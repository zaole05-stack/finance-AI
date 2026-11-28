"""Tests für M2 mit echten Form-4-Meldungen vom 24.11.2026 (SEC EDGAR, gemeinfrei)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from finance_ai.core import storage
from finance_ai.core.models import Side
from finance_ai.data.form4 import parse_form4
from finance_ai.data.sec_edgar import (
    EdgarClient,
    FilingRef,
    current_feed_url,
    daily_index_url,
    parse_current_feed,
    parse_form4_index,
    parse_submission,
    recent_form4_filings,
)
from finance_ai.experts import insider

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
ALDX = "0001193125-26-473131"  # CEO kauft 300.000 Aktien, ~243.000 USD
CBK = "0000898432-26-000808"  # CFO kauft für ~11.000 USD, unter der Schwelle
LEE = "0001183010-26-000071"  # Director-Käufe aus einem 10b5-1-Plan
NO_TICKER = "0001193125-26-476047"  # Kauf, aber Firma ohne Börsenkürzel
DGICA = "0000935596-26-000033"  # Kauf eines reinen 10%-Eigentümers
LATER = datetime(2026, 11, 25, 8, tzinfo=UTC)


def index_refs() -> dict[str, FilingRef]:
    text = (FIXTURES / "form.20261124.idx").read_text(encoding="utf-8")
    return {ref.accession: ref for ref in parse_form4_index(text)}


def filing(accession: str):
    text = (FIXTURES / f"{accession}.txt").read_text(encoding="utf-8")
    return parse_submission(index_refs()[accession], text)


def test_index_keeps_form4_once_per_filing():
    refs = index_refs()
    # 10 Form-4-Zeilen, 5 Meldungen. 4/A und 8-K fallen weg.
    assert sorted(refs) == sorted([ALDX, CBK, LEE, NO_TICKER, DGICA])
    assert refs[ALDX].txt_url.endswith(f"edgar/data/1341235/{ALDX}.txt")
    assert refs[ALDX].index_url == (
        "https://www.sec.gov/Archives/edgar/data/1341235/000119312526473131/"
        f"{ALDX}-index.htm"
    )


def test_daily_index_url():
    assert daily_index_url(date(2026, 11, 24)) == (
        "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/form.20261124.idx"
    )
    assert "/QTR1/form.20260102.idx" in daily_index_url(date(2026, 1, 2))


def test_acceptance_time_is_eastern():
    # <ACCEPTANCE-DATETIME>20261124065832 → 06:58:32 New York = 11:58:32 UTC (Winterzeit)
    assert filing(ALDX).accepted_at.astimezone(UTC) == datetime(2026, 11, 24, 11, 58, 32, tzinfo=UTC)


def test_submission_without_xml_is_rejected():
    with pytest.raises(ValueError, match="kein XML"):
        parse_submission(index_refs()[ALDX], "<ACCEPTANCE-DATETIME>20261124065832\n")


def test_parse_form4_fields():
    doc = parse_form4(filing(ALDX).xml)
    assert (doc.issuer_name, doc.ticker, doc.is_10b5_1_plan) == (
        "Aldeyra Therapeutics, Inc.", "ALDX", False,
    )
    owner = doc.owners[0]
    assert owner.name == "Brady Todd C"
    assert owner.is_officer and owner.role.startswith("President and CEO")
    tx = doc.transactions[0]
    assert (tx.code, tx.acquired, tx.shares, tx.price, tx.day) == (
        "P", True, D("300000"), D("0.8102"), date(2026, 11, 20),
    )


def test_parse_form4_flags_and_missing_ticker():
    assert parse_form4(filing(LEE).xml).is_10b5_1_plan is True
    assert parse_form4(filing(NO_TICKER).xml).ticker is None


def test_parse_form4_rejects_other_documents():
    with pytest.raises(ValueError):
        parse_form4("<html/>")
    with pytest.raises(ValueError):
        parse_form4("kein xml")


def test_known_insider_purchase_gives_correct_signal():
    """Prüfkriterium M2: Für einen bekannten Insider-Kauf entsteht das richtige Signal."""
    source = filing(ALDX)
    signal = insider.signal_from_filing(source, LATER)
    assert signal is not None
    assert signal.id == f"insider:{ALDX}"
    assert (signal.expert, signal.ticker, signal.side) == ("insider", "ALDX", Side.BUY)
    assert signal.source_url == source.ref.index_url
    assert signal.observed_at == source.accepted_at
    assert signal.created_at == LATER
    assert "Brady Todd C" in signal.summary
    assert "300000 Aktien" in signal.summary
    assert "0.8102 USD" in signal.summary
    assert "243060 USD" in signal.summary
    assert "2026-11-20" in signal.summary


def form4_args(source, **changes):
    """Angaben für signal_from_form4 aus einer Meldung, so wie sie der Backtest liefert."""
    args = dict(
        accession=source.ref.accession,
        source_url=source.ref.index_url,
        observed_at=source.accepted_at,
        issuer_sic=source.issuer_sic,
        created_at=LATER,
    )
    return {**args, **changes}


def test_signal_from_form4_matches_filing_path():
    """Backtest und Live-Betrieb ergeben aus derselben Meldung dasselbe Signal."""
    for accession in (ALDX, CBK, LEE, NO_TICKER, DGICA):
        source = filing(accession)
        doc = parse_form4(source.xml)
        assert insider.signal_from_form4(doc, **form4_args(source)) == (
            insider.signal_from_filing(source, LATER)
        ), accession


def test_signal_from_form4_applies_rules_itself():
    source = filing(ALDX)
    doc = parse_form4(source.xml)
    assert insider.signal_from_form4(doc, **form4_args(source, issuer_sic="6798")) is None
    assert insider.signal_from_form4(doc, **form4_args(source, issuer_sic=None)) is None
    assert insider.signal_from_form4(doc, **form4_args(source), min_value=D("300000")) is None


@pytest.mark.parametrize(
    ("accession", "reason"),
    [
        (CBK, "unter Mindestwert"),
        (LEE, "10b5-1-Plan"),
        (NO_TICKER, "kein Börsenkürzel"),
        (DGICA, "nur 10%-Eigentümer"),
    ],
)
def test_filtered_filings_give_no_signal(accession, reason):
    assert insider.signal_from_filing(filing(accession), LATER) is None, reason


def test_min_value_is_configurable():
    assert insider.signal_from_filing(filing(CBK), LATER, min_value=D("10000")) is not None
    assert insider.signal_from_filing(filing(ALDX), LATER, min_value=D("300000")) is None


def test_scan_day_offline():
    class FakeClient:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            name = "form.20261124.idx" if url.endswith(".idx") else url.rsplit("/", 1)[-1]
            return (FIXTURES / name).read_text(encoding="utf-8")

    client = FakeClient()
    signals = insider.scan_day(client, date(2026, 11, 24), clock=lambda: LATER)
    assert [s.ticker for s in signals] == ["ALDX"]
    assert len(client.urls) == 1 + 5  # Index plus jede Meldung genau einmal


def test_scan_day_without_index_gives_nothing():
    class Holiday:
        def get(self, url):
            return None

    assert insider.scan_day(Holiday(), date(2026, 11, 26)) == []


def test_saving_signals_twice_does_not_duplicate():
    conn = storage.connect()
    signal = insider.signal_from_filing(filing(ALDX), LATER)
    assert storage.save_new_signals(conn, [signal]) == 1
    rerun = insider.signal_from_filing(filing(ALDX), LATER + timedelta(hours=1))
    assert storage.save_new_signals(conn, [rerun]) == 0
    assert storage.list_signals(conn, "insider") == [signal]


def test_client_requires_contact():
    with pytest.raises(ValueError):
        EdgarClient("finance-ai")


@pytest.mark.network
def test_live_edgar_scan():
    from finance_ai.config import MissingSetting, sec_user_agent

    try:
        client = EdgarClient(sec_user_agent())
    except MissingSetting as error:
        pytest.skip(str(error))
    day = date.today() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    refs = insider.form4_filings(client, day)
    assert refs, f"Kein Form-4-Index für {day}"
    filing_ = insider.fetch_filing(client, refs[0])
    assert filing_ is not None
    parse_form4(filing_.xml)


def flaky_client(errors):
    """Client, dessen erste Anfragen mit den gegebenen Fehlern scheitern."""
    client = EdgarClient("test test@example.org", min_interval=0, backoff=0)
    calls = []

    def once(url):
        calls.append(url)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return "ok"

    client._get_once = once
    return client, calls


def http_error(code):
    import urllib.error

    return urllib.error.HTTPError("https://www.sec.gov/x", code, "x", {}, None)


def test_client_retries_transient_errors():
    client, calls = flaky_client([ConnectionResetError(), http_error(503), http_error(429)])
    assert client.get("u") == "ok"
    assert len(calls) == 4


def test_client_gives_up_after_retries():
    client, calls = flaky_client([ConnectionResetError()] * 4)
    with pytest.raises(ConnectionResetError):
        client.get("u")
    assert len(calls) == 4


def test_client_404_and_403():
    client, calls = flaky_client([http_error(404)])
    assert client.get("u") is None
    client, calls = flaky_client([http_error(403)])
    with pytest.raises(Exception, match="403"):
        client.get("u")
    assert len(calls) == 1


def test_scan_day_skips_unreachable_filing():
    class Partial:
        def get(self, url):
            if url.endswith(f"{CBK}.txt"):
                raise ConnectionResetError("weg")
            name = "form.20261124.idx" if url.endswith(".idx") else url.rsplit("/", 1)[-1]
            return (FIXTURES / name).read_text(encoding="utf-8")

    signals = insider.scan_day(Partial(), date(2026, 11, 24), clock=lambda: LATER)
    assert [s.ticker for s in signals] == ["ALDX"]


def test_issuer_sic_from_header():
    assert filing(ALDX).issuer_sic == "2834"  # Pharma
    assert filing(CBK).issuer_sic == "6022"  # Bank


@pytest.mark.parametrize("sic", [None, "6798", "6726", "6770"])
def test_funds_reits_and_spacs_give_no_signal(sic):
    from dataclasses import replace

    assert insider.signal_from_filing(replace(filing(ALDX), issuer_sic=sic), LATER) is None


# --- Atom-Feed der neuesten Meldungen -------------------------------------
#
# current_form4_20261126.atom ist ein unveränderter Ausschnitt des echten Feeds
# (abgerufen am 26.11.2026, Einträge vom 25.11.2026 17:24–17:29 New York).
# Er enthält 20 Einträge: 4 Form-4-Meldungen in 10 Einträgen, dazu 424B2,
# 424B5 und 425, die über den Präfix-Filter type=4 mit hineinrutschen.

FEED = FIXTURES / "current_form4_20261126.atom"
NEPTUNE = "0001628280-26-076022"
PIMCO = "0001510281-26-000477"
COVENANT = "0001008886-26-000256"


def feed_page():
    return parse_current_feed(FEED.read_text(encoding="utf-8"))


def eastern(text):
    return datetime.fromisoformat(text)


def test_feed_keeps_only_form4_once_per_filing():
    page = feed_page()
    assert page.size == 20
    assert [e.ref.accession for e in page.entries] == [NEPTUNE, PIMCO, COVENANT]
    assert page.oldest == eastern("2026-11-25T17:24:58-05:00")


def test_feed_prefers_issuer_cik():
    refs = {e.ref.accession: e.ref for e in feed_page().entries}
    # Bei Covenant stehen die meldenden Personen vor dem Emittenten im Feed.
    assert refs[COVENANT].cik == "0000928658"
    assert refs[COVENANT].index_url == (
        "https://www.sec.gov/Archives/edgar/data/928658/000100888626000256/"
        f"{COVENANT}-index.htm"
    )
    assert refs[COVENANT].txt_url == (
        f"https://www.sec.gov/Archives/edgar/data/928658/{COVENANT}.txt"
    )
    assert refs[NEPTUNE].cik == "0002067129"


def test_feed_entry_time_keeps_offset():
    entry = feed_page().entries[0]
    assert entry.updated.astimezone(UTC) == datetime(2026, 11, 25, 22, 27, 15, tzinfo=UTC)


def test_feed_rejects_broken_xml():
    with pytest.raises(ValueError, match="Atom-Feed"):
        parse_current_feed("<feed")


def test_current_feed_url():
    assert current_feed_url(start=200, count=20) == (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4"
        "&owner=include&count=20&start=200&output=atom"
    )


class FeedClient:
    """Liefert vorgegebene Feed-Seiten der Reihe nach und Meldungen aus den Fixtures."""

    def __init__(self, *pages):
        self.pages = list(pages)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if "getcurrent" in url:
            return self.pages.pop(0) if self.pages else None
        return (FIXTURES / url.rsplit("/", 1)[-1]).read_text(encoding="utf-8")


def test_recent_filings_stop_at_since():
    client = FeedClient(FEED.read_text(encoding="utf-8"))
    refs = recent_form4_filings(client, since=eastern("2026-11-25T17:25:00-05:00"))
    assert [r.accession for r in refs] == [NEPTUNE, PIMCO]
    assert len(client.urls) == 1


def test_recent_filings_page_until_since():
    # Bei Seitengröße 20 ist der Ausschnitt eine volle Seite. Er reicht nicht
    # bis `since`, also wird die nächste Seite geladen.
    older = constructed_feed(
        (ALDX, "0001341235", "Issuer", "2026-11-25T17:20:00-05:00"),
        (CBK, "0001981546", "Issuer", "2026-11-25T16:00:00-05:00"),
    )
    client = FeedClient(FEED.read_text(encoding="utf-8"), older)
    refs = recent_form4_filings(
        client, since=eastern("2026-11-25T17:00:00-05:00"), page_size=20
    )
    assert [r.accession for r in refs] == [NEPTUNE, PIMCO, COVENANT, ALDX]
    assert "start=20" in client.urls[1]


def test_recent_filings_respect_max_pages():
    page = FEED.read_text(encoding="utf-8")
    client = FeedClient(page, page, page)
    recent_form4_filings(client, since=eastern("2026-11-24T00:00:00-05:00"),
                         max_pages=2, page_size=20)
    assert len(client.urls) == 2


def constructed_feed(*entries):
    """Feed im Format des echten Feeds, aus Meldungen, die als Fixture vorliegen."""
    body = "".join(
        f"""<entry>
<title>4 - Firma ({cik}) ({role})</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index.htm"/>
<updated>{updated}</updated>
<category scheme="https://www.sec.gov/" label="form type" term="4"/>
<id>urn:tag:sec.gov,2008:accession-number={acc}</id>
</entry>"""
        for acc, cik, role, updated in entries
    )
    return (
        '<?xml version="1.0" encoding="ISO-8859-1" ?>\n'
        f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'
    )


def test_scan_recent_finds_known_purchase_minutes_after_filing():
    """Über den Feed entsteht dasselbe Signal wie über den Tagesindex."""
    feed = constructed_feed(
        (ALDX, "0001579179", "Reporting", "2026-11-24T06:58:32-05:00"),
        (ALDX, "0001341235", "Issuer", "2026-11-24T06:58:32-05:00"),
        (CBK, "0001981546", "Issuer", "2026-11-24T06:40:00-05:00"),
    )
    client = FeedClient(feed)
    minutes_later = datetime(2026, 11, 24, 12, 5, tzinfo=UTC)
    signals = insider.scan_recent(
        client, since=eastern("2026-11-24T06:00:00-05:00"), clock=lambda: minutes_later
    )
    assert [s.ticker for s in signals] == ["ALDX"]
    assert signals[0].id == f"insider:{ALDX}"
    assert signals[0].created_at - signals[0].observed_at < timedelta(minutes=10)
    assert len(client.urls) == 1 + 2  # eine Feed-Seite, dann jede Meldung einmal


def test_scan_recent_without_feed_gives_nothing():
    assert insider.scan_recent(FeedClient(), since=LATER) == []


@pytest.mark.network
def test_live_current_feed():
    from finance_ai.config import MissingSetting, sec_user_agent

    try:
        client = EdgarClient(sec_user_agent())
    except MissingSetting as error:
        pytest.skip(str(error))
    page = parse_current_feed(client.get(current_feed_url(count=40)) or "")
    assert page.size > 0
    assert all(e.ref.accession for e in page.entries)


def test_confidence_ranks_top_executives_higher():
    from finance_ai.data.form4 import Owner

    def owner(title, officer=True, director=False):
        return Owner("X", director, officer, False, title)

    assert insider.signal_from_filing(filing(ALDX), LATER).confidence == 0.6
    assert insider._confidence([owner("Chief Financial Officer")]) == 0.6
    assert insider._confidence([owner("Chairman of the Board")]) == 0.6
    assert insider._confidence([owner("Executive Vice President, Sales")]) == 0.5
    assert insider._confidence([owner("", officer=False, director=True)]) == 0.5
