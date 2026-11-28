"""Tests für die Messung des Insider-Backtests (Plan-Schritt 6).

Nur feste, ausgedachte Kurse. Echte Renditen werden hier nie berechnet:
Das Regelwerk ist noch nicht eingefroren.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

import pytest

from finance_ai.core.models import Side, Signal
from finance_ai.data.sec_company import MissingPrice
from finance_ai.data.sec_edgar import EASTERN
from finance_ai.decision.agent import DecisionRules
from finance_ai.evaluation import measure as m
from finance_ai.evaluation.backtest import BacktestSignal, Section, SignalStatus
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.engine import simulate
from finance_ai.paper_trading.prices import StaticPriceSource

COSTS = CostModel()  # 1 USD Gebühr, 0,5 % Slippage, 26,375 % Steuer
RULES = DecisionRules(start_cash=D("10000"), max_positions=10, holding_period=timedelta(days=91))
HOLD = RULES.holding_period


def at_open(day):
    return datetime.combine(day, time(9, 30), tzinfo=EASTERN)


def at_close(day):
    return datetime.combine(day, time(16, 0), tzinfo=EASTERN)


def weekdays(first, last):
    day = first
    while day <= last:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def series(first, last, price):
    """Eröffnung und Schluss je Werktag; `price` ist eine Zahl oder eine Funktion des Tages."""
    quotes = []
    for day in weekdays(first, last):
        value = price(day) if callable(price) else price
        quotes += [(at_open(day), D(value)), (at_close(day), D(value))]
    return quotes


def bsignal(
    ticker="ABC", day=date(2015, 3, 6), status=SignalStatus.OK, section=Section.VERDICT,
    cap=D("500000000"), case=None, confidence=0.6, price_ticker=None, reported=D("10"),
):
    observed = datetime.combine(day, time(17, 30), tzinfo=EASTERN)
    signal = Signal(
        expert="insider", ticker=ticker, side=Side.BUY, source_url="https://www.sec.gov/x",
        summary="Kauf", observed_at=observed, created_at=datetime(2026, 11, 28, tzinfo=EASTERN),
        confidence=confidence,
    )
    ok = status is SignalStatus.OK
    return BacktestSignal(
        signal=signal, filing_date=day, issuer_cik="1", section=section, status=status,
        price_ticker=(price_ticker or ticker) if ok else None, via_current_ticker=False,
        market_cap=cap, market_cap_source="Yahoo" if ok else "Meldung",
        missing_case=case, reported_price=reported,
    )


# --- Stufen -------------------------------------------------------------------


def test_tiers_follow_the_plan_table():
    assert all(m.fixed_return(m.Tier.OPTIMISTIC, c) is None for c in MissingPrice)
    assert all(m.fixed_return(m.Tier.WORST, c) == D("-1") for c in MissingPrice)
    realistic = {c: m.fixed_return(m.Tier.REALISTIC, c) for c in MissingPrice}
    assert realistic == {
        MissingPrice.TAKEOVER: D("0"),
        MissingPrice.BANKRUPTCY: D("-0.55"),
        MissingPrice.UNKNOWN: D("-0.55"),
        MissingPrice.AFTER_HOLDING: None,
        MissingPrice.NO_EVENT: D("-0.55"),
    }


# --- Rechnung von Hand --------------------------------------------------------


def test_round_trip_matches_hand_calculation():
    # 1000 USD, Kurs 10 → 12. Kauf zu 10,05, 999 USD brutto + 1 USD Gebühr:
    # 99,40299 Stück. Verkauf zu 11,94: 1186,8716 − 1 = 1185,8716.
    # Gewinn 185,8716, nach 26,375 % Steuer 136,848 → 13,6848 %.
    r = m.round_trip_return(D("10"), D("12"), COSTS, D("1000"))
    assert r == pytest.approx(D("0.136848"), abs=D("0.000001"))


def test_loss_counts_with_tax_credit_like_in_the_loss_pot():
    # Verlust senkt später die Steuer (Verlusttopf): Steuer wirkt beidseitig.
    r = m.round_trip_return(D("10"), D("8"), CostModel(D("0"), D("0"), D("0"), D("0.25")), D("1000"))
    assert r == pytest.approx(D("-0.15"))


def test_total_loss_has_no_sale_fee():
    r = m.round_trip_return(D("10"), D("0"), CostModel(tax_rate=D("0")), D("1000"))
    assert r == D("-1")


def test_double_slippage_only_changes_slippage():
    doubled = m.double_slippage(COSTS)
    assert doubled.slippage_rate == D("0.010")
    assert (doubled.fee_fixed, doubled.tax_rate) == (COSTS.fee_fixed, COSTS.tax_rate)


# --- Einzelsignale ------------------------------------------------------------


def single_prices(stock=None, etf=None):
    first, last = date(2015, 3, 2), date(2015, 7, 31)
    return StaticPriceSource({
        "ABC": stock if stock is not None else series(first, last, lambda d: "10" if d < date(2015, 6, 8) else "12"),
        "IWM": etf if etf is not None else series(first, last, lambda d: "100" if d < date(2015, 6, 8) else "105"),
    })


def test_single_signal_enters_at_next_open_and_matches_hand_calculation():
    # Meldung Freitag 6.3.2015 → Einstieg Montag 9.3., 9:30.
    # Ausstieg: erster Kurs ab 9.3. + 91 Tage = Montag 8.6., 9:30.
    r = m.single_result(bsignal(), m.Tier.REALISTIC, single_prices(), "IWM", HOLD, COSTS, D("1000"))
    assert r.entry == at_open(date(2015, 3, 9))
    assert r.exit == at_open(date(2015, 6, 8))
    assert r.measured
    assert r.stock_return == pytest.approx(D("0.136848"), abs=D("0.000001"))
    assert r.etf_return == pytest.approx(D("0.027619"), abs=D("0.000001"))
    assert r.excess == pytest.approx(D("0.109229"), abs=D("0.000001"))


def test_single_signal_uses_the_ticker_with_prices():
    s = bsignal(ticker="OLD", price_ticker="ABC")
    r = m.single_result(s, m.Tier.REALISTIC, single_prices(), "IWM", HOLD, COSTS, D("1000"))
    assert r.stock_return > 0


@pytest.mark.parametrize("status", [SignalStatus.NO_PRICE, SignalStatus.MISMATCH])
def test_single_signal_without_price_gets_fixed_value_against_etf(status):
    s = bsignal(status=status, case=MissingPrice.BANKRUPTCY)
    prices = single_prices()
    realistic = m.single_result(s, m.Tier.REALISTIC, prices, "IWM", HOLD, COSTS, D("1000"))
    assert not realistic.measured
    assert realistic.stock_return == m.round_trip_return(D("10"), D("4.5"), COSTS, D("1000"))
    assert realistic.etf_return == pytest.approx(D("0.027619"), abs=D("0.000001"))
    assert m.single_result(s, m.Tier.OPTIMISTIC, prices, "IWM", HOLD, COSTS, D("1000")) is None


def test_after_holding_drops_out_in_the_deciding_tier():
    s = bsignal(status=SignalStatus.NO_PRICE, case=MissingPrice.AFTER_HOLDING)
    assert m.single_result(s, m.Tier.REALISTIC, single_prices(), "IWM", HOLD, COSTS, D("1000")) is None
    worst = m.single_result(s, m.Tier.WORST, single_prices(), "IWM", HOLD, COSTS, D("1000"))
    # −100 %, abzüglich der Steuergutschrift aus dem Verlusttopf.
    assert worst.stock_return == D("-1") * (1 - COSTS.tax_rate)


def test_eligible_applies_live_rules():
    assert m.eligible(bsignal(), RULES)
    assert not m.eligible(bsignal(confidence=0.4), RULES)
    assert not m.eligible(bsignal(cap=D("3000000000")), RULES)
    assert not m.eligible(bsignal(cap=None, status=SignalStatus.NO_PRICE), RULES)
    assert not m.eligible(bsignal(status=SignalStatus.MARKET_CAP_UNKNOWN, cap=None), RULES)
    # Stresstest ohne Börsenwert-Grenze.
    assert m.eligible(bsignal(section=Section.STRESS, cap=None), RULES)
    assert m.eligible(bsignal(section=Section.STRESS, cap=D("9000000000")), RULES)


# --- Bootstrap ------------------------------------------------------------------


def fake_result(day, excess):
    s = bsignal(day=day)
    t = at_open(day)
    return m.SignalResult(s, t, t, D(excess), D(0), True)


def test_bootstrap_draws_whole_calendar_months():
    # Zwei Monate mit je vielen gleichen Werten: Jede Ziehung besteht aus ganzen
    # Monaten. Der Mittelwert kann also nur 0, 0,5 oder 1 sein.
    results = [fake_result(date(2015, 3, 2), "1")] * 50 + [fake_result(date(2015, 4, 1), "0")] * 50
    means = m.bootstrap_means(results, draws=200, seed=1)
    assert set(round(x, 6) for x in means) <= {0.0, 0.5, 1.0}


def test_bootstrap_interval_is_reproducible_and_brackets_the_mean():
    results = [fake_result(date(2015, month, 2), str(month / 100)) for month in range(1, 13)]
    low, high = m.bootstrap_ci(results, draws=2000, seed=7)
    assert (low, high) == m.bootstrap_ci(results, draws=2000, seed=7)
    assert low < 0.065 < high


def test_bootstrap_without_variation_is_a_point():
    results = [fake_result(date(2015, month, 2), "0.02") for month in range(1, 7)]
    assert m.bootstrap_ci(results, draws=500) == pytest.approx((0.02, 0.02))


# --- Fenster --------------------------------------------------------------------


def test_window_starts_are_monthly_and_stay_inside_the_section():
    stress = m.window_starts(Section.STRESS)
    assert stress[0] == date(2006, 1, 1)
    assert stress[-1] == date(2010, 12, 1)  # endet 1.6.2011, vor dem 30.6.2011
    verdict = m.window_starts(Section.VERDICT)
    assert verdict[0] == date(2011, 7, 1)
    assert verdict[-1] == date(2026, 3, 1)  # endet 1.9.2026, vor dem 30.9.2026


def test_halves_only_take_windows_entirely_inside():
    first, second = m.halves(m.window_starts(Section.VERDICT))
    assert first[0] == date(2011, 7, 1) and first[-1] == date(2018, 7, 1)
    assert second[0] == date(2019, 1, 1)
    assert date(2018, 10, 1) not in first + second


def test_summary_mean_and_shares():
    s = m.summarize([D("0.10"), D("-0.02"), D("0.03"), D("0.05")])
    assert s.count == 4
    assert s.mean == pytest.approx(D("0.04"))
    assert s.share_ahead == pytest.approx(0.75)
    assert s.share_5pp == pytest.approx(0.5)


# --- Portfolio ------------------------------------------------------------------


START = date(2015, 3, 1)


def window_prices(extra=None):
    quotes = {
        "IWM": series(date(2015, 2, 2), date(2015, 9, 30), "100"),
        "ABC": series(date(2015, 2, 2), date(2015, 9, 30), lambda d: "10" if d < date(2015, 6, 8) else "12"),
    }
    quotes.update(extra or {})
    return StaticPriceSource(quotes)


def test_window_portfolio_matches_hand_calculation():
    # Ein Signal, ETF flach. Startkapital 10.000, Budget je Platz 980 USD.
    # Kurs 10: 98 Stück zu 10,05 = 984,90 + 1 Gebühr = 985,90.
    # Verkauf 8.6. zu 11,94: 1170,12 − 1 = 1169,12, Gewinn 183,22,
    # Steuer 48,324275 → Bargeld 10.000 − 985,90 + 1169,12 − 48,324275 = 10.134,895725.
    w = m.run_window([bsignal()], m.Tier.REALISTIC, START, Section.VERDICT,
                     window_prices(), "IWM", RULES, COSTS)
    assert w.start == START and w.end == date(2015, 9, 1)
    assert w.comparison.portfolio_return == pytest.approx(D("0.0134895725"))
    # ETF flach: nur Kosten. 9999 / 100,5 Stück, Verkauf zu 99,5, minus 1 USD.
    etf = ((D(9999) / D("100.5")) * D("99.5") - 1 - 10000) / 10000
    assert w.comparison.benchmark_return == pytest.approx(etf)
    assert w.excess == w.comparison.portfolio_return - w.comparison.benchmark_return


def test_window_orders_replay_identically_in_simulate():
    w = m.run_window([bsignal()], m.Tier.REALISTIC, START, Section.VERDICT,
                     window_prices(), "IWM", RULES, COSTS)
    assert [o.side for o in w.orders] == [Side.BUY, Side.SELL]
    replay = simulate(w.orders, window_prices(), RULES.start_cash, COSTS, delay=timedelta(0))
    account = replay["insider"].immediate
    assert account.cash == w.account.cash
    assert [f.executed_at for f in account.fills] == [f.executed_at for f in w.account.fills]


def test_verdict_window_uses_no_signals_before_july_2011():
    stress = bsignal(day=date(2011, 6, 29), section=Section.STRESS)
    verdict = bsignal(ticker="XYZ", day=date(2011, 7, 1))
    prices = StaticPriceSource({
        "IWM": series(date(2011, 6, 1), date(2012, 2, 1), "100"),
        "ABC": series(date(2011, 6, 1), date(2012, 2, 1), "10"),
        "XYZ": series(date(2011, 6, 1), date(2012, 2, 1), "10"),
    })
    w = m.run_window([stress, verdict], m.Tier.REALISTIC, date(2011, 7, 1), Section.VERDICT,
                     prices, "IWM", RULES, COSTS)
    assert {o.ticker for o in w.orders} == {"XYZ"}


def test_stress_window_has_no_market_cap_limit_verdict_has():
    big = D("9000000000")
    for section, bought in ((Section.STRESS, True), (Section.VERDICT, False)):
        s = bsignal(section=section, cap=big)
        w = m.run_window([s], m.Tier.REALISTIC, START, section, window_prices(), "IWM", RULES, COSTS)
        assert bool(w.orders) is bought


def test_window_without_price_buys_reported_price_and_loses_55_percent_at_exit():
    s = bsignal(ticker="GONE", status=SignalStatus.NO_PRICE, case=MissingPrice.BANKRUPTCY, reported=D("10"))
    w = m.run_window([s], m.Tier.REALISTIC, START, Section.VERDICT, window_prices(), "IWM", RULES, COSTS)
    buy, sell = w.account.fills
    assert buy.quote == D("10") and sell.quote == D("4.50")
    assert sell.executed_at >= buy.executed_at + HOLD
    # Eigener Schlüssel: kein Zusammenstoß mit einem wiederverwendeten Kürzel.
    assert buy.ticker != "GONE"
    # Optimistisch fällt das Signal weg.
    none = m.run_window([s], m.Tier.OPTIMISTIC, START, Section.VERDICT, window_prices(), "IWM", RULES, COSTS)
    assert none.orders == []


def test_window_without_price_keeps_entry_value_until_holding_ends():
    s = bsignal(ticker="GONE", status=SignalStatus.NO_PRICE, case=MissingPrice.BANKRUPTCY)
    prices = m.TierPrices(window_prices(), [s], m.Tier.REALISTIC, HOLD)
    key = m.fixed_key(s)
    assert prices.last_at_or_before(key, at_open(date(2015, 4, 1)))[1] == D("10")
    assert prices.last_at_or_before(key, at_open(date(2015, 6, 8)))[1] == D("4.50")


def test_single_signal_refuses_holding_beyond_available_prices():
    # Kurse enden vor dem Ausstieg (z. B. Meldung im September 2026, Lauf im
    # November 2026): kein Ergebnis raten, sondern abbrechen.
    short = series(date(2015, 3, 2), date(2015, 5, 29), "10")
    prices = StaticPriceSource({"ABC": short, "IWM": short})
    with pytest.raises(ValueError, match="Haltedauer"):
        m.single_result(bsignal(), m.Tier.REALISTIC, prices, "IWM", HOLD, COSTS, D("1000"))
