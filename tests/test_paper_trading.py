from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from finance_ai.core.models import MAIN_PORTFOLIO, Order, Side
from finance_ai.paper_trading.account import Account, OrderRejected
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.engine import buy_and_hold, compare, simulate
from finance_ai.paper_trading.prices import NoPriceError, StaticPriceSource


def at(day: str, hour: int) -> datetime:
    return datetime.fromisoformat(f"2026-{day}T{hour:02d}:00:00+00:00")


COSTS = CostModel(fee_fixed=D("1"), slippage_rate=D("0.001"), tax_rate=D("0.26375"))
PRICES = StaticPriceSource(
    {
        "ABCD": [(at("01-05", 15), "50"), (at("01-05", 16), "52"),
                 (at("02-02", 15), "60"), (at("02-02", 16), "59")],
        "IWM": [(at("01-05", 15), "100"), (at("02-02", 16), "105")],
    }
)


def order(side: Side, quantity: str, created: datetime, ticker="ABCD", portfolio=MAIN_PORTFOLIO) -> Order:
    return Order(portfolio, ticker, side, D(quantity), created, ("s1",), "Test")


# --- Prüfung M1: fester Kursverlauf, Ergebnis von Hand gerechnet -------------
#
# Startkapital 10 000, Gebühr 1 pro Trade, Slippage 0,1 %, Steuer 26,375 %.
# Kauf 100 ABCD am 05.01. 15:00, Verkauf 100 ABCD am 02.02. 15:00.
#
# Sofort:     Kauf 50 × 1,001 = 50,05 → 5005 + 1 = 5006
#             Verkauf 60 × 0,999 = 59,94 → 5994 − 1 = 5993
#             Gewinn 987, Steuer 260,32125 → Endwert 10 726,67875 (+7,2667875 %)
# Verzögert:  Kauf zum Kurs 52 (16:00) → 52,052 → 5206,2
#             Verkauf zum Kurs 59 (16:00) → 58,941 → 5893,1
#             Gewinn 686,9, Steuer 181,169875 → Endwert 10 505,730125 (+5,05730125 %)
# ETF:        Kauf zu 100,1 für höchstens 9999 → 99,890109 Stück (abgerundet)
#             Verkauf zu 105 × 0,999 → Erlös 10 476,972983555
#             Steuer 125,80164791275625 → Endwert 10 351,17142474224375


def test_m1_hand_calculated_scenario():
    orders = [order(Side.BUY, "100", at("01-05", 15)), order(Side.SELL, "100", at("02-02", 15))]
    accounts = simulate(orders, PRICES, D("10000"), COSTS)[MAIN_PORTFOLIO]
    end = at("02-02", 16)

    assert accounts.immediate.cash == D("10726.67875")
    assert accounts.immediate.positions == []
    assert accounts.immediate.total_return(end, PRICES) == D("0.072667875")

    assert accounts.delayed.cash == D("10505.730125")
    assert accounts.delayed.total_return(end, PRICES) == D("0.0505730125")

    benchmark = buy_and_hold("IWM", at("01-05", 15), PRICES, D("10000"), COSTS)
    assert benchmark.position("IWM").quantity == D("99.890109")
    assert benchmark.liquidation_value(end, PRICES) == D("10351.17142474224375")

    result = compare(accounts.immediate, benchmark, end, PRICES)
    assert result.benchmark_return == D("0.035117142474224375")
    assert result.excess_return == D("0.072667875") - D("0.035117142474224375")


# --- Kurse --------------------------------------------------------------------


def test_prices_first_after_and_last_before():
    assert PRICES.first_at_or_after("abcd", at("01-05", 15)) == (at("01-05", 15), D("50"))
    assert PRICES.first_at_or_after("ABCD", at("01-05", 15) + timedelta(seconds=1))[1] == D("52")
    assert PRICES.last_at_or_before("ABCD", at("01-20", 0))[1] == D("52")
    with pytest.raises(NoPriceError):
        PRICES.first_at_or_after("ABCD", at("03-01", 0))
    with pytest.raises(NoPriceError):
        PRICES.last_at_or_before("ABCD", at("01-01", 0))
    with pytest.raises(NoPriceError):
        PRICES.first_at_or_after("UNBEKANNT", at("01-05", 15))


@pytest.mark.parametrize("bad", ["0", "-1", 1.5])
def test_prices_reject_invalid(bad):
    with pytest.raises((ValueError, TypeError)):
        StaticPriceSource({"X": [(at("01-05", 15), bad)]})


def test_prices_require_timezone():
    with pytest.raises(ValueError):
        StaticPriceSource({"X": [(datetime(2026, 1, 5), "1")]})


# --- Kosten -------------------------------------------------------------------


def test_cost_model_defaults_and_validation():
    default = CostModel()
    assert default.tax_rate == D("0.26375")
    assert default.buy_price(D("100")) == D("100.500")
    assert default.sell_price(D("100")) == D("99.500")
    assert CostModel(fee_fixed=D("1"), fee_rate=D("0.001")).fee(D("1000")) == D("2.000")
    with pytest.raises(ValueError):
        CostModel(fee_fixed=D("-1"))
    with pytest.raises(ValueError):
        CostModel(tax_rate=D("1"))
    with pytest.raises(TypeError):
        CostModel(slippage_rate=0.01)


# --- Depot --------------------------------------------------------------------

NO_SLIP = CostModel(fee_fixed=D("0"), slippage_rate=D("0"), tax_rate=D("0.25"))


def test_average_price_includes_buy_fee():
    account = Account("t", D("1000"), CostModel(fee_fixed=D("2"), slippage_rate=D("0")))
    account.buy("X", D("4"), D("10"), at("01-05", 15))
    account.buy("X", D("4"), D("20"), at("01-05", 16))
    # (40 + 2 + 80 + 2) / 8 = 15,5
    assert account.position("X").avg_price == D("15.5")
    assert account.cash == D("876")


def test_partial_sell_keeps_average_price():
    account = Account("t", D("1000"), NO_SLIP)
    account.buy("X", D("10"), D("10"), at("01-05", 15))
    account.sell("X", D("4"), D("15"), at("01-05", 16))
    assert account.position("X").quantity == D("6")
    assert account.position("X").avg_price == D("10")
    # Gewinn 20, Steuer 5 → 900 + 60 − 5
    assert account.cash == D("955")


def test_loss_carryforward_offsets_later_gain():
    account = Account("t", D("1000"), NO_SLIP)
    account.buy("A", D("10"), D("10"), at("01-05", 15))
    account.sell("A", D("10"), D("7"), at("01-05", 16))  # Verlust 30
    assert account.loss_carryforward == D("30")
    account.buy("B", D("10"), D("10"), at("01-06", 15))
    fill = account.sell("B", D("10"), D("15"), at("01-06", 16))  # Gewinn 50
    assert fill.tax == D("5.00")  # (50 − 30) × 25 %
    assert account.loss_carryforward == 0


def test_gain_smaller_than_carryforward_is_tax_free():
    account = Account("t", D("1000"), NO_SLIP)
    account.buy("A", D("10"), D("10"), at("01-05", 15))
    account.sell("A", D("10"), D("5"), at("01-05", 16))  # Verlust 50
    account.buy("B", D("10"), D("10"), at("01-06", 15))
    fill = account.sell("B", D("10"), D("12"), at("01-06", 16))  # Gewinn 20
    assert fill.tax == 0
    assert account.loss_carryforward == D("30")


def test_liquidation_value_uses_carryforward_without_changing_it():
    account = Account("t", D("1000"), NO_SLIP)
    account.buy("A", D("10"), D("10"), at("01-05", 15))
    account.sell("A", D("10"), D("8"), at("01-05", 16))  # Verlust 20
    account.buy("ABCD", D("10"), D("50"), at("01-05", 16))
    # Bewertung zu 59: Gewinn 90, steuerpflichtig 70 → Steuer 17,5
    value = account.liquidation_value(at("02-02", 16), PRICES)
    assert value == D("480") + D("590") - D("17.5")
    assert account.loss_carryforward == D("20")
    assert account.market_value(at("02-02", 16), PRICES) == D("1070")


def test_rejects_buy_without_cash_and_oversell():
    account = Account("t", D("100"), NO_SLIP)
    with pytest.raises(OrderRejected, match="Bargeld"):
        account.buy("X", D("11"), D("10"), at("01-05", 15))
    with pytest.raises(OrderRejected, match="Bestand"):
        account.sell("X", D("1"), D("10"), at("01-05", 15))
    assert account.cash == D("100")
    assert account.fills == []


def test_execute_records_rejections_instead_of_raising():
    account = Account("t", D("100"), NO_SLIP)
    assert account.execute(order(Side.BUY, "100", at("01-05", 15)), at("01-05", 15), PRICES) is None
    assert account.execute(order(Side.BUY, "1", at("03-01", 0)), at("03-01", 0), PRICES) is None
    assert [r.reason.split()[0] for r in account.rejections] == ["Nicht", "Kein"]


# --- Doppelte Ausführung --------------------------------------------------------


def test_delay_uses_first_quote_after_delay():
    orders = [order(Side.BUY, "1", at("01-05", 15))]
    accounts = simulate(orders, PRICES, D("1000"), NO_SLIP)[MAIN_PORTFOLIO]
    assert accounts.immediate.fills[0].quote == D("50")
    assert accounts.delayed.fills[0].quote == D("52")
    assert accounts.delayed.fills[0].executed_at == at("01-05", 16)


def test_order_without_later_quote_is_rejected_only_when_delayed():
    orders = [order(Side.BUY, "1", at("02-02", 16))]
    accounts = simulate(orders, PRICES, D("1000"), NO_SLIP)[MAIN_PORTFOLIO]
    assert len(accounts.immediate.fills) == 1
    assert accounts.delayed.fills == []
    assert len(accounts.delayed.rejections) == 1


def test_portfolios_are_simulated_separately():
    orders = [
        order(Side.BUY, "1", at("01-05", 15)),
        order(Side.BUY, "2", at("01-05", 15), portfolio="shadow:insider"),
    ]
    result = simulate(orders, PRICES, D("1000"), NO_SLIP)
    assert set(result) == {MAIN_PORTFOLIO, "shadow:insider"}
    assert result["shadow:insider"].immediate.position("ABCD").quantity == D("2")
    assert result[MAIN_PORTFOLIO].immediate.position("ABCD").quantity == D("1")


def test_orders_execute_in_time_order_not_input_order():
    orders = [order(Side.SELL, "1", at("02-02", 15)), order(Side.BUY, "1", at("01-05", 15))]
    accounts = simulate(orders, PRICES, D("1000"), NO_SLIP)[MAIN_PORTFOLIO]
    assert [f.side for f in accounts.immediate.fills] == [Side.BUY, Side.SELL]
    assert accounts.immediate.rejections == []


def test_negative_delay_rejected():
    with pytest.raises(ValueError):
        simulate([], PRICES, D("1000"), NO_SLIP, delay=timedelta(hours=-1))


def test_compare_requires_same_start_cash():
    a = Account("a", D("1000"), NO_SLIP)
    b = Account("b", D("2000"), NO_SLIP)
    with pytest.raises(ValueError):
        compare(a, b, at("02-02", 16), PRICES)


def test_simulate_until_leaves_orders_pending_and_ignores_later_prices():
    orders = [order(Side.BUY, "10", at("01-05", 15)), order(Side.SELL, "10", at("02-02", 15))]
    # Am 05.01. um 15:30: sofortiger Kauf hat einen Kurs, der verzögerte (16:00) noch nicht.
    early = simulate(orders, PRICES, D("1000"), NO_SLIP, until=at("01-05", 15) + timedelta(minutes=30))
    accounts = early[MAIN_PORTFOLIO]
    assert [p.ticker for p in accounts.immediate.positions] == ["ABCD"]
    assert accounts.delayed.positions == []
    assert accounts.pending_immediate == (orders[1].id,)
    assert accounts.pending_delayed == (orders[0].id, orders[1].id)
    assert accounts.delayed.rejections == []
    # Ohne Stichtag wird wie bisher alles ausgeführt.
    assert simulate(orders, PRICES, D("1000"), NO_SLIP)[MAIN_PORTFOLIO].pending_delayed == ()
