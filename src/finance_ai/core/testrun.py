"""Testläufe: ein eingefrorenes Regelwerk und die Portfolios, die damit laufen.

Ein Testlauf legt beim Anlegen fest, nach welchen Regeln entschieden wird und
welche Portfolios welche Signale bekommen. Danach ändert sich daran nichts mehr
(docs/BEREICH-A.md, Beschlüsse 1 bis 3). Eine Änderung der Strategie heißt:
neuer Testlauf. Die Datenbank setzt das mit Triggern durch (Migration 2 in
core/storage.py).

Die Portfolios eines Testlaufs heißen `<testlauf>/<key>`, z. B.
`insider-91d/main` oder `insider-91d/shadow:insider`. Portfolios ohne
Testlauf (`main`, `shadow:insider`) bleiben wie bisher nutzbar.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime

from finance_ai.core.models import MAIN_PORTFOLIO, shadow_portfolio
from finance_ai.core.settings import Settings, settings_from_json, settings_to_json
from finance_ai.core.storage import from_db_time, to_db_time

_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_KEY = re.compile(r"[a-z0-9][a-z0-9:_-]*")


@dataclass(frozen=True, slots=True)
class PortfolioSpec:
    """Ein Portfolio im Testlauf und welche Signale es bekommt.

    `experts` None heißt: Signale aller Experten. `counts_for_verdict` False
    heißt: nur Beobachtung, zählt nicht für das Urteil über die Strategie.
    """

    key: str
    experts: frozenset[str] | None = None
    counts_for_verdict: bool = True

    def __post_init__(self) -> None:
        if not _KEY.fullmatch(self.key):
            raise ValueError(f"Ungültiger Portfolio-Schlüssel: {self.key!r}")
        if self.experts is not None:
            object.__setattr__(self, "experts", frozenset(self.experts))
            if not self.experts:
                raise ValueError("experts leer: None für alle Experten verwenden")


@dataclass(frozen=True, slots=True)
class TestRun:
    __test__ = False  # Kein Test, auch wenn der Name so beginnt.

    id: str
    name: str
    owner: str
    started_at: datetime
    settings: Settings
    portfolios: tuple[PortfolioSpec, ...]
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.id):
            raise ValueError(f"Ungültige Testlauf-ID: {self.id!r} (erlaubt: a-z, 0-9, -)")
        if not self.name.strip() or not self.owner.strip():
            raise ValueError("Name und Verantwortlicher sind Pflicht")
        if self.started_at.utcoffset() is None:
            raise ValueError("started_at braucht eine Zeitzone")
        if not self.portfolios:
            raise ValueError("Testlauf ohne Portfolio")
        keys = [spec.key for spec in self.portfolios]
        if len(set(keys)) != len(keys):
            raise ValueError("Portfolio-Schlüssel doppelt")
        if not any(spec.counts_for_verdict for spec in self.portfolios):
            raise ValueError("Mindestens ein Portfolio muss für das Urteil zählen")

    def portfolio(self, spec: PortfolioSpec) -> str:
        return portfolio_name(self.id, spec.key)

    @property
    def is_ended(self) -> bool:
        return self.ended_at is not None


def portfolio_name(run_id: str, key: str) -> str:
    return f"{run_id}/{key}"


def default_portfolios(experts: Iterable[str]) -> tuple[PortfolioSpec, ...]:
    """Haupt-Portfolio über alle Experten plus ein Schattenportfolio je Experte."""
    return (PortfolioSpec(MAIN_PORTFOLIO),) + tuple(
        PortfolioSpec(shadow_portfolio(e), experts=frozenset({e})) for e in sorted(set(experts))
    )


def create_test_run(
    conn: sqlite3.Connection,
    id: str,
    name: str,
    owner: str,
    started_at: datetime,
    settings: Settings,
    portfolios: Iterable[PortfolioSpec],
) -> TestRun:
    """Legt einen Testlauf an. Das Regelwerk wird dabei eingefroren.

    `test_start` in den Einstellungen wird auf `started_at` gesetzt, damit
    beide nicht auseinanderlaufen.
    """
    run = TestRun(
        id=id,
        name=name.strip(),
        owner=owner.strip(),
        started_at=started_at,
        settings=replace(settings, test_start=started_at),
        portfolios=tuple(portfolios),
    )
    with conn:
        conn.execute(
            "INSERT INTO test_runs (id, name, owner, started_at, settings) VALUES (?, ?, ?, ?, ?)",
            (run.id, run.name, run.owner, to_db_time(run.started_at), settings_to_json(run.settings)),
        )
        conn.executemany(
            "INSERT INTO run_portfolios VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    run.portfolio(spec),
                    run.id,
                    spec.key,
                    json.dumps(sorted(spec.experts)) if spec.experts is not None else None,
                    int(spec.counts_for_verdict),
                    position,
                )
                for position, spec in enumerate(run.portfolios)
            ],
        )
    return run


def get_test_run(conn: sqlite3.Connection, run_id: str) -> TestRun | None:
    row = conn.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,)).fetchone()
    return None if row is None else _run_from_row(conn, row)


def list_test_runs(conn: sqlite3.Connection) -> list[TestRun]:
    rows = conn.execute("SELECT * FROM test_runs ORDER BY started_at, id").fetchall()
    return [_run_from_row(conn, row) for row in rows]


def end_test_run(conn: sqlite3.Connection, run_id: str, at: datetime) -> TestRun:
    """Beendet einen Testlauf. Danach nimmt er keine Entscheidungen mehr an."""
    if at.utcoffset() is None:
        raise ValueError("at braucht eine Zeitzone")
    with conn:
        cursor = conn.execute(
            "UPDATE test_runs SET ended_at = ? WHERE id = ?", (to_db_time(at), run_id)
        )
    if cursor.rowcount == 0:
        raise KeyError(run_id)
    run = get_test_run(conn, run_id)
    assert run is not None
    return run


def _run_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> TestRun:
    specs = conn.execute(
        "SELECT key, experts, counts_for_verdict FROM run_portfolios WHERE run_id = ? ORDER BY position",
        (row["id"],),
    )
    return TestRun(
        id=row["id"],
        name=row["name"],
        owner=row["owner"],
        started_at=from_db_time(row["started_at"]),
        settings=settings_from_json(row["settings"]),
        portfolios=tuple(
            PortfolioSpec(
                key=spec["key"],
                experts=frozenset(json.loads(spec["experts"])) if spec["experts"] is not None else None,
                counts_for_verdict=bool(spec["counts_for_verdict"]),
            )
            for spec in specs
        ),
        ended_at=from_db_time(row["ended_at"]) if row["ended_at"] else None,
    )
