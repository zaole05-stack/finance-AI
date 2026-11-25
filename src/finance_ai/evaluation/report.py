"""Auswertung je Portfolio gegen den ETF, nach den Regeln aus KONZEPT.md.

Bewertet wird nach allen Kosten (Liquidationswert). Maßgeblich für das Urteil
ist die **verzögerte** Ausführung (1 Stunde), denn so würde Phase 1 mit
manueller Freigabe tatsächlich handeln.

Während des Testlaufs gilt nur die harte Grenze: mehr als 20 % Verlust heißt
einstellen. Ein Rückstand zum ETF wird gemeldet, führt aber nicht sofort zum
Abbruch. Sonst würde schon ein schlechter erster Tag reichen. Nach Ende des
Testlaufs (Standard 182 Tage) gilt die Tabelle:
≥ 5 Prozentpunkte vor dem ETF → klein mit echtem Geld starten,
0 bis 5 → um 6 Monate verlängern, dahinter → einstellen.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from finance_ai.core.models import Order
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.engine import buy_and_hold, simulate
from finance_ai.paper_trading.prices import PriceSource

TEST_DURATION = timedelta(days=182)
MAX_LOSS = Decimal("-0.20")
GO_LIVE_MARGIN = Decimal("0.05")


class Verdict(StrEnum):
    RUNNING = "läuft"
    BEHIND = "läuft, liegt hinter dem ETF"
    STOP = "einstellen"
    EXTEND = "verlängern"
    GO_LIVE = "klein mit echtem Geld starten"


@dataclass(frozen=True, slots=True)
class PortfolioReport:
    portfolio: str
    orders: int
    rejected_immediate: int
    rejected_delayed: int
    return_immediate: Decimal
    return_delayed: Decimal
    benchmark_return: Decimal
    verdict: Verdict

    @property
    def excess_delayed(self) -> Decimal:
        return self.return_delayed - self.benchmark_return

    @property
    def approval_cost(self) -> Decimal:
        """Was die Stunde Freigabe-Verzögerung kostet (positiv = Verlust)."""
        return self.return_immediate - self.return_delayed


def evaluate(
    orders: Iterable[Order],
    prices: PriceSource,
    benchmark_ticker: str,
    start: datetime,
    at: datetime,
    start_cash: Decimal,
    costs: CostModel,
    duration: timedelta = TEST_DURATION,
) -> list[PortfolioReport]:
    """Bericht je Portfolio, sortiert nach Name. Portfolios ohne Orders fehlen."""
    orders = [o for o in orders if o.created_at <= at]
    counts: dict[str, int] = {}
    for order in orders:
        counts[order.portfolio] = counts.get(order.portfolio, 0) + 1
    benchmark = buy_and_hold(benchmark_ticker, start, prices, start_cash, costs)
    benchmark_return = benchmark.total_return(at, prices)
    finished = at - start >= duration

    reports = []
    for portfolio, accounts in sorted(simulate(orders, prices, start_cash, costs).items()):
        immediate = accounts.immediate.total_return(at, prices)
        delayed = accounts.delayed.total_return(at, prices)
        reports.append(
            PortfolioReport(
                portfolio=portfolio,
                orders=counts[portfolio],
                rejected_immediate=len(accounts.immediate.rejections),
                rejected_delayed=len(accounts.delayed.rejections),
                return_immediate=immediate,
                return_delayed=delayed,
                benchmark_return=benchmark_return,
                verdict=verdict(delayed, benchmark_return, finished),
            )
        )
    return reports


def verdict(portfolio_return: Decimal, benchmark_return: Decimal, finished: bool) -> Verdict:
    if portfolio_return < MAX_LOSS:
        return Verdict.STOP
    excess = portfolio_return - benchmark_return
    if not finished:
        return Verdict.BEHIND if excess < 0 else Verdict.RUNNING
    if excess >= GO_LIVE_MARGIN:
        return Verdict.GO_LIVE
    if excess >= 0:
        return Verdict.EXTEND
    return Verdict.STOP
