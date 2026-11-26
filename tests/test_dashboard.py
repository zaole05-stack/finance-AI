from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from finance_ai.core import storage
from finance_ai.core.models import MAIN_PORTFOLIO, Order, Side, Signal
from finance_ai.core.settings import Settings, load_settings, save_settings
from finance_ai.dashboard import data
from finance_ai.decision.agent import DecisionRules
from finance_ai.decision.run import run_decisions
from finance_ai.evaluation.report import evaluate
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.prices import StaticPriceSource

T0 = datetime(2026, 11, 24, 15, tzinfo=UTC)
HOUR = timedelta(hours=1)
RULES = DecisionRules(start_cash=D("10000"), max_positions=1, max_market_cap=None)


def sig(ticker, expert="insider"):
    return Signal(
        expert=expert,
        ticker=ticker,
        side=Side.BUY,
        source_url=f"https://www.sec.gov/{ticker}",
        summary=f"{ticker} Kauf",
        observed_at=T0 - 5 * HOUR,
        created_at=T0 - HOUR,
        confidence=0.5,
        id=f"{expert}:{ticker}",
    )


def series(start_price, end_price):
    return [(T0 - HOUR, D(start_price)), (T0 + HOUR, D(start_price)), (T0 + 48 * HOUR, D(end_price))]


PRICES = StaticPriceSource({"AAA": series("10", "5"), "BBB": series("20", "21"), "IWM": series("100", "102")})


def filled_db():
    conn = storage.connect()
    storage.save_new_signals(conn, [sig("AAA"), sig("BBB", expert="politik")])
    run_decisions(conn, T0, PRICES, ["insider", "politik"], RULES)
    return conn


def test_settings_roundtrip_and_defaults():
    conn = storage.connect()
    assert load_settings(conn) == Settings()
    custom = Settings(
        benchmark_ticker=" iwc ",
        test_start=T0,
        rules=DecisionRules(start_cash=D("5000"), max_positions=4, holding_period=timedelta(days=30),
                            max_signal_age=timedelta(days=2), min_confidence=0.6, max_market_cap=None),
        costs=CostModel(fee_fixed=D("2"), slippage_rate=D("0.01")),
    )
    assert custom.benchmark_ticker == "IWC"
    save_settings(conn, custom)
    save_settings(conn, custom)  # Überschreiben statt doppelt
    assert load_settings(conn) == custom


def test_settings_reject_naive_start():
    with pytest.raises(ValueError):
        Settings(test_start=datetime(2026, 11, 24))


def test_overview_numbers_equal_evaluation():
    """Prüfkriterium M4: Alle Zahlen im Dashboard stimmen mit der Auswertung überein."""
    conn = filled_db()
    settings = Settings(rules=RULES)
    at = T0 + 48 * HOUR
    view = data.overview(conn, settings, PRICES, at)
    expected = evaluate(storage.list_orders(conn), PRICES, "IWM", T0, at, D("10000"), CostModel())
    assert view.test_start == T0
    assert view.reports == expected
    assert [r.portfolio for r in view.reports] == [MAIN_PORTFOLIO, "shadow:insider", "shadow:politik"]


def test_warning_when_stop_rule_applies():
    conn = filled_db()
    view = data.overview(conn, Settings(rules=RULES), PRICES, T0 + 48 * HOUR)
    errors = {w.portfolio for w in view.warnings if w.level == "error"}
    # AAA halbiert sich: Haupt-Portfolio und Insider-Schatten verlieren über 20 %.
    assert errors == {MAIN_PORTFOLIO, "shadow:insider"}
    assert not any(w.portfolio == "shadow:politik" and w.level == "error" for w in view.warnings)


def test_orders_without_price_yet_are_pending_not_rejected():
    """Direkt nach der Entscheidung gibt es noch keinen Kurs. Das ist kein Fehler."""
    conn = filled_db()
    view = data.overview(conn, Settings(rules=RULES), PRICES, T0 + HOUR / 2)
    assert view.error is None
    main = view.reports[0]
    assert (main.pending_immediate, main.pending_delayed) == (1, 1)
    assert (main.rejected_immediate, main.rejected_delayed) == (0, 0)
    assert main.return_delayed == 0
    assert any("noch offen" in w.text for w in view.warnings)
    # Mit dem ersten Kurs nach der Entscheidung (T0 + 1h) sind beide ausgeführt.
    main = data.overview(conn, Settings(rules=RULES), PRICES, T0 + HOUR).reports[0]
    assert (main.pending_immediate, main.pending_delayed) == (0, 0)


def test_benchmark_without_price_counts_as_cash():
    conn = filled_db()
    view = data.overview(conn, Settings(benchmark_ticker="XXX", rules=RULES), PRICES, T0 + 48 * HOUR)
    assert view.error is None
    assert all(r.benchmark_pending and r.benchmark_return == 0 for r in view.reports)
    assert any("ETF" in w.text for w in view.warnings)


def test_overview_empty_database():
    view = data.overview(storage.connect(), Settings(), PRICES, T0)
    assert (view.test_start, view.reports, view.error) == (None, [], None)


def test_runs_show_orders_and_rejections():
    conn = filled_db()
    (run,) = data.runs(conn, MAIN_PORTFOLIO)
    assert run.decided_at == T0
    assert [o.ticker for o in run.orders] == ["AAA"]
    assert [r["ticker"] for r in run.rejected["kein freier Platz"]] == ["BBB"]
    assert data.portfolios(conn) == [MAIN_PORTFOLIO, "shadow:insider", "shadow:politik"]


def test_refresh_prices_downloads_tracked_tickers():
    conn = filled_db()
    calls = []

    class Source:
        def download(self, ticker, start, end):
            calls.append((ticker, start, end))
            if ticker == "BBB":
                raise data.NoPriceError(ticker)
            return 1

    missing = data.refresh_prices(conn, Settings(rules=RULES), Source(), T0 + 48 * HOUR)
    assert missing == ["BBB"]
    assert [c[0] for c in calls] == ["AAA", "BBB", "IWM"]
    assert calls[0][1] == T0 - timedelta(days=1)
