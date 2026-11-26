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
from finance_ai.core.testrun import TestRun
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
    """Entscheidet für alle Portfolios über offene Signale und speichert das Ergebnis.

    Portfolios ohne Testlauf (`main`, `shadow:<experte>`). Für einen Testlauf
    `run_test_run` verwenden.
    """
    portfolios = [(MAIN_PORTFOLIO, None)] + [(shadow_portfolio(e), {e}) for e in experts]
    return _decide_all(conn, at, prices, portfolios, rules, market_cap, since=None)


def run_test_run(
    conn: sqlite3.Connection,
    run: TestRun,
    at: datetime,
    prices: PriceSource,
    market_cap: MarketCapLookup | None = None,
) -> list[Decision]:
    """Entscheidungslauf für einen Testlauf mit dessen eingefrorenen Regeln.

    Nur Signale ab Beginn des Testlaufs zählen. Ein beendeter Testlauf nimmt
    keine Entscheidungen mehr an.
    """
    if run.is_ended:
        raise ValueError(f"Testlauf {run.id} ist beendet")
    if at < run.started_at:
        raise ValueError(f"Testlauf {run.id} beginnt erst {run.started_at.isoformat()}")
    portfolios = [(run.portfolio(spec), spec.experts) for spec in run.portfolios]
    return _decide_all(
        conn, at, prices, portfolios, run.settings.rules, market_cap, since=run.started_at
    )


def _decide_all(
    conn: sqlite3.Connection,
    at: datetime,
    prices: PriceSource,
    portfolios: Iterable[tuple[str, Iterable[str] | None]],
    rules: DecisionRules,
    market_cap: MarketCapLookup | None,
    since: datetime | None,
) -> list[Decision]:
    decisions = []
    for portfolio, experts in portfolios:
        signals = storage.pending_signals(conn, portfolio, at, experts=experts, since=since)
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
