"""Tests für den Datencheck (Plan-Schritt 4b): nur Datenqualität, keine Renditen."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from finance_ai.data.form4 import Form4, Owner, Transaction
from finance_ai.data.sec_company import CompanyInfo, Event, MissingPrice
from finance_ai.data.sec_insider_datasets import DatasetFiling
from finance_ai.evaluation import data_check as dc
from finance_ai.paper_trading.daily_prices import PriceCheck, PriceStatus

HOLD = timedelta(days=91)
CEO = Owner("Muster Max", False, True, False, "CEO")


def filing(n, ticker, cik, day=date(2015, 3, 2), price="10", shares="5000"):
    tx = Transaction("P", True, D(shares), D(price), day)
    return DatasetFiling(
        f"0000000000-15-{n:06d}", day, cik,
        Form4(cik, f"Firma {n}", ticker, (CEO,), (tx,), False),
    )


def company(cik, sic="2834", events=()):
    return CompanyInfo(cik, sic, (), (), tuple(events))


class FakePrices:
    """Ergebnis der Kursprüfung und letzter Kurstag je Ticker."""

    def __init__(self, checks, last_day):
        self.checks, self.last_day = checks, last_day

    def check(self, ticker, info, day, price):
        return self.checks[ticker]

    def last_bar_day(self, ticker):
        return self.last_day.get(ticker)


def run(filings, companies, prices):
    return dc.check_filings(filings, companies.get, prices, HOLD)


def test_counts_each_case():
    filings = [
        filing(1, "OK", "1"),
        filing(2, "NEW", "2"),  # erst über das heutige Kürzel gefunden
        filing(3, "GONE", "3"),  # kein Kurs, Pleite in der Haltedauer
        filing(4, "LATER", "4"),  # kein Kurs, erst später verschwunden
        filing(5, "REUSED", "5"),  # Kürzel gehört heute einer anderen Firma
        filing(6, "ENDS", "6"),  # Kurse enden in der Haltedauer, Übernahme
        filing(7, "FUND", "7"),  # Fonds: kein Signal
        filing(8, "SMALL", "8", shares="10"),  # unter 25.000 USD: kein Signal
    ]
    companies = {
        "1": company("1"),
        "2": company("2"),
        "3": company("3", events=[Event(date(2015, 4, 1), "8-K 1.03")]),
        "4": company("4", events=[Event(date(2019, 1, 1), "25-NSE")]),
        "5": company("5"),
        "6": company("6", events=[Event(date(2015, 4, 15), "DEFM14A")]),
        "7": company("7", sic="6726"),
        "8": company("8"),
    }
    ok = PriceCheck(PriceStatus.OK, "X")
    prices = FakePrices(
        {
            "OK": ok,
            "NEW": PriceCheck(PriceStatus.OK, "NEW2", via_current_ticker=True),
            "GONE": PriceCheck(PriceStatus.MISSING, None),
            "LATER": PriceCheck(PriceStatus.MISSING, None),
            "REUSED": PriceCheck(PriceStatus.MISMATCH, None),
            "ENDS": PriceCheck(PriceStatus.OK, "ENDS"),
        },
        {"X": date(2026, 11, 25), "NEW2": date(2026, 11, 25), "ENDS": date(2015, 4, 20)},
    )
    report = run(filings, companies, prices)
    assert report.signals == 6
    assert report.with_price == 2
    assert report.via_current_ticker == 1
    assert report.mismatch == 1
    assert report.cases == {
        MissingPrice.BANKRUPTCY: 1,
        MissingPrice.AFTER_HOLDING: 1,
        MissingPrice.NO_EVENT: 1,  # REUSED: keine Meldung zur Firma
        MissingPrice.TAKEOVER: 1,
    }
    # Mit −55 % gehen Pleite, unbekannter Grund und keine Meldung ein.
    assert report.at_minus_55 == 2
    assert report.share_at_minus_55 == pytest.approx(2 / 6)


def test_company_without_sec_data_is_no_signal():
    # Ohne Firmendaten kein Branchencode, also wie live: kein Signal.
    report = run([filing(1, "OK", "1")], {}, FakePrices({}, {}))
    assert report.signals == 0 and report.no_company == 1


@pytest.mark.parametrize(
    ("share", "verdict"),
    [(0.10, dc.Verdict.CONTINUE), (0.1001, dc.Verdict.WARN), (0.20, dc.Verdict.WARN),
     (0.2001, dc.Verdict.STOP)],
)
def test_thresholds(share, verdict):
    assert dc.verdict(share) is verdict


def test_worse_year_decides():
    good = dc.YearReport(year=2015, signals=100, at_minus_55=5)
    bad = dc.YearReport(year=2008, signals=100, at_minus_55=25)
    assert dc.overall_verdict([good, bad]) is dc.Verdict.STOP


def test_markdown_summary_mentions_holding_period():
    report = dc.YearReport(year=2015, signals=52, with_price=40, at_minus_55=4)
    text = dc.markdown([report], HOLD)
    assert "2015" in text and "91 Tage" in text and "7.7 %" in text
