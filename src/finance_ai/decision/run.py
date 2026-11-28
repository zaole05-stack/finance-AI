"""Ein Entscheidungslauf über Haupt-Portfolio und Schattenportfolios.

Das Haupt-Portfolio entscheidet über die Signale aller Experten. Jedes
Schattenportfolio bekommt nur die Signale eines Experten und dieselben Regeln.
So zeigt der Vergleich, ob die Kombination besser ist als jeder Experte allein.
"""

from __future__ import annotations

import sqlite3
import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta

from finance_ai.core import storage
from finance_ai.core.models import MAIN_PORTFOLIO, ROUTINE, shadow_portfolio
from finance_ai.core.testrun import PortfolioSpec, TestRun
from finance_ai.decision.agent import (
    Decision,
    DecisionRules,
    MarketCapLookup,
    decide,
    holdings_from_orders,
)
from finance_ai.decision.regelwerk import CodeRulesChangedError, changed_rules, code_rules
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
    # Beschluss 16: Routinekäufe lehnt auch der Lauf ohne Testlauf ab.
    no_routine = frozenset({ROUTINE})
    portfolios = [(MAIN_PORTFOLIO, PortfolioSpec(MAIN_PORTFOLIO, exclude_tags=no_routine))]
    for e in experts:
        name = shadow_portfolio(e)
        portfolios.append((name, PortfolioSpec(name, experts=frozenset({e}), exclude_tags=no_routine)))
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
    keine Entscheidungen mehr an. Weichen die Regeln im Code vom Stand beim
    Anlegen ab, auch nicht: Dann misst der Testlauf eine andere Strategie.
    """
    if run.is_ended:
        raise ValueError(f"Testlauf {run.id} ist beendet")
    changed = changed_rules(json.loads(run.code_rules), code_rules())
    if changed:
        raise CodeRulesChangedError(
            f"Testlauf {run.id}: Regeln im Code geändert seit dem Start ({', '.join(changed)}). "
            "Neuen Testlauf anlegen oder die Änderung zurücknehmen."
        )
    if at < run.started_at:
        raise ValueError(f"Testlauf {run.id} beginnt erst {run.started_at.isoformat()}")
    if run.settings.rules.max_market_cap is not None and market_cap is None:
        # Ohne Abfrage prüft decide() den Börsenwert nicht. Der Testlauf liefe
        # dann still ohne die eingefrorene Grenze.
        raise ValueError(
            f"Testlauf {run.id} hat eine Börsenwert-Grenze, aber keine Börsenwert-Abfrage"
        )
    portfolios = [(run.portfolio(spec), spec) for spec in run.portfolios]
    return _decide_all(
        conn, at, prices, portfolios, run.settings.rules, market_cap, since=run.started_at
    )


def _decide_all(
    conn: sqlite3.Connection,
    at: datetime,
    prices: PriceSource,
    portfolios: Iterable[tuple[str, PortfolioSpec]],
    rules: DecisionRules,
    market_cap: MarketCapLookup | None,
    since: datetime | None,
) -> list[Decision]:
    decisions = []
    for portfolio, spec in portfolios:
        pending = storage.pending_signals(conn, portfolio, at, experts=spec.experts, since=since)
        reasons = {s.id: spec.tag_rejection(s) for s in pending}
        signals = [s for s in pending if reasons[s.id] is None]
        holdings = holdings_from_orders(storage.list_orders(conn, portfolio))
        decision = decide(portfolio, signals, holdings, at, prices, rules, market_cap)
        filtered = [s for s in pending if reasons[s.id] is not None]
        if filtered:
            decision = replace(
                decision,
                outcomes=decision.outcomes + [(s.id, None, reasons[s.id]) for s in filtered],
                signals=decision.signals | {s.id: s for s in filtered},
            )
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
