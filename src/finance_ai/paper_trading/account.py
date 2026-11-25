"""Papier-Depot mit Bargeld, Beständen, Kosten und Steuern.

Vereinfachungen (bewusst, für den Vergleich mit dem ETF unerheblich, solange
beide Seiten gleich behandelt werden):
- Eine einzige Währung, keine Wechselkurse.
- Steuer wird bei jedem Verkauf fällig, nicht jährlich abgerechnet.
- Verluste kommen in einen Verlusttopf und werden mit späteren Gewinnen
  verrechnet. Ein Sparerpauschbetrag wird nicht berücksichtigt.
- Bruchstücke sind erlaubt, Leerverkäufe und Kredit nicht.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from finance_ai.core.models import Order, Position, Side
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.prices import NoPriceError, PriceSource

ZERO = Decimal(0)


class OrderRejected(Exception):
    """Die Order kann in diesem Depot nicht ausgeführt werden."""


@dataclass(frozen=True, slots=True)
class Fill:
    """Ausgeführter Trade. `price` enthält bereits die Slippage."""

    order_id: str | None
    ticker: str
    side: Side
    quantity: Decimal
    quote: Decimal
    price: Decimal
    fee: Decimal
    tax: Decimal
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class Rejection:
    order_id: str
    reason: str
    at: datetime


class Account:
    def __init__(self, name: str, start_cash: Decimal, costs: CostModel):
        start_cash = Decimal(start_cash)
        if start_cash <= 0:
            raise ValueError("Startkapital muss größer als 0 sein")
        self.name = name
        self.start_cash = start_cash
        self.cash = start_cash
        self.costs = costs
        self.loss_carryforward = ZERO
        self.fills: list[Fill] = []
        self.rejections: list[Rejection] = []
        self._positions: dict[str, Position] = {}

    @property
    def positions(self) -> list[Position]:
        return [self._positions[t] for t in sorted(self._positions)]

    def position(self, ticker: str) -> Position | None:
        return self._positions.get(ticker.strip().upper())

    def buy(
        self, ticker: str, quantity: Decimal, quote: Decimal, at: datetime,
        order_id: str | None = None,
    ) -> Fill:
        ticker = ticker.strip().upper()
        quantity = _positive("quantity", quantity)
        price = self.costs.buy_price(quote)
        gross = quantity * price
        fee = self.costs.fee(gross)
        total = gross + fee
        if total > self.cash:
            raise OrderRejected(f"Nicht genug Bargeld: brauche {total}, habe {self.cash}")

        self.cash -= total
        old = self._positions.get(ticker)
        old_qty = old.quantity if old else ZERO
        old_cost = old.cost_basis if old else ZERO
        new_qty = old_qty + quantity
        # Die Kaufgebühr gehört zu den Anschaffungskosten und senkt später den Gewinn.
        self._positions[ticker] = Position(self.name, ticker, new_qty, (old_cost + total) / new_qty)
        return self._record(Fill(order_id, ticker, Side.BUY, quantity, quote, price, fee, ZERO, at))

    def sell(
        self, ticker: str, quantity: Decimal, quote: Decimal, at: datetime,
        order_id: str | None = None,
    ) -> Fill:
        ticker = ticker.strip().upper()
        quantity = _positive("quantity", quantity)
        held = self._positions.get(ticker)
        if held is None or quantity > held.quantity:
            have = held.quantity if held else ZERO
            raise OrderRejected(f"Verkauf von {quantity} {ticker}, Bestand nur {have}")

        price = self.costs.sell_price(quote)
        proceeds = quantity * price - self.costs.fee(quantity * price)
        gain = proceeds - quantity * held.avg_price
        tax, self.loss_carryforward = _tax(gain, self.loss_carryforward, self.costs.tax_rate)
        self.cash += proceeds - tax

        rest = held.quantity - quantity
        if rest == 0:
            del self._positions[ticker]
        else:
            self._positions[ticker] = Position(self.name, ticker, rest, held.avg_price)
        fee = quantity * price - proceeds
        return self._record(Fill(order_id, ticker, Side.SELL, quantity, quote, price, fee, tax, at))

    def execute(self, order: Order, at: datetime, prices: PriceSource) -> Fill | None:
        """Führt die Order zum ersten Kurs ab `at` aus. Abgelehnte Orders werden protokolliert."""
        try:
            quote_time, quote = prices.first_at_or_after(order.ticker, at)
            trade = self.buy if order.side is Side.BUY else self.sell
            return trade(order.ticker, order.quantity, quote, quote_time, order.id)
        except (OrderRejected, NoPriceError) as error:
            self.rejections.append(Rejection(order.id, str(error), at))
            return None

    def market_value(self, at: datetime, prices: PriceSource) -> Decimal:
        """Bargeld plus Bestände zum letzten Kurs, ohne Verkaufskosten."""
        return self.cash + sum(
            (p.quantity * prices.last_at_or_before(p.ticker, at)[1] for p in self.positions),
            ZERO,
        )

    def liquidation_value(self, at: datetime, prices: PriceSource) -> Decimal:
        """Was nach Verkauf aller Bestände zu `at` übrig bliebe: nach Gebühren, Slippage und Steuer."""
        value = self.cash
        carry = self.loss_carryforward
        for p in self.positions:
            gross = p.quantity * self.costs.sell_price(prices.last_at_or_before(p.ticker, at)[1])
            proceeds = gross - self.costs.fee(gross)
            tax, carry = _tax(proceeds - p.cost_basis, carry, self.costs.tax_rate)
            value += proceeds - tax
        return value

    def total_return(self, at: datetime, prices: PriceSource) -> Decimal:
        """Rendite nach allen Kosten, als Anteil (0.05 = 5 %)."""
        return (self.liquidation_value(at, prices) - self.start_cash) / self.start_cash

    def _record(self, fill: Fill) -> Fill:
        self.fills.append(fill)
        return fill


def _tax(gain: Decimal, carry: Decimal, rate: Decimal) -> tuple[Decimal, Decimal]:
    """Steuer auf einen realisierten Gewinn und neuer Stand des Verlusttopfs."""
    if gain <= 0:
        return ZERO, carry - gain
    taxable = gain - carry
    if taxable <= 0:
        return ZERO, -taxable
    return taxable * rate, ZERO


def _positive(name: str, value: Decimal) -> Decimal:
    value = Decimal(value)
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} muss größer als 0 sein")
    return value
