"""Quartalsdatensätze der SEC zu Insider-Meldungen (Insider Transactions Data Sets).

Die SEC stellt alle Form-3/4/5-Meldungen ab 2006 als ein ZIP je Quartal bereit,
je etwa 8–16 MB. Sie enthalten das XML der Meldungen in flacher Form, als
tab-getrennte UTF-8-Dateien. Gelesen werden drei davon: SUBMISSION (eine Zeile
je Meldung), REPORTINGOWNER (je meldender Person) und NONDERIV_TRANS (je
Aktiengeschäft). Daraus entsteht dasselbe `Form4`, das live aus dem XML kommt.
So gelten im Backtest genau die Regeln aus `experts/insider.py`.

Unterschiede zum XML, die der Backtest ausweisen muss:
- Preise sind auf 2 Nachkommastellen gerundet (72,29 statt 72,2898). Bei
  Pennystocks verschiebt das Beträge um bis zu einige Prozent.
- Es gibt nur das Meldedatum, keine Uhrzeit. Meldungen nach 17:30 Uhr
  New York zählen zum nächsten Tag. Als Zeitpunkt gilt deshalb 17:30 Uhr am
  Meldetag. Das ist nie früher als die tatsächliche Annahme.
- Das 10b5-1-Kennzeichen (`AFF10B5ONE`) gibt es erst ab 2023.

Quelle und Dokumentation:
https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from finance_ai.data.form4 import Form4, Owner, Transaction, clean_ticker
from finance_ai.data.sec_edgar import EASTERN, FilingRef

DATASETS_PAGE = (
    "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
)
FILING_CUTOFF = time(17, 30)
_QUARTER_LINK = re.compile(r'href="([^"]*/((\d{4})q([1-4]))_form345\.zip)"')
_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
    start=1,
)}
_TRUE = {"1", "true"}


class Client(Protocol):
    def get(self, url: str) -> str | None: ...

    def get_bytes(self, url: str) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class DatasetFiling:
    """Eine Form-4-Meldung aus einem Quartalsdatensatz."""

    accession: str
    filing_date: date
    issuer_cik: str
    form4: Form4

    @property
    def observed_at(self) -> datetime:
        """Spätester möglicher Annahmezeitpunkt: 17:30 Uhr New York am Meldetag."""
        return datetime.combine(self.filing_date, FILING_CUTOFF, tzinfo=EASTERN)

    @property
    def source_url(self) -> str:
        """Übersichtsseite der Meldung bei der SEC, wie bei live erzeugten Signalen."""
        return FilingRef(self.accession, self.issuer_cik, "").index_url


def parse_date(raw: str) -> date:
    """Datum im Format der Datensätze, z. B. '31-JUL-2026'."""
    day, month, year = raw.strip().split("-")
    return date(int(year), _MONTHS[month.upper()], int(day))


def parse_flag(raw: str) -> bool:
    """Ja/Nein-Feld. Vorkommende Schreibweisen: 1, 0, true, false, leer."""
    return raw.strip().lower() in _TRUE


def read_quarter(path: Path) -> Iterator[DatasetFiling]:
    """Alle Form-4-Meldungen eines Quartals. Korrekturen (4/A) fallen weg."""
    with zipfile.ZipFile(path) as archive:
        owners: dict[str, list[Owner]] = defaultdict(list)
        for row in _rows(archive, "REPORTINGOWNER.tsv"):
            owners[row["ACCESSION_NUMBER"]].append(_owner(row))
        transactions: dict[str, list[tuple[int, Transaction]]] = defaultdict(list)
        for row in _rows(archive, "NONDERIV_TRANS.tsv"):
            tx = _transaction(row)
            if tx is not None:
                transactions[row["ACCESSION_NUMBER"]].append((int(row["NONDERIV_TRANS_SK"]), tx))
        for row in _rows(archive, "SUBMISSION.tsv"):
            if row["DOCUMENT_TYPE"].strip() != "4":
                continue
            accession = row["ACCESSION_NUMBER"]
            yield DatasetFiling(
                accession=accession,
                filing_date=parse_date(row["FILING_DATE"]),
                issuer_cik=row["ISSUERCIK"].strip(),
                form4=Form4(
                    issuer_cik=row["ISSUERCIK"].strip(),
                    issuer_name=row["ISSUERNAME"].strip(),
                    ticker=clean_ticker(row["ISSUERTRADINGSYMBOL"]),
                    owners=tuple(owners.get(accession, ())),
                    # Reihenfolge wie in der Meldung, nach dem Schlüssel der SEC
                    transactions=tuple(tx for _, tx in sorted(transactions.get(accession, ()),
                                                              key=lambda item: item[0])),
                    is_10b5_1_plan=parse_flag(row.get("AFF10B5ONE") or ""),
                ),
            )


def _rows(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with archive.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        # Felder mit Tabs oder Anführungszeichen stehen in "...", "" ist ein Zeichen ".
        yield from csv.DictReader(text, delimiter="\t")


def _owner(row: dict[str, str]) -> Owner:
    roles = {part.strip().lower() for part in row["RPTOWNER_RELATIONSHIP"].split(",")}
    return Owner(
        name=row["RPTOWNERNAME"].strip(),
        is_director="director" in roles,
        is_officer="officer" in roles,
        is_ten_percent_owner="tenpercentowner" in roles,
        officer_title=(row.get("RPTOWNER_TITLE") or "").strip(),
    )


def _transaction(row: dict[str, str]) -> Transaction | None:
    """Wie im XML-Parser: ohne Stückzahl, Preis oder Datum keine Transaktion."""
    shares = _decimal(row["TRANS_SHARES"])
    price = _decimal(row["TRANS_PRICEPERSHARE"])
    if shares is None or price is None or shares <= 0 or price <= 0 or not row["TRANS_DATE"]:
        return None
    return Transaction(
        code=(row["TRANS_CODE"] or "").strip().upper(),
        acquired=row["TRANS_ACQUIRED_DISP_CD"].strip().upper() == "A",
        shares=shares,
        price=price,
        day=parse_date(row["TRANS_DATE"]),
    )


def _decimal(raw: str | None) -> Decimal | None:
    try:
        number = Decimal((raw or "").strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def parse_quarter_links(page: str) -> dict[str, str]:
    """Download-Adressen je Quartal ('2026q3' → URL) von der Übersichtsseite.

    Die Pfade unterscheiden sich je Quartal (z. B. `datastandardsinnovation/`
    und `structureddata/`), deshalb werden sie gelesen statt zusammengesetzt.
    """
    links = {}
    for href, quarter, _, _ in _QUARTER_LINK.findall(page):
        links[quarter] = href if href.startswith("http") else "https://www.sec.gov" + href
    return links


def download_quarters(
    client: Client, dest: Path, only: set[str] | None = None
) -> list[Path]:
    """Lädt fehlende Quartale nach `dest`. Vorhandene Dateien werden nicht erneut geladen.

    Gibt die Pfade aller gewünschten Quartale zurück, nach Quartal sortiert.
    """
    page = client.get(DATASETS_PAGE)
    if not page:
        raise RuntimeError(f"Übersichtsseite nicht erreichbar: {DATASETS_PAGE}")
    links = parse_quarter_links(page)
    if only is not None:
        links = {q: url for q, url in links.items() if q in only}
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for quarter in sorted(links):
        path = dest / f"{quarter}_form345.zip"
        if not path.exists():
            data = client.get_bytes(links[quarter])
            if data is None:
                raise RuntimeError(f"Quartal {quarter} nicht gefunden: {links[quarter]}")
            partial = path.with_suffix(".part")
            partial.write_bytes(data)
            partial.replace(path)  # erst vollständig, dann sichtbar
        paths.append(path)
    return paths
