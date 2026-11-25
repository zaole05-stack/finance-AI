"""Daten für das Dashboard, ohne Streamlit, damit sie testbar bleiben.

Alle Kennzahlen kommen direkt aus `evaluation.report.evaluate`. Das Dashboard
rechnet nichts selbst, so können Dashboard und Auswertung nicht auseinanderlaufen.
"""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from finance_ai.core import storage
from finance_ai.core.models import Order
from finance_ai.core.settings import Settings
from finance_ai.evaluation.report import PortfolioReport, Verdict, evaluate
from finance_ai.paper_trading.market_data import CachedPriceSource
from finance_ai.paper_trading.prices import NoPriceError, PriceSource

DEFAULT_DB = Path("data") / "finance_ai.sqlite"


def database_path() -> Path:
    return Path(os.environ.get("FINANCE_AI_DB", DEFAULT_DB))


@dataclass(frozen=True, slots=True)
class Warning_:
    level: str  # "error" oder "info"
    portfolio: str
    text: str


@dataclass(frozen=True, slots=True)
class Overview:
    at: datetime
    test_start: datetime | None
    reports: list[PortfolioReport]
    warnings: list[Warning_]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Run:
    """Ein Entscheidungslauf eines Portfolios: Orders und abgelehnte Signale."""

    portfolio: str
    decided_at: datetime
    orders: list[Order]
    rejected: dict[str, list[sqlite3.Row]]


def test_start(conn: sqlite3.Connection, settings: Settings) -> datetime | None:
    if settings.test_start is not None:
        return settings.test_start
    orders = storage.list_orders(conn)
    return orders[0].created_at if orders else None


def overview(
    conn: sqlite3.Connection, settings: Settings, prices: PriceSource, at: datetime | None = None
) -> Overview:
    at = at or datetime.now(UTC)
    start = test_start(conn, settings)
    if start is None:
        return Overview(at, None, [], [])
    try:
        reports = evaluate(
            storage.list_orders(conn),
            prices,
            settings.benchmark_ticker,
            start,
            at,
            settings.rules.start_cash,
            settings.costs,
        )
    except NoPriceError as error:
        return Overview(at, start, [], [], f"Kurse fehlen: {error}. Bitte Kurse aktualisieren.")
    return Overview(at, start, reports, warnings(reports))


def warnings(reports: list[PortfolioReport]) -> list[Warning_]:
    result = []
    if any(r.benchmark_pending for r in reports):
        result.append(
            Warning_("info", "", "Der ETF hat seit Teststart noch keinen Kurs. Er wird zum ersten Kurs gekauft.")
        )
    for r in reports:
        if r.verdict is Verdict.STOP:
            result.append(
                Warning_("error", r.portfolio, f"Abbruchregel greift: {r.portfolio} einstellen.")
            )
        elif r.verdict is Verdict.BEHIND:
            result.append(Warning_("info", r.portfolio, f"{r.portfolio} liegt hinter dem ETF."))
        if r.pending_immediate or r.pending_delayed:
            result.append(
                Warning_(
                    "info",
                    r.portfolio,
                    f"{r.portfolio}: {r.pending_immediate} Orders sofort und "
                    f"{r.pending_delayed} verzögert noch offen (noch kein Kurs).",
                )
            )
        if r.rejected_delayed or r.rejected_immediate:
            result.append(
                Warning_(
                    "info",
                    r.portfolio,
                    f"{r.portfolio}: {r.rejected_immediate} Orders sofort und "
                    f"{r.rejected_delayed} verzögert abgelehnt.",
                )
            )
    return result


def runs(conn: sqlite3.Connection, portfolio: str) -> list[Run]:
    """Entscheidungsläufe eines Portfolios, neueste zuerst."""
    by_time: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in storage.list_decisions(conn, portfolio):
        by_time[row["decided_at"]].append(row)
    order_times: dict[str, list[Order]] = defaultdict(list)
    for order in storage.list_orders(conn, portfolio):
        order_times[storage.to_db_time(order.created_at)].append(order)

    result = []
    for key in sorted(set(by_time) | set(order_times), reverse=True):
        rejected: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in by_time.get(key, []):
            if row["order_id"] is None:
                rejected[row["reason"].split(" (")[0]].append(row)
        # Reihenfolge wie vom Agenten erzeugt: erst Verkäufe, dann Käufe nach Rang.
        result.append(Run(portfolio, storage.from_db_time(key), order_times.get(key, []), dict(rejected)))
    return result


def portfolios(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT portfolio FROM orders UNION SELECT portfolio FROM decisions ORDER BY 1"
    ).fetchall()
    names = [r[0] for r in rows]
    # Haupt-Portfolio zuerst
    return sorted(names, key=lambda n: (n != "main", n))


def tracked_tickers(conn: sqlite3.Connection, settings: Settings) -> set[str]:
    """Alle Ticker, für die Kurse gebraucht werden: Orders plus Vergleichs-ETF."""
    tickers = {o.ticker for o in storage.list_orders(conn)}
    tickers.add(settings.benchmark_ticker)
    return tickers


def refresh_prices(
    conn: sqlite3.Connection, settings: Settings, source: CachedPriceSource, at: datetime
) -> list[str]:
    """Lädt Stundenkurse ab Teststart für alle Ticker. Gibt die Ticker ohne Kurse zurück."""
    start = test_start(conn, settings) or at
    missing = []
    for ticker in sorted(tracked_tickers(conn, settings)):
        try:
            source.download(ticker, start - timedelta(days=1), at)
        except NoPriceError:
            missing.append(ticker)
    return missing
