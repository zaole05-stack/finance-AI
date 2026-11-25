import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pandas as pd
import pytest

from finance_ai.core import storage
from finance_ai.core.models import MAIN_PORTFOLIO, Order, Side
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.engine import simulate
from finance_ai.paper_trading.market_data import (
    HOUR,
    Bar,
    CachedPriceSource,
    bars_from_frame,
    fetch_yahoo_hourly,
)
from finance_ai.paper_trading.prices import NoPriceError


def t(hour: int, minute: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


# Drei Stundenbalken: 14:30–15:30, 15:30–16:30, 16:30–17:30 (UTC)
BARS = [
    Bar("IWM", t(14, 30), t(15, 30), D("100"), D("101")),
    Bar("IWM", t(15, 30), t(16, 30), D("102"), D("103")),
    Bar("IWM", t(16, 30), t(17, 30), D("104"), D("105")),
]


def fake_fetcher(bars):
    calls = []

    def fetch(ticker, start, end):
        calls.append((ticker, start, end))
        return [b for b in bars if b.ticker == ticker.upper()]

    fetch.calls = calls
    return fetch


@pytest.fixture
def source():
    conn = storage.connect()
    src = CachedPriceSource(conn, fake_fetcher(BARS), clock=lambda: t(18))
    src.download("iwm", t(0), t(23))
    yield src
    conn.close()


def test_download_skips_unfinished_bars():
    conn = storage.connect()
    src = CachedPriceSource(conn, fake_fetcher(BARS), clock=lambda: t(17))
    # Der dritte Balken endet erst 17:30 und ist um 17:00 noch offen.
    assert src.download("IWM", t(0), t(23)) == 2
    with pytest.raises(NoPriceError):
        src.first_at_or_after("IWM", t(16, 0))


def test_download_without_data_raises():
    src = CachedPriceSource(storage.connect(), fake_fetcher([]), clock=lambda: t(18))
    with pytest.raises(NoPriceError, match="730 Tage"):
        src.download("IWM", t(0), t(23))


def test_order_fills_at_next_bar_open(source):
    assert source.first_at_or_after("IWM", t(14, 30)) == (t(14, 30), D("100"))
    assert source.first_at_or_after("IWM", t(14, 45)) == (t(15, 30), D("102"))
    with pytest.raises(NoPriceError):
        source.first_at_or_after("IWM", t(16, 31))


def test_close_is_not_visible_before_bar_end(source):
    # 15:29: Der erste Balken läuft noch, bekannt ist nur sein Eröffnungskurs.
    assert source.last_at_or_before("IWM", t(15, 29)) == (t(14, 30), D("100"))
    # 15:30: Schluss Balken 1 und Eröffnung Balken 2 fallen zusammen → Eröffnung gilt.
    assert source.last_at_or_before("IWM", t(15, 30)) == (t(15, 30), D("102"))
    # Nach dem letzten Balken gilt sein Schlusskurs.
    assert source.last_at_or_before("IWM", t(20)) == (t(17, 30), D("105"))
    with pytest.raises(NoPriceError):
        source.last_at_or_before("IWM", t(14, 29))


def test_redownload_overwrites_adjusted_prices(source):
    adjusted = [Bar("IWM", t(14, 30), t(15, 30), D("99"), D("100"))]
    source._fetcher = fake_fetcher(adjusted)
    source.download("IWM", t(0), t(23))
    assert source.first_at_or_after("IWM", t(14, 30)) == (t(14, 30), D("99"))
    assert source.last_at_or_before("IWM", t(20)) == (t(17, 30), D("105"))


def test_unknown_ticker(source):
    with pytest.raises(NoPriceError):
        source.first_at_or_after("XYZ", t(14))


def test_bars_from_frame_converts_timezone_and_skips_gaps():
    index = pd.DatetimeIndex(
        ["2026-11-24 09:30", "2026-11-24 10:30", "2026-11-24 11:30"], tz="America/New_York"
    )
    frame = pd.DataFrame(
        {"Open": [265.029999, float("nan"), 262.899994], "Close": [265.420013, 1.0, 262.51001]},
        index=index,
    )
    bars = bars_from_frame("iwm", frame, HOUR)
    assert [b.start for b in bars] == [t(14, 30), t(16, 30)]
    assert bars[0].end == t(15, 30)
    assert bars[0].open == D("265.029999")
    assert bars[0].ticker == "IWM"


def test_bar_validation():
    with pytest.raises(ValueError):
        Bar("X", t(15), t(14), D("1"), D("1"))
    with pytest.raises(ValueError):
        Bar("X", datetime(2026, 1, 1), datetime(2026, 1, 1, 1), D("1"), D("1"))
    with pytest.raises(ValueError):
        Bar("X", t(14), t(15), D("0"), D("1"))


def test_simulate_on_cached_prices(source):
    order = Order(MAIN_PORTFOLIO, "IWM", Side.BUY, D("1"), t(14, 30), ("s1",), "Test")
    costs = CostModel(fee_fixed=D("0"), slippage_rate=D("0"), tax_rate=D("0"))
    accounts = simulate([order], source, D("1000"), costs)[MAIN_PORTFOLIO]
    assert accounts.immediate.fills[0].quote == D("100")
    assert accounts.delayed.fills[0].quote == D("102")
    assert accounts.immediate.market_value(t(20), source) == D("1005")


def test_prices_survive_reopening(tmp_path):
    path = tmp_path / "kurse.sqlite"
    conn = storage.connect(path)
    CachedPriceSource(conn, fake_fetcher(BARS), clock=lambda: t(18)).download("IWM", t(0), t(23))
    conn.close()
    reopened = CachedPriceSource(storage.connect(path), fake_fetcher([]))
    assert reopened.first_at_or_after("IWM", t(14))[1] == D("100")


@pytest.mark.network
def test_live_yahoo_hourly():
    end = datetime.now(UTC)
    bars = fetch_yahoo_hourly("IWM", end - timedelta(days=10), end)
    assert bars, "Yahoo hat keine Stundenkurse geliefert"
    assert all(b.end - b.start == HOUR for b in bars)
    assert all(b.start.utcoffset() is not None for b in bars)
