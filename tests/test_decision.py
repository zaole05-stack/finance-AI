from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from finance_ai.core import storage
from finance_ai.core.models import MAIN_PORTFOLIO, Order, Side, Signal, shadow_portfolio
from finance_ai.decision.agent import DecisionRules, decide, holdings_from_orders
from finance_ai.decision.run import run_decisions
from finance_ai.evaluation.report import Verdict, evaluate, verdict
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.prices import StaticPriceSource

DAY = timedelta(days=1)
T0 = datetime(2026, 11, 24, 15, tzinfo=UTC)
RULES = DecisionRules(start_cash=D("10000"), max_positions=2, max_market_cap=None)


def sig(ticker, expert="insider", conf=0.5, observed=T0 - timedelta(hours=5), n=0, side=Side.BUY):
    return Signal(
        expert=expert,
        ticker=ticker,
        side=side,
        source_url=f"https://www.sec.gov/{ticker}/{expert}/{n}",
        summary=f"{ticker} Kauf {n}",
        observed_at=observed,
        created_at=T0 - timedelta(hours=1),
        confidence=conf,
        id=f"{expert}:{ticker}:{n}",
    )


def prices(**tickers):
    series = {}
    for ticker, price in tickers.items():
        series[ticker] = [(T0 - DAY + timedelta(hours=h), D(price)) for h in range(0, 24 * 200, 1)]
    return StaticPriceSource(series)


PRICES = prices(AAA="10", BBB="20", CCC="30", DDD="6000")


def test_ranking_and_position_size():
    signals = [sig("AAA"), sig("BBB", conf=0.6), sig("CCC"), sig("CCC", expert="politik")]
    d = decide(MAIN_PORTFOLIO, signals, {}, T0, PRICES, RULES)
    # BBB hat die höchste Konfidenz, CCC zwei Signale, AAA fällt aus Platzmangel weg.
    assert [o.ticker for o in d.orders] == ["BBB", "CCC"]
    assert d.orders[0].quantity == D("245")  # 10000 / 2 * 0.98 / 20
    assert d.orders[1].signal_ids == ("insider:CCC:0", "politik:CCC:0")
    reasons = {sid: reason for sid, _, reason in d.outcomes}
    assert reasons["insider:AAA:0"] == "kein freier Platz (Rang 3)"
    assert reasons["politik:CCC:0"] == "gekauft (Rang 2)"


def test_every_order_is_traceable_to_its_signals():
    """Prüfkriterium M3: Jede Order lässt sich auf ihre Signale zurückführen."""
    signals = [sig("BBB", conf=0.6), sig("CCC"), sig("CCC", expert="politik")]
    d = decide(MAIN_PORTFOLIO, signals, {}, T0, PRICES, RULES)
    for order in d.orders:
        assert order.signal_ids
        for signal_id in order.signal_ids:
            assert signal_id in d.signals
            assert d.signals[signal_id].source_url in order.rationale
            assert any(sid == signal_id and oid == order.id for sid, oid, _ in d.outcomes)
    assert {sid for sid, oid, _ in d.outcomes if oid} == {s.id for s in signals}


@pytest.mark.parametrize(
    ("signal", "holdings", "expected"),
    [
        (sig("AAA", observed=T0 - 4 * DAY), {}, "Signal älter als 3 Tage"),
        (sig("AAA", conf=0.4), {}, "Konfidenz unter 0.5"),
        (sig("XXX"), {}, "kein aktueller Kurs"),
        (sig("DDD"), {}, "Kurs 6000 USD zu hoch für das Budget je Position"),
        (sig("AAA", side=Side.SELL), {}, "Verkaufssignale werden noch nicht gehandelt"),
    ],
)
def test_rejection_reasons(signal, holdings, expected):
    d = decide(MAIN_PORTFOLIO, [signal], holdings, T0, PRICES, RULES)
    assert d.orders == []
    assert d.outcomes == [(signal.id, None, expected)]


def test_market_cap_filter():
    rules = DecisionRules(max_positions=5)
    caps = {"AAA": D("500000000"), "BBB": D("3000000000")}
    d = decide(MAIN_PORTFOLIO, [sig("AAA"), sig("BBB"), sig("CCC")], {}, T0, PRICES, rules, caps.get)
    assert [o.ticker for o in d.orders] == ["AAA"]
    reasons = {sid: reason for sid, _, reason in d.outcomes}
    assert reasons["insider:BBB:0"] == "Börsenwert 3000 Mio. USD über Grenze 2000 Mio. USD"
    assert reasons["insider:CCC:0"] == "Börsenwert unbekannt"


def test_holding_period_sells_and_frees_slot():
    buy = Order(MAIN_PORTFOLIO, "AAA", Side.BUY, D("10"), T0 - 91 * DAY, ("s1",), "alt")
    keep = Order(MAIN_PORTFOLIO, "BBB", Side.BUY, D("5"), T0 - 10 * DAY, ("s2",), "neu")
    holdings = holdings_from_orders([buy, keep])
    d = decide(MAIN_PORTFOLIO, [sig("BBB"), sig("CCC")], holdings, T0, PRICES, RULES)
    sell, new = d.orders
    assert (sell.side, sell.ticker, sell.quantity, sell.signal_ids) == (Side.SELL, "AAA", D("10"), ("s1",))
    assert (new.side, new.ticker) == (Side.BUY, "CCC")
    assert ("insider:BBB:0", None, "schon im Depot") in d.outcomes


def test_holdings_from_orders():
    orders = [
        Order(MAIN_PORTFOLIO, "AAA", Side.BUY, D("10"), T0, ("a",), "x"),
        Order(MAIN_PORTFOLIO, "AAA", Side.BUY, D("5"), T0 + DAY, ("b",), "x"),
        Order(MAIN_PORTFOLIO, "BBB", Side.BUY, D("1"), T0, ("c",), "x"),
        Order(MAIN_PORTFOLIO, "BBB", Side.SELL, D("1"), T0 + DAY, ("c",), "x"),
    ]
    holdings = holdings_from_orders(orders)
    assert list(holdings) == ["AAA"]
    assert holdings["AAA"].quantity == D("15")
    assert holdings["AAA"].opened_at == T0
    assert holdings["AAA"].signal_ids == ("a", "b")


def test_briefing_lists_orders_and_reasons():
    signals = [sig("AAA"), sig("BBB", conf=0.6), sig("CCC"), sig("XXX")]
    briefing = decide(MAIN_PORTFOLIO, signals, {}, T0, PRICES, RULES).briefing
    assert "### Kauf BBB" in briefing
    assert "https://www.sec.gov/BBB/insider/0" in briefing
    assert "- kein aktueller Kurs: XXX" in briefing
    assert "- kein freier Platz: CCC" in briefing


def test_run_decisions_main_and_shadow_once():
    conn = storage.connect()
    storage.save_new_signals(conn, [sig("AAA"), sig("BBB", expert="politik")])
    decisions = run_decisions(conn, T0, PRICES, ["insider", "politik"], RULES)
    assert [d.portfolio for d in decisions] == [MAIN_PORTFOLIO, "shadow:insider", "shadow:politik"]
    assert [o.ticker for o in storage.list_orders(conn, MAIN_PORTFOLIO)] == ["AAA", "BBB"]
    assert [o.ticker for o in storage.list_orders(conn, shadow_portfolio("insider"))] == ["AAA"]
    assert [o.ticker for o in storage.list_orders(conn, shadow_portfolio("politik"))] == ["BBB"]
    rows = storage.list_decisions(conn, MAIN_PORTFOLIO)
    assert [(r["ticker"], r["reason"]) for r in rows] == [("AAA", "gekauft (Rang 1)"), ("BBB", "gekauft (Rang 2)")]
    # Zweiter Lauf: Signale sind entschieden, nichts Neues.
    again = run_decisions(conn, T0 + timedelta(hours=1), PRICES, ["insider", "politik"], RULES)
    assert all(d.orders == [] and d.outcomes == [] for d in again)
    assert len(storage.list_orders(conn)) == 4


def test_save_decision_is_atomic():
    conn = storage.connect()
    storage.save_new_signals(conn, [sig("AAA")])
    d = decide(MAIN_PORTFOLIO, [sig("AAA")], {}, T0, PRICES, RULES)
    bad = d.outcomes + [("unbekannt", None, "x")]  # Fremdschlüssel verletzt
    with pytest.raises(Exception):
        storage.save_decision(conn, MAIN_PORTFOLIO, T0, d.orders, bad)
    assert storage.list_orders(conn) == []


def test_evaluate_reports_per_portfolio_against_etf():
    costs = CostModel(fee_fixed=D("0"), slippage_rate=D("0"), tax_rate=D("0"))
    src = StaticPriceSource(
        {
            "AAA": [(T0, D("10")), (T0 + timedelta(hours=1), D("11")), (T0 + 10 * DAY, D("20"))],
            "ETF": [(T0, D("100")), (T0 + 10 * DAY, D("110"))],
        }
    )
    orders = [
        Order(MAIN_PORTFOLIO, "AAA", Side.BUY, D("100"), T0, ("a",), "x"),
        Order("shadow:insider", "AAA", Side.BUY, D("100"), T0, ("a",), "x"),
    ]
    reports = evaluate(orders, src, "ETF", T0, T0 + 10 * DAY, D("10000"), costs)
    main = reports[0]
    assert main.portfolio == MAIN_PORTFOLIO
    # sofort: 100 Stück zu 10 → +1000; verzögert: zu 11 → +900
    assert main.return_immediate == D("0.1")
    assert main.return_delayed == D("0.09")
    assert main.benchmark_return == D("0.1")
    assert main.approval_cost == D("0.01")
    assert main.verdict is Verdict.BEHIND
    assert [r.portfolio for r in reports] == [MAIN_PORTFOLIO, "shadow:insider"]


@pytest.mark.parametrize(
    ("ret", "bench", "finished", "expected"),
    [
        (D("-0.21"), D("-0.30"), False, Verdict.STOP),
        (D("0.01"), D("0.02"), False, Verdict.BEHIND),
        (D("0.03"), D("0.02"), False, Verdict.RUNNING),
        (D("0.07"), D("0.02"), True, Verdict.GO_LIVE),
        (D("0.04"), D("0.02"), True, Verdict.EXTEND),
        (D("0.01"), D("0.02"), True, Verdict.STOP),
    ],
)
def test_verdict_rules(ret, bench, finished, expected):
    assert verdict(ret, bench, finished) is expected
