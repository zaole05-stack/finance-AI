"""Tests für Firmendaten von der SEC: Branchencode, Kürzel, Aktienzahl, Ereignisse.

Fixtures in tests/fixtures/sec_company/ sind gekürzte echte Antworten der SEC
für Diebold Nixdorf (CIK 28823), abgerufen am 26.11.2026:
- CIK0000028823.json: Stammdaten und ausgewählte Meldungen (10-K, 8-K mit
  Punkt 1.03, 25-NSE, S-4). Diebold meldete 2023 Insolvenz an, wurde delistet
  und notiert seither neu unter DBD.
- CIK0000028823-submissions-001.json: ältere Meldungen, auf 10-K ab 2014 gekürzt.
- companyfacts-CIK0000028823.json: nur die beiden Aktienzahl-Angaben.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from finance_ai.data import sec_company as sc

FIXTURES = Path(__file__).parent / "fixtures" / "sec_company"
CIK = "0000028823"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def diebold() -> sc.CompanyInfo:
    return sc.company_from_json(
        json.loads(fixture("CIK0000028823.json")),
        json.loads(fixture("companyfacts-CIK0000028823.json")),
        [json.loads(fixture("CIK0000028823-submissions-001.json"))],
    )


def test_master_data():
    info = diebold()
    assert (info.cik, info.sic, info.tickers) == (CIK, "3578", ("DBD",))


def test_events_bankruptcy_and_delisting():
    events = diebold().events
    assert sc.Event(date(2023, 6, 1), "8-K 1.03") in events
    assert sc.Event(date(2023, 6, 20), "25-NSE") in events
    # Diebold hat das S-4 als Käufer eingereicht. Für das Ziel sagt es nichts.
    assert not any(e.form.startswith("S-4") for e in events)
    assert events == tuple(sorted(events))


def test_shares_only_from_reports_filed_before_the_day():
    info = diebold()
    # Der erste Bericht mit Aktienzahl wurde am 9.8.2010 eingereicht.
    assert info.shares_at(date(2010, 8, 9)) is None
    assert info.shares_at(date(2010, 8, 10)) == 65_690_461
    # Nach der Insolvenz 2023 gibt es neue Aktien, ab dem Bericht vom 9.11.2023.
    assert info.shares_at(date(2023, 11, 9)) == 80_036_836
    assert info.shares_at(date(2023, 11, 10)) == 37_566_668


def test_stale_share_count_is_unknown():
    info = diebold()
    last = max(s.end for s in info.shares)
    assert info.shares_at(last + timedelta(days=sc.MAX_SHARES_AGE.days)) is not None
    assert info.shares_at(last + timedelta(days=sc.MAX_SHARES_AGE.days + 30)) is None


def test_balance_sheet_count_uses_latest_period_not_prior_year():
    # In den Berichten stehen auch Vorjahreswerte (z. B. Stand 31.12.2009 im
    # Bericht vom November 2010). Gewählt wird der jüngste Stichtag.
    facts = json.loads(fixture("companyfacts-CIK0000028823.json"))
    del facts["facts"]["dei"]
    info = sc.company_from_json(json.loads(fixture("CIK0000028823.json")), facts, [])
    assert info.shares_at(date(2010, 11, 6)) == 65_690_022  # Stand 30.9.2010


def test_cover_page_count_preferred():
    # Gibt es beide Angaben, gilt die vom Deckblatt (dei), sie ist aktueller.
    assert diebold().shares_at(date(2010, 11, 6)) == 65_679_549


def test_company_without_xbrl_facts():
    info = sc.company_from_json(json.loads(fixture("CIK0000028823.json")), None, [])
    assert info.shares == () and info.shares_at(date(2020, 1, 1)) is None
    assert info.sic == "3578"


class FakeClient:
    def __init__(self, facts=True):
        self.urls = []
        self.facts = facts

    def get(self, url):
        self.urls.append(url)
        name = url.rsplit("/", 1)[-1]
        if "companyfacts" in url:
            # Viele kleine und alte Firmen haben keine XBRL-Daten (404).
            return fixture(f"companyfacts-{name}") if self.facts else None
        return fixture(name)


def test_load_fetches_once_and_caches(tmp_path):
    client = FakeClient()
    first = sc.load_company(client, "28823", tmp_path)
    assert first == diebold()
    assert [u.rsplit("/", 1)[-1] for u in client.urls] == [
        "CIK0000028823.json",
        "CIK0000028823-submissions-001.json",
        "CIK0000028823.json",  # companyfacts
    ]
    assert "companyfacts" in client.urls[2]
    again = sc.load_company(client, "28823", tmp_path)
    assert again == first
    assert len(client.urls) == 3  # zweiter Aufruf nur aus dem Zwischenspeicher


def test_load_company_without_facts(tmp_path):
    info = sc.load_company(FakeClient(facts=False), "28823", tmp_path)
    assert info.shares == () and info.sic == "3578"


def test_unknown_company_is_none(tmp_path):
    class Nothing:
        def get(self, url):
            return None

    assert sc.load_company(Nothing(), "1", tmp_path) is None


@pytest.mark.network
def test_live_company():
    from finance_ai.config import MissingSetting, sec_user_agent
    from finance_ai.data.sec_edgar import EdgarClient

    try:
        client = EdgarClient(sec_user_agent())
    except MissingSetting as error:
        pytest.skip(str(error))
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        info = sc.load_company(client, "28823", Path(folder))
    assert info is not None and info.sic == "3578" and info.shares
