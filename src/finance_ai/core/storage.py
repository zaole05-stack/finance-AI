"""SQLite-Speicher für Signale, Orders und Positionen.

Geldbeträge und Stückzahlen werden als Text gespeichert, damit `Decimal` ohne
Rundung zurückkommt. Zeitpunkte werden in UTC als ISO-8601 gespeichert.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from os import PathLike

from finance_ai.core.models import Order, Position, Side, Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id          TEXT PRIMARY KEY,
    expert      TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    side        TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    source_url  TEXT NOT NULL,
    summary     TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    confidence  REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS signals_expert_created ON signals (expert, created_at);

CREATE TABLE IF NOT EXISTS orders (
    id         TEXT PRIMARY KEY,
    portfolio  TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    side       TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rationale  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_portfolio_created ON orders (portfolio, created_at);

CREATE TABLE IF NOT EXISTS order_signals (
    order_id  TEXT NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    signal_id TEXT NOT NULL REFERENCES signals (id),
    position  INTEGER NOT NULL,
    PRIMARY KEY (order_id, signal_id)
);

CREATE TABLE IF NOT EXISTS positions (
    portfolio TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    quantity  TEXT NOT NULL,
    avg_price TEXT NOT NULL,
    PRIMARY KEY (portfolio, ticker)
);

-- Jedes Signal wird je Portfolio genau einmal entschieden: Order oder Ablehnung mit Grund.
CREATE TABLE IF NOT EXISTS decisions (
    signal_id  TEXT NOT NULL REFERENCES signals (id),
    portfolio  TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    order_id   TEXT REFERENCES orders (id),
    reason     TEXT NOT NULL,
    PRIMARY KEY (signal_id, portfolio)
);

-- Kursbalken: Eröffnungskurs gilt ab bar_start, Schlusskurs erst ab bar_end.
CREATE TABLE IF NOT EXISTS price_bars (
    ticker     TEXT NOT NULL,
    bar_start  TEXT NOT NULL,
    bar_end    TEXT NOT NULL,
    open       TEXT NOT NULL,
    close      TEXT NOT NULL,
    PRIMARY KEY (ticker, bar_start),
    CHECK (bar_end > bar_start)
);
CREATE INDEX IF NOT EXISTS price_bars_end ON price_bars (ticker, bar_end);
"""


def connect(path: str | PathLike[str] = ":memory:") -> sqlite3.Connection:
    """Öffnet die Datenbank und legt fehlende Tabellen an."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def save_signal(conn: sqlite3.Connection, signal: Signal) -> None:
    with conn:
        conn.execute("INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", _signal_row(signal))


def save_new_signals(conn: sqlite3.Connection, signals: Iterable[Signal]) -> int:
    """Speichert nur Signale, deren ID noch fehlt. Gibt die Anzahl neuer Signale zurück.

    So kann ein Experte denselben Tag mehrmals abrufen, ohne doppelte Signale.
    Ein schon gespeichertes Signal bleibt unverändert, auch sein `created_at`.
    """
    with conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [_signal_row(signal) for signal in signals],
        )
        return conn.total_changes - before


def _signal_row(signal: Signal) -> tuple:
    return (
        signal.id,
        signal.expert,
        signal.ticker,
        signal.side.value,
        signal.source_url,
        signal.summary,
        to_db_time(signal.observed_at),
        to_db_time(signal.created_at),
        signal.confidence,
    )


def get_signal(conn: sqlite3.Connection, signal_id: str) -> Signal | None:
    row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
    return _signal_from_row(row) if row else None


def list_signals(conn: sqlite3.Connection, expert: str | None = None) -> list[Signal]:
    """Alle Signale, optional nur eines Experten, nach Erzeugungszeit sortiert."""
    if expert is None:
        rows = conn.execute("SELECT * FROM signals ORDER BY created_at, id")
    else:
        rows = conn.execute(
            "SELECT * FROM signals WHERE expert = ? ORDER BY created_at, id", (expert,)
        )
    return [_signal_from_row(row) for row in rows]


def save_order(conn: sqlite3.Connection, order: Order) -> None:
    """Speichert die Order samt Verweisen. Alle Signale müssen schon gespeichert sein."""
    with conn:
        _insert_order(conn, order)


def _insert_order(conn: sqlite3.Connection, order: Order) -> None:
    conn.execute(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            order.id,
            order.portfolio,
            order.ticker,
            order.side.value,
            str(order.quantity),
            to_db_time(order.created_at),
            order.rationale,
        ),
    )
    conn.executemany(
        "INSERT INTO order_signals VALUES (?, ?, ?)",
        [(order.id, signal_id, i) for i, signal_id in enumerate(order.signal_ids)],
    )


def get_order(conn: sqlite3.Connection, order_id: str) -> Order | None:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return _order_from_row(conn, row) if row else None


def list_orders(conn: sqlite3.Connection, portfolio: str | None = None) -> list[Order]:
    """Alle Orders, optional nur eines Portfolios, nach Erzeugungszeit sortiert."""
    if portfolio is None:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at, id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM orders WHERE portfolio = ? ORDER BY created_at, id", (portfolio,)
        ).fetchall()
    return [_order_from_row(conn, row) for row in rows]


def pending_signals(
    conn: sqlite3.Connection, portfolio: str, until: datetime, expert: str | None = None
) -> list[Signal]:
    """Signale bis `until`, über die für dieses Portfolio noch nicht entschieden wurde."""
    query = (
        "SELECT * FROM signals WHERE created_at <= ? AND id NOT IN "
        "(SELECT signal_id FROM decisions WHERE portfolio = ?)"
    )
    params: list = [to_db_time(until), portfolio]
    if expert is not None:
        query += " AND expert = ?"
        params.append(expert)
    rows = conn.execute(query + " ORDER BY created_at, id", params)
    return [_signal_from_row(row) for row in rows]


def save_decision(
    conn: sqlite3.Connection,
    portfolio: str,
    decided_at: datetime,
    orders: Iterable[Order],
    outcomes: Iterable[tuple[str, str | None, str]],
) -> None:
    """Speichert Orders und Entscheidungen atomar.

    `outcomes` enthält je Signal (signal_id, order_id oder None, Grund).
    """
    with conn:
        for order in orders:
            _insert_order(conn, order)
        conn.executemany(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
            [
                (signal_id, portfolio, to_db_time(decided_at), order_id, reason)
                for signal_id, order_id, reason in outcomes
            ],
        )


def list_decisions(conn: sqlite3.Connection, portfolio: str) -> list[sqlite3.Row]:
    """Alle Entscheidungen eines Portfolios mit Signal, für Briefing und Dashboard."""
    return conn.execute(
        """
        SELECT d.signal_id, d.decided_at, d.order_id, d.reason, s.expert, s.ticker, s.summary,
               s.source_url
        FROM decisions d JOIN signals s ON s.id = d.signal_id
        WHERE d.portfolio = ? ORDER BY d.decided_at, s.ticker, d.signal_id
        """,
        (portfolio,),
    ).fetchall()


def _order_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> Order:
    order_id = row["id"]
    signal_ids = tuple(
        r["signal_id"]
        for r in conn.execute(
            "SELECT signal_id FROM order_signals WHERE order_id = ? ORDER BY position",
            (order_id,),
        )
    )
    return Order(
        portfolio=row["portfolio"],
        ticker=row["ticker"],
        side=Side(row["side"]),
        quantity=Decimal(row["quantity"]),
        created_at=from_db_time(row["created_at"]),
        signal_ids=signal_ids,
        rationale=row["rationale"],
        id=row["id"],
    )


def save_position(conn: sqlite3.Connection, position: Position) -> None:
    """Legt die Position an oder überschreibt den bisherigen Bestand."""
    with conn:
        conn.execute(
            """
            INSERT INTO positions VALUES (?, ?, ?, ?)
            ON CONFLICT (portfolio, ticker)
            DO UPDATE SET quantity = excluded.quantity, avg_price = excluded.avg_price
            """,
            (position.portfolio, position.ticker, str(position.quantity), str(position.avg_price)),
        )


def delete_position(conn: sqlite3.Connection, portfolio: str, ticker: str) -> None:
    """Entfernt eine Position, z. B. nach vollständigem Verkauf."""
    with conn:
        conn.execute(
            "DELETE FROM positions WHERE portfolio = ? AND ticker = ?",
            (portfolio, ticker.strip().upper()),
        )


def get_positions(conn: sqlite3.Connection, portfolio: str) -> list[Position]:
    rows = conn.execute(
        "SELECT * FROM positions WHERE portfolio = ? ORDER BY ticker", (portfolio,)
    )
    return [
        Position(
            portfolio=row["portfolio"],
            ticker=row["ticker"],
            quantity=Decimal(row["quantity"]),
            avg_price=Decimal(row["avg_price"]),
        )
        for row in rows
    ]


def _signal_from_row(row: sqlite3.Row) -> Signal:
    return Signal(
        expert=row["expert"],
        ticker=row["ticker"],
        side=Side(row["side"]),
        source_url=row["source_url"],
        summary=row["summary"],
        observed_at=from_db_time(row["observed_at"]),
        created_at=from_db_time(row["created_at"]),
        confidence=row["confidence"],
        id=row["id"],
    )


def to_db_time(value: datetime) -> str:
    # Immer UTC, damit ORDER BY auf dem Text chronologisch sortiert.
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def from_db_time(value: str) -> datetime:
    return datetime.fromisoformat(value)
