"""Tests für Tageskurse im Backtest.

Die Kurse hier sind erfunden und nur nach dem Muster von Yahoo aufgebaut
(geprüft am 26.11.2026 mit AAPL rund um den 4:1-Split vom 31.8.2020):
`Close` ist bereits um Splits bereinigt, `Adj Close` zusätzlich um Dividenden,
`Stock Splits` ist am Split-Tag der Faktor und sonst 0. Echte Yahoo-Daten
gehören nicht ins Repo.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pandas as pd
import pytest

from finance_ai.data.sec_company import CompanyInfo, Event
from finance_ai.data.sec_edgar import EASTERN
from finance_ai.paper_trading import daily_prices as dp
from finance_ai.paper_trading.prices import NoPriceError


def frame(rows):
    """rows: (Tag, Open, Close, Adj Close, Split)"""
    index = pd.DatetimeIndex(
        [pd.Timestamp(day).tz_localize("America/New_York") for day, *_ in rows], name="Date"
    )
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "Close": [r[2] for r in rows],
            "Adj Close": [r[3] for r in rows],
            "Stock Splits": [r[4] for r in rows],
            "Dividends": [0.0] * len(rows),
        },
        index=index,
    )


# Wie AAPL Ende August 2020: 4:1-Split am 31.8., alle Kurse schon split-bereinigt.
SPLIT = frame([
    ("2020-08-27", 127.0, 125.0, 122.5, 0.0),
    ("2020-08-28", 126.0, 124.8, 122.3, 0.0),
    ("2020-08-31", 127.5, 129.0, 126.4, 4.0),
    ("2020-09-01", 132.8, 134.2, 131.5, 0.0),
])


class FakeYahoo:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    def __call__(self, ticker):
        self.calls.append(ticker)
        return dp.bars_from_frame(self.frames.get(ticker, frame([])))


@pytest.fixture
def store(tmp_path):
    yahoo = FakeYahoo({"AAPL": SPLIT, "NEW": SPLIT})
    with dp.DailyPriceStore(tmp_path / "prices.sqlite", fetcher=yahoo) as prices:
        yield prices, yahoo


def test_store_keeps_data_after_reopen(tmp_path):
    yahoo = FakeYahoo({"AAPL": SPLIT})
    with dp.DailyPriceStore(tmp_path / "p.sqlite", fetcher=yahoo) as prices:
        prices.ensure("AAPL")
    with dp.DailyPriceStore(tmp_path / "p.sqlite", fetcher=yahoo) as prices:
        assert prices.ensure("AAPL") is True
        assert len(prices.bars("AAPL")) == 4
    assert yahoo.calls == ["AAPL"]


def test_bars_from_frame_skips_gaps():
    gaps = frame([("2020-08-27", float("nan"), 125.0, 122.5, 0.0), ("2020-08-28", 126.0, 124.8, 122.3, 0.0)])
    bars = dp.bars_from_frame(gaps)
    assert [b.day for b in bars] == [date(2020, 8, 28)]
    assert bars[0] == dp.DailyBar(date(2020, 8, 28), D("126"), D("124.8"), D("122.3"), D("0"))


def test_download_once_also_when_empty(store):
    prices, yahoo = store
    assert prices.ensure("AAPL") is True
    assert prices.ensure("AAPL") is True
    assert prices.ensure("LEHMQ") is False  # delistet, Yahoo liefert nichts
    assert prices.ensure("LEHMQ") is False
    assert yahoo.calls == ["AAPL", "LEHMQ"]  # jeder Ticker genau einmal


def test_source_quotes_open_and_close_in_new_york(store):
    prices, _ = store
    prices.ensure("AAPL")
    source = prices.source()
    # Eine Meldung nach Börsenschluss wird am nächsten Morgen zur Eröffnung gekauft.
    after_close = datetime(2020, 8, 27, 17, 30, tzinfo=EASTERN)
    when, price = source.first_at_or_after("AAPL", after_close)
    assert when == datetime(2020, 8, 28, 9, 30, tzinfo=EASTERN)
    # Eröffnung bereinigt wie der Schluss: 126 × 122,3 / 124,8
    assert price == (D("126") * D("122.3") / D("124.8")).quantize(dp.PRICE_STEP)
    when, price = source.last_at_or_before("AAPL", datetime(2020, 8, 28, 20, tzinfo=EASTERN))
    assert (when, price) == (datetime(2020, 8, 28, 16, 0, tzinfo=EASTERN), D("122.3"))


def test_source_without_data_raises(store):
    prices, _ = store
    with pytest.raises(NoPriceError):
        prices.source().first_at_or_after("LEHMQ", datetime(2020, 1, 1, tzinfo=EASTERN))


def test_raw_close_undoes_later_splits(store):
    prices, _ = store
    prices.ensure("AAPL")
    # Vor dem 4:1-Split war der echte Kurs viermal so hoch.
    assert prices.raw_close("AAPL", date(2020, 8, 28)) == D("124.8") * 4
    assert prices.raw_close("AAPL", date(2020, 8, 31)) == D("129.0")
    # Wochenende: letzter Handelstag davor
    assert prices.raw_close("AAPL", date(2020, 8, 30)) == D("124.8") * 4
    assert prices.raw_close("AAPL", date(2020, 8, 1)) is None


@pytest.mark.parametrize(("raw", "yahoo"), [("BRK.B", "BRK-B"), ("bf/b", "BF-B"), (" dbd ", "DBD")])
def test_yahoo_symbol(raw, yahoo):
    assert dp.yahoo_symbol(raw) == yahoo


def company(tickers=("NEW",), events=()):
    return CompanyInfo("0000000001", "3578", tickers, (), tuple(events))


def test_price_check_ok(store):
    prices, _ = store
    check = dp.check_price(prices, "AAPL", company(), date(2020, 8, 28), D("500"))
    assert (check.status, check.ticker, check.via_current_ticker) == (dp.PriceStatus.OK, "AAPL", False)


def test_price_check_uses_current_ticker(store):
    prices, _ = store
    check = dp.check_price(prices, "OLD", company(("NEW",)), date(2020, 8, 28), D("499"))
    assert (check.status, check.ticker, check.via_current_ticker) == (dp.PriceStatus.OK, "NEW", True)


def test_price_check_detects_reused_ticker(store):
    prices, _ = store
    # Gemeldet 30 USD, Yahoo kennt das Kürzel aber mit ~500 USD: andere Firma.
    check = dp.check_price(prices, "AAPL", company(()), date(2020, 8, 28), D("30"))
    assert check.status is dp.PriceStatus.MISMATCH


def test_price_check_tolerance_is_25_percent(store):
    prices, _ = store
    raw = D("124.8") * 4
    assert dp.check_price(prices, "AAPL", company(()), date(2020, 8, 28), raw * D("0.81")).status is dp.PriceStatus.OK
    assert dp.check_price(prices, "AAPL", company(()), date(2020, 8, 28), raw * D("0.79")).status is dp.PriceStatus.MISMATCH


def test_price_check_missing(store):
    prices, _ = store
    check = dp.check_price(prices, "LEHMQ", company(()), date(2008, 6, 2), D("30"))
    assert (check.status, check.ticker) == (dp.PriceStatus.MISSING, None)


def test_vanish_reason():
    day = date(2008, 6, 2)
    takeover = company(events=[Event(date(2009, 3, 1), "DEFM14A"), Event(date(2009, 5, 1), "25-NSE")])
    bankrupt = company(events=[Event(date(2008, 9, 15), "8-K 1.03"), Event(date(2008, 12, 1), "DEFM14A")])
    earlier = company(events=[Event(date(2007, 1, 1), "8-K 1.03")])
    assert takeover.vanish_reason(day) is dp_reason("TAKEOVER")
    # Insolvenz hat Vorrang: Wer nach der Pleite verkauft wird, ist trotzdem pleite.
    assert bankrupt.vanish_reason(day) is dp_reason("BANKRUPTCY")
    # Nur Ereignisse nach dem Signal zählen.
    assert earlier.vanish_reason(day) is dp_reason("UNKNOWN")
    assert company().vanish_reason(day) is dp_reason("UNKNOWN")


def dp_reason(name):
    from finance_ai.data.sec_company import VanishReason

    return VanishReason[name]


@pytest.mark.network
def test_live_yahoo_daily():
    # IWM (Russell-2000-ETF) gibt es seit 2000. Nicht DBD: Nach der Insolvenz
    # 2023 führt Yahoo unter DBD nur noch die neuen Aktien ab August 2023.
    bars = dp.fetch_yahoo_daily("IWM")
    assert bars and bars[0].day < date(2006, 1, 1)
    assert all(b.open > 0 and b.close > 0 for b in bars[-20:])
    assert max(b.day for b in bars) > date.today() - timedelta(days=10)
