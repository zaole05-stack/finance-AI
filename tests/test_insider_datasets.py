"""Tests für den Lader der SEC-Quartalsdatensätze (Insider Transactions Data Sets).

Die Fixture in tests/fixtures/insider_datasets/ ist ein Ausschnitt aus
2026q3_form345.zip (SEC, gemeinfrei): alle Zeilen von fünf Meldungen, Spalten
unverändert. Nur die Wohnadressen der Insider (Straße, Ort, PLZ) sind geleert.

- DBD  0001368469-26-000010  CFO kauft 700 Aktien zu 72,29 USD (im XML 72,2898)
- GPUS 0001214659-26-011255  gemeinsame Meldung, 4 Käufe und 1 Verkauf
- FIS  0001628280-26-048468  Director kauft aus einem 10b5-1-Plan
- CATLU 0001213900-26-083960 nur ein 10%-Eigentümer
- DLHC 0001628280-26-051490  Korrektur (4/A)
"""

import zipfile
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from finance_ai.data import sec_insider_datasets as ds
from finance_ai.data.sec_edgar import EASTERN, FilingRef, parse_submission
from finance_ai.experts import insider

FIXTURES = Path(__file__).parent / "fixtures"
EXCERPT = FIXTURES / "insider_datasets"
DBD = "0001368469-26-000010"
GPUS = "0001214659-26-011255"
FIS = "0001628280-26-048468"
CATLU = "0001213900-26-083960"
DLHC = "0001628280-26-051490"
LATER = datetime(2026, 11, 26, 12, tzinfo=UTC)


@pytest.fixture
def quarter(tmp_path) -> Path:
    """Die Fixture als ZIP, so wie die SEC sie ausliefert."""
    path = tmp_path / "2026q3_form345.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for tsv in EXCERPT.glob("*.tsv"):
            archive.write(tsv, tsv.name)
    return path


def filings(quarter) -> dict[str, ds.DatasetFiling]:
    return {f.accession: f for f in ds.read_quarter(quarter)}


def signal(filing: ds.DatasetFiling, sic: str = "3578", **changes):
    doc = replace(filing.form4, **changes) if changes else filing.form4
    return insider.signal_from_form4(
        doc,
        accession=filing.accession,
        source_url=filing.source_url,
        observed_at=filing.observed_at,
        issuer_sic=sic,
        created_at=LATER,
    )


def test_only_original_form4_filings(quarter):
    assert sorted(filings(quarter)) == sorted([DBD, GPUS, FIS, CATLU])  # ohne 4/A


def test_fields_of_known_purchase(quarter):
    filing = filings(quarter)[DBD]
    doc = filing.form4
    assert (filing.filing_date, filing.issuer_cik) == (date(2026, 7, 31), "0000028823")
    assert (doc.issuer_name, doc.ticker, doc.is_10b5_1_plan) == (
        "DIEBOLD NIXDORF, Inc", "DBD", False,
    )
    (owner,) = doc.owners
    assert (owner.name, owner.is_officer, owner.is_director, owner.officer_title) == (
        "Timko Thomas S", True, False, "EVP, CFO",
    )
    (tx,) = doc.transactions
    assert (tx.code, tx.acquired, tx.shares, tx.price, tx.day) == (
        "P", True, D("700"), D("72.29"), date(2026, 7, 31),
    )


def test_filing_time_is_end_of_filing_day_in_new_york(quarter):
    # Die Datensätze kennen nur das Datum. Spätere Annahmen zählen zum nächsten Tag.
    observed = filings(quarter)[DBD].observed_at
    assert observed == datetime(2026, 7, 31, 17, 30, tzinfo=EASTERN)


def test_same_signal_as_xml_path_up_to_rounding(quarter):
    """Prüfkriterium: Der Datensatz ergibt dasselbe Signal wie die Einreichung."""
    text = (FIXTURES / "edgar" / f"{DBD}.txt").read_text(encoding="utf-8")
    ref = FilingRef(DBD, "0000028823", f"edgar/data/28823/{DBD}.txt")
    from_xml = insider.signal_from_filing(parse_submission(ref, text), LATER)
    from_dataset = signal(filings(quarter)[DBD])
    assert from_xml is not None and from_dataset is not None
    same = ("id", "expert", "ticker", "side", "source_url", "created_at", "confidence")
    assert {k: getattr(from_dataset, k) for k in same} == {k: getattr(from_xml, k) for k in same}
    # Die Datensätze runden Preise auf 2 Stellen (72,29 statt 72,2898).
    assert "72.2898 USD" in from_xml.summary and "72.2900 USD" in from_dataset.summary
    for part in ("Timko Thomas S", "700 Aktien", "zusammen 50603 USD"):
        assert part in from_dataset.summary
    # Angenommen ist die Meldung um 16:21, der Datensatz setzt konservativ 17:30.
    assert from_dataset.observed_at.date() == from_xml.observed_at.date()
    assert from_dataset.observed_at >= from_xml.observed_at


def test_joint_filing_sums_purchases_only(quarter):
    filing = filings(quarter)[GPUS]
    roles = {o.name: (o.is_director, o.is_officer, o.is_ten_percent_owner) for o in filing.form4.owners}
    assert roles == {
        "Ault & Company, Inc.": (False, False, True),
        "AULT MILTON C III": (True, True, True),
    }
    result = signal(filing, sic="7374")
    assert result is not None
    # 150000*0,30 + 47641*0,31 + 10000*0,34 + 89000*0,27 = 87198,71, der Verkauf zählt nicht.
    assert "zusammen 87199 USD" in result.summary
    assert "2026-08-27 bis 2026-08-31" in result.summary


def test_10b5_1_plan_flag(quarter):
    filing = filings(quarter)[FIS]
    assert filing.form4.is_10b5_1_plan is True
    assert signal(filing, sic="7374") is None
    assert signal(filing, sic="7374", is_10b5_1_plan=False) is not None


def test_ten_percent_owner_only_gives_no_signal(quarter):
    assert signal(filings(quarter)[CATLU], sic="2834") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("31-JUL-2026", date(2026, 7, 31)), ("02-Jan-2006", date(2006, 1, 2))],
)
def test_parse_date(raw, expected):
    assert ds.parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "True"])
def test_plan_flag_true_spellings(raw):
    assert ds.parse_flag(raw) is True


@pytest.mark.parametrize("raw", ["0", "false", "", "  "])
def test_plan_flag_false_spellings(raw):
    assert ds.parse_flag(raw) is False


PAGE = """
<a href="/files/datastandardsinnovation/data/insider-transactions-data-sets/2026q3_form345.zip">2026 Q3</a>
<a href="https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2026q1_form345.zip">2026 Q1</a>
<a href="/files/insider_transactions_readme.pdf">Readme</a>
"""


def test_quarter_links_come_from_the_page():
    # Die Pfade sind je Quartal verschieden, deshalb werden sie nicht zusammengesetzt.
    assert ds.parse_quarter_links(PAGE) == {
        "2026q3": "https://www.sec.gov/files/datastandardsinnovation/data/"
        "insider-transactions-data-sets/2026q3_form345.zip",
        "2026q1": "https://www.sec.gov/files/structureddata/data/"
        "insider-transactions-data-sets/2026q1_form345.zip",
    }


class FakeClient:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return PAGE

    def get_bytes(self, url):
        self.urls.append(url)
        return b"zip:" + url.encode()


def test_download_skips_existing_files(tmp_path):
    (tmp_path / "2026q3_form345.zip").write_bytes(b"schon da")
    client = FakeClient()
    paths = ds.download_quarters(client, tmp_path)
    assert [p.name for p in paths] == ["2026q1_form345.zip", "2026q3_form345.zip"]
    assert (tmp_path / "2026q3_form345.zip").read_bytes() == b"schon da"
    assert (tmp_path / "2026q1_form345.zip").read_bytes().startswith(b"zip:")
    assert len(client.urls) == 2  # Übersichtsseite und ein fehlendes Quartal


def test_download_can_be_limited_to_quarters(tmp_path):
    client = FakeClient()
    paths = ds.download_quarters(client, tmp_path, only={"2026q3"})
    assert [p.name for p in paths] == ["2026q3_form345.zip"]
    assert not (tmp_path / "2026q1_form345.zip").exists()
