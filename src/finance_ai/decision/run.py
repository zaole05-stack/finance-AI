"""Ein Entscheidungslauf über Haupt-Portfolio und Schattenportfolios.

Das Haupt-Portfolio entscheidet über die Signale aller Experten. Jedes
Schattenportfolio bekommt nur die Signale eines Experten und dieselben Regeln.
So zeigt der Vergleich, ob die Kombination besser ist als jeder Experte allein.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta

from finance_ai.core import storage
from finance_ai.core.models import MAIN_PORTFOLIO, shadow_portfolio
from finance_ai.decision.agent import (
    Decision,
    DecisionRules,
    MarketCapLookup,
    decide,
    holdings_from_orders,
)
from finance_ai.paper_trading.market_data import CachedPriceSource
from finance_ai.paper_trading.prices import NoPriceError, PriceSource


def run_decisions(
    conn: sqlite3.Connection,
    at: datetime,
    prices: PriceSource,
    experts: Iterable[str],
    rules: DecisionRules = DecisionRules(),
    market_cap: MarketCapLookup | None = None,
) -> list[Decision]:
    """Entscheidet für alle Portfolios über offene Signale und speichert das Ergebnis."""
    portfolios = [(MAIN_PORTFOLIO, None)] + [(shadow_portfolio(e), e) for e in experts]
    decisions = []
    for portfolio, expert in portfolios:
        signals = storage.pending_signals(conn, portfolio, at, expert)
        holdings = holdings_from_orders(storage.list_orders(conn, portfolio))
        decision = decide(portfolio, signals, holdings, at, prices, rules, market_cap)
        storage.save_decision(conn, portfolio, at, decision.orders, decision.outcomes)
        decisions.append(decision)
    return decisions


def download_recent_prices(
    source: CachedPriceSource, tickers: Iterable[str], at: datetime, days: int = 7
) -> list[str]:
    """Lädt Stundenkurse der letzten Tage. Gibt die Ticker ohne Kurse zurück."""
    missing = []
    for ticker in sorted(set(tickers)):
        try:
            source.download(ticker, at - timedelta(days=days), at)
        except NoPriceError:
            missing.append(ticker)
    return missing
