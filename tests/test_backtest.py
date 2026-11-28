"""Tests für die Signale des Insider-Backtests (Plan-Schritt 5).

Geprüft wird nur, welche Signale entstehen und welchen Status sie haben.
Renditen kommen erst in Schritt 6.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from finance_ai.data.form4 import Form4, Owner, Transaction
from finance_ai.data.sec_company import CompanyInfo, Event, MissingPrice, ShareCount
from finance_ai.data.sec_insider_datasets import DatasetFiling
from finance_ai.evaluation import backtest as bt
from finance_ai.paper_trading.daily_prices import PriceCheck, PriceStatus

HOLD = timedelta(days=91)
NOW = datetime(2026, 11, 28, tzinfo=UTC)
CEO = Owner("Muster Max", False, True, False, "CEO")
DAY = date(2015, 3, 2)


def filing(ticker="ABC", cik="1", day=DAY, price="10", shares="5000", n=1):
    tx = Transaction("P", True, D(shares), D(price), day - timedelta(days=2))
    return DatasetFiling(
        f"0000000000-15-{n:06d}", day, cik,
        Form4(cik, f"Firma {n}", ticker, (CEO,), (tx,), False),
    )


def company(cik="1", sic="2834", shares=(), events=()):
    return CompanyInfo(cik, sic, (), tuple(shares), tuple(events))


def shares(filed, end, count=1_000_000):
    return ShareCount(filed, end, count, True)


class FakePrices:
    """Ergebnis der Kursprüfung, letzter Kurstag und damaliger Schlusskurs je Tag."""

    def __init__(self, check=None, last_day=date(2026, 11, 25), closes=None):
        self._check = check or PriceCheck(PriceStatus.OK, "ABC")
        self._last = last_day
        self._closes = closes or {}
        self.asked_close_for: list[date] = []

    def check(self, ticker, info, day, price):
        return self._check

    def last_bar_day(self, ticker):
        return self._last

    def raw_close(self, ticker, day):
        self.asked_close_for.append(day)
        return self._closes.get(day)


def classify(f, info, prices):
    return bt.classify(f, info, prices, HOLD, NOW)


def test_ok_signal_with_market_cap_from_close_on_filing_day():
    info = company(shares=[shares(date(2015, 2, 1), date(2014, 12, 31), 2_000_000)])
    prices = FakePrices(closes={DAY: D("12"), DAY + timedelta(days=1): D("50")})
    s = classify(filing(), info, prices)
    assert s.status is bt.SignalStatus.OK
    assert s.section is bt.Section.VERDICT
    assert s.market_cap == D("24000000")
    assert s.market_cap_source == "Yahoo"
    assert s.signal.ticker == "ABC" and s.price_ticker == "ABC"
    # Kein Blick in die Zukunft: nur der Schlusskurs am Meldetag.
    assert prices.asked_close_for == [DAY]


def test_shares_filed_on_or_after_filing_day_are_not_known():
    # Bericht am Meldetag selbst eingereicht: gilt noch nicht als bekannt.
    info = company(shares=[shares(DAY, date(2014, 12, 31))])
    s = classify(filing(), info, FakePrices(closes={DAY: D("12")}))
    assert s.market_cap is None
    assert s.status is bt.SignalStatus.MARKET_CAP_UNKNOWN


def test_stress_section_does_not_need_market_cap():
    day = date(2011, 6, 30)
    s = classify(filing(day=day), company(), FakePrices())
    assert s.section is bt.Section.STRESS
    assert s.status is bt.SignalStatus.OK
    assert s.market_cap is None


@pytest.mark.parametrize(
    ("day", "section"),
    [(date(2005, 12, 30), None), (date(2006, 1, 3), bt.Section.STRESS),
     (date(2011, 6, 30), bt.Section.STRESS), (date(2011, 7, 1), bt.Section.VERDICT),
     (date(2026, 9, 30), bt.Section.VERDICT), (date(2026, 10, 1), None)],
)
def test_section_by_filing_day(day, section):
    assert bt.section_for(day) is section


def test_outside_period_is_no_backtest_signal():
    assert classify(filing(day=date(2026, 10, 1)), company(), FakePrices()) is None


def test_insider_rules_are_shared_with_live():
    # Fonds (SIC 6726) und Käufe unter 25.000 USD ergeben kein Signal.
    assert classify(filing(), company(sic="6726"), FakePrices()) is None
    assert classify(filing(shares="10"), company(), FakePrices()) is None


def test_no_price_keeps_case_and_market_cap_from_reported_price():
    info = company(
        shares=[shares(date(2015, 2, 1), date(2014, 12, 31), 3_000_000)],
        events=[Event(date(2015, 4, 1), "8-K 1.03")],
    )
    s = classify(filing(price="4", shares="10000"), info, FakePrices(check=PriceCheck(PriceStatus.MISSING, None)))
    assert s.status is bt.SignalStatus.NO_PRICE
    assert s.missing_case is MissingPrice.BANKRUPTCY
    # Ohne Yahoo-Kurs: gemeldeter Kaufpreis, damit die Börsenwert-Grenze
    # auch für die Fälle ohne Kurs gilt.
    assert s.market_cap == D("12000000")
    assert s.market_cap_source == "Meldung"
    # Einstiegspreis für die festen Werte im Portfolio (Schritt 6).
    assert s.reported_price == D("4")


def test_mismatch():
    s = classify(filing(), company(), FakePrices(check=PriceCheck(PriceStatus.MISMATCH, None)))
    assert s.status is bt.SignalStatus.MISMATCH
    assert s.missing_case is MissingPrice.NO_EVENT


def test_prices_ending_in_holding_period_count_as_no_price():
    takeover = company(events=[Event(date(2015, 4, 15), "DEFM14A")])
    ends = FakePrices(last_day=date(2015, 4, 20))
    s = classify(filing(), takeover, ends)
    assert s.status is bt.SignalStatus.NO_PRICE
    assert s.missing_case is MissingPrice.TAKEOVER
    # Ohne Meldung in der Haltedauer: sicher dort verschwunden, Grund unbekannt.
    s = classify(filing(), company(), ends)
    assert s.missing_case is MissingPrice.UNKNOWN


def test_build_signals_skips_unknown_companies_and_counts_them():
    filings = [filing(cik="1", n=1), filing(cik="2", n=2)]
    result = bt.build_signals(filings, {"1": company("1")}.get, FakePrices(), HOLD, NOW)
    assert [s.signal.id for s in result.signals] == ["insider:0000000000-15-000001"]
    assert result.no_company == 1
