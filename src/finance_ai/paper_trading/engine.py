"""Doppelte Ausführung (sofort und mit Freigabe-Verzögerung) und ETF-Vergleich.

Jede Order läuft in zwei getrennten Depots: einmal zum ersten Kurs nach ihrer
Erzeugung, einmal zum ersten Kurs nach `created_at + delay`. Der Unterschied
zeigt, ob ein Signal die manuelle Freigabe in Phase 1 übersteht.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from finance_ai.core.models import Order
from finance_ai.paper_trading.account import Account
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.prices import NoPriceError, PriceSource

DEFAULT_APPROVAL_DELAY = timedelta(hours=1)
QUANTITY_STEP = Decimal("0.000001")


class ExecutionMode(StrEnum):
    IMMEDIATE = "sofort"
    DELAYED = "verzoegert"


@dataclass(frozen=True, slots=True)
class DualAccounts:
    immediate: Account
    delayed: Account
    # Orders, die bis zum Stichtag noch keinen Kurs hatten (noch nicht ausgeführt).
    pending_immediate: tuple[str, ...] = ()
    pending_delayed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Comparison:
    portfolio_return: Decimal
    benchmark_return: Decimal

    @property
    def excess_return(self) -> Decimal:
        """Vorsprung gegenüber dem ETF in Prozentpunkten (als Anteil)."""
        return self.portfolio_return - self.benchmark_return


def simulate(
    orders: Iterable[Order],
    prices: PriceSource,
    start_cash: Decimal,
    costs: CostModel,
    delay: timedelta = DEFAULT_APPROVAL_DELAY,
    until: datetime | None = None,
) -> dict[str, DualAccounts]:
    """Spielt alle Orders durch, getrennt nach Portfolio und Ausführungsart.

    Mit `until` werden nur Orders ausgeführt, deren erster Kurs spätestens zu
    diesem Zeitpunkt vorliegt. Die übrigen gelten als offen, nicht als
    abgelehnt. So nutzt eine Auswertung zum Zeitpunkt `until` keine späteren Kurse.
    """
    if delay < timedelta(0):
        raise ValueError("delay darf nicht negativ sein")
    by_portfolio: dict[str, list[Order]] = defaultdict(list)
    for order in orders:
        by_portfolio[order.portfolio].append(order)

    result = {}
    for portfolio, portfolio_orders in by_portfolio.items():
        accounts = {}
        pending: dict[ExecutionMode, tuple[str, ...]] = {}
        for mode, shift in (
            (ExecutionMode.IMMEDIATE, timedelta(0)),
            (ExecutionMode.DELAYED, delay),
        ):
            account = Account(f"{portfolio}/{mode}", start_cash, costs)
            # Verzögerte Orders können sich gegenseitig überholen, deshalb
            # nach Ausführungszeit sortieren, nicht nach Erzeugungszeit.
            schedule = sorted(portfolio_orders, key=lambda o: (o.created_at + shift, o.created_at, o.id))
            waiting = []
            for order in schedule:
                if until is not None and not has_quote(prices, order.ticker, order.created_at + shift, until):
                    waiting.append(order.id)
                    continue
                account.execute(order, order.created_at + shift, prices)
            accounts[mode] = account
            pending[mode] = tuple(waiting)
        result[portfolio] = DualAccounts(
            accounts[ExecutionMode.IMMEDIATE],
            accounts[ExecutionMode.DELAYED],
            pending[ExecutionMode.IMMEDIATE],
            pending[ExecutionMode.DELAYED],
        )
    return result


def has_quote(prices: PriceSource, ticker: str, start: datetime, until: datetime) -> bool:
    if start > until:
        return False
    try:
        quote_time, _ = prices.first_at_or_after(ticker, start)
    except NoPriceError:
        return False
    return quote_time <= until


def buy_and_hold(
    ticker: str,
    start: datetime,
    prices: PriceSource,
    start_cash: Decimal,
    costs: CostModel,
) -> Account:
    """Vergleichsdepot: Das ganze Startkapital geht zum Start in den ETF."""
    account = Account(f"benchmark:{ticker.strip().upper()}", start_cash, costs)
    quote_time, quote = prices.first_at_or_after(ticker, start)
    # Bruttobetrag so wählen, dass Betrag + Gebühr das Bargeld nicht übersteigt.
    budget = (account.cash - costs.fee_fixed) / (1 + costs.fee_rate)
    quantity = (budget / costs.buy_price(quote)).quantize(QUANTITY_STEP, rounding=ROUND_DOWN)
    account.buy(ticker, quantity, quote, quote_time)
    return account


def compare(account: Account, benchmark: Account, at: datetime, prices: PriceSource) -> Comparison:
    """Beide Depots zum selben Zeitpunkt nach allen Kosten bewerten."""
    if account.start_cash != benchmark.start_cash:
        raise ValueError("Depot und Vergleichsdepot brauchen dasselbe Startkapital")
    return Comparison(account.total_return(at, prices), benchmark.total_return(at, prices))
