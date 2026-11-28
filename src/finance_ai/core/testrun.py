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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from finance_ai.core.models import MAIN_PORTFOLIO, ROUTINE, Signal, require_tags, shadow_portfolio
from finance_ai.core.settings import Settings, settings_from_json, settings_to_json
from finance_ai.core.storage import from_db_time, to_db_time

_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_KEY = re.compile(r"[a-z0-9][a-z0-9:_-]*")


@dataclass(frozen=True, slots=True)
class PortfolioSpec:
    """Ein Portfolio im Testlauf und welche Signale es bekommt.

    `experts` None heißt: Signale aller Experten. Signale anderer Experten
    sieht das Portfolio gar nicht.

    Die Tag-Filter wirken anders: Ein Signal, das am Filter scheitert, wird
    mit Grund abgelehnt und gespeichert. So bleibt sichtbar, was das Portfolio
    ausgeschlossen hat (Beschluss 16). `include_tags` None heißt: kein
    Pflicht-Tag. Sonst braucht das Signal mindestens einen davon.

    `counts_for_verdict` False heißt: nur Beobachtung, zählt nicht für das
    Urteil über die Strategie.
    """

    key: str
    experts: frozenset[str] | None = None
    counts_for_verdict: bool = True
    include_tags: frozenset[str] | None = None
    exclude_tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not _KEY.fullmatch(self.key):
            raise ValueError(f"Ungültiger Portfolio-Schlüssel: {self.key!r}")
        if self.experts is not None:
            object.__setattr__(self, "experts", frozenset(self.experts))
            if not self.experts:
                raise ValueError("experts leer: None für alle Experten verwenden")
        object.__setattr__(self, "exclude_tags", require_tags(self.exclude_tags))
        if self.include_tags is not None:
            object.__setattr__(self, "include_tags", require_tags(self.include_tags))
            if not self.include_tags:
                raise ValueError("include_tags leer: None für keinen Pflicht-Tag verwenden")
            if self.include_tags & self.exclude_tags:
                raise ValueError("Ein Tag ist zugleich verlangt und ausgeschlossen")

    def tag_rejection(self, signal: Signal) -> str | None:
        """Grund, warum das Signal am Tag-Filter scheitert, oder None."""
        excluded = signal.tags & self.exclude_tags
        if excluded:
            return f"Tag-Filter: {', '.join(sorted(excluded))} ausgeschlossen"
        if self.include_tags is not None and not signal.tags & self.include_tags:
            return f"Tag-Filter: braucht {' oder '.join(sorted(self.include_tags))}"
        return None


@dataclass(frozen=True, slots=True)
class TestRun:
    __test__ = False  # Kein Test, auch wenn der Name so beginnt.

    id: str
    name: str
    owner: str
    started_at: datetime
    settings: Settings
    portfolios: tuple[PortfolioSpec, ...]
    # Regeln aus dem Code beim Anlegen, als JSON (decision/regelwerk.py).
    # "{}" bei Testläufen von vor Migration 5: Die nehmen keine Entscheidungen an.
    code_rules: str = "{}"
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


ROUTINE_CONTROL = "kontrolle:routine"


def default_portfolios(experts: Iterable[str]) -> tuple[PortfolioSpec, ...]:
    """Portfolios nach Beschluss 17.

    Haupt-Portfolio über alle Experten und ein Schattenportfolio je Experte,
    jeweils ohne Routinekäufe. Ist der Insider-Experte dabei, kommt ein
    Kontroll-Portfolio nur mit Routinekäufen dazu, das nur beobachtet.
    """
    names = sorted(set(experts))
    no_routine = frozenset({ROUTINE})
    specs = [PortfolioSpec(MAIN_PORTFOLIO, exclude_tags=no_routine)]
    specs += [
        PortfolioSpec(shadow_portfolio(e), experts=frozenset({e}), exclude_tags=no_routine)
        for e in names
    ]
    if "insider" in names:
        specs.append(
            PortfolioSpec(
                ROUTINE_CONTROL,
                experts=frozenset({"insider"}),
                counts_for_verdict=False,
                include_tags=no_routine,
            )
        )
    return tuple(specs)


def create_test_run(
    conn: sqlite3.Connection,
    id: str,
    name: str,
    owner: str,
    started_at: datetime,
    settings: Settings,
    portfolios: Iterable[PortfolioSpec],
    *,
    code_rules: Mapping,
) -> TestRun:
    """Legt einen Testlauf an. Das Regelwerk wird dabei eingefroren.

    Eingefroren werden die Einstellungen und `code_rules`, die Regeln aus dem
    Code (`decision.regelwerk.code_rules()`). `test_start` in den Einstellungen
    wird auf `started_at` gesetzt, damit beide nicht auseinanderlaufen.
    """
    run = TestRun(
        id=id,
        name=name.strip(),
        owner=owner.strip(),
        started_at=started_at,
        settings=replace(settings, test_start=started_at),
        portfolios=tuple(portfolios),
        code_rules=json.dumps(code_rules, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
    )
    with conn:
        conn.execute(
            "INSERT INTO test_runs (id, name, owner, started_at, settings, code_rules) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run.id, run.name, run.owner, to_db_time(run.started_at), settings_to_json(run.settings),
             run.code_rules),
        )
        conn.executemany(
            "INSERT INTO run_portfolios (portfolio, run_id, key, experts, counts_for_verdict, "
            "position, include_tags, exclude_tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run.portfolio(spec),
                    run.id,
                    spec.key,
                    json.dumps(sorted(spec.experts)) if spec.experts is not None else None,
                    int(spec.counts_for_verdict),
                    position,
                    _tags_json(spec.include_tags),
                    _tags_json(spec.exclude_tags),
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
        "SELECT key, experts, counts_for_verdict, include_tags, exclude_tags FROM run_portfolios "
        "WHERE run_id = ? ORDER BY position",
        (row["id"],),
    )
    return TestRun(
        id=row["id"],
        name=row["name"],
        owner=row["owner"],
        started_at=from_db_time(row["started_at"]),
        settings=settings_from_json(row["settings"]),
        code_rules=row["code_rules"],
        portfolios=tuple(
            PortfolioSpec(
                key=spec["key"],
                experts=frozenset(json.loads(spec["experts"])) if spec["experts"] is not None else None,
                counts_for_verdict=bool(spec["counts_for_verdict"]),
                include_tags=_tags_from_json(spec["include_tags"]),
                exclude_tags=_tags_from_json(spec["exclude_tags"]) or frozenset(),
            )
            for spec in specs
        ),
        ended_at=from_db_time(row["ended_at"]) if row["ended_at"] else None,
    )


def _tags_json(tags: frozenset[str] | None) -> str | None:
    return None if tags is None else json.dumps(sorted(tags))


def _tags_from_json(text: str | None) -> frozenset[str] | None:
    return None if text is None else frozenset(json.loads(text))
