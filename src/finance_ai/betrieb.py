"""Einstiegsbefehl für den Dauerbetrieb eines Testlaufs (Bereich A, M6).

    python -m finance_ai.betrieb testlauf-anlegen --id insider-91d --name "…" --owner …
    python -m finance_ai.betrieb lauf --testlauf insider-91d
    python -m finance_ai.betrieb protokoll --testlauf insider-91d

`lauf` ist für den stündlichen Aufruf durch die Windows-Aufgabenplanung
gedacht (docs/BETRIEB.md). Jeder Aufruf darf beliebig oft kommen:

1. tägliches Backup, falls fällig (Beschluss 8);
2. Scan der Form-4-Meldungen seit dem letzten gelungenen Scan. Gespeicherte
   Signale werden nicht doppelt angelegt;
3. Stundenkurse für offene Signale, Bestände und den ETF;
4. Entscheidung mit den eingefrorenen Regeln des Testlaufs, zum Zeitpunkt
   „jetzt“ (Beschluss 6, Variante A);
5. eine Zeile in `operation_runs`, auch wenn ein Schritt fehlschlägt.

Scheitert der Kursabruf, wird in diesem Lauf nicht entschieden. Sonst würden
Signale wegen eines Netzfehlers dauerhaft mit „kein aktueller Kurs“ abgelehnt.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from finance_ai.core import storage
from finance_ai.core.backup import backup_if_due
from finance_ai.core.models import Signal
from finance_ai.core.settings import load_settings
from finance_ai.core.testrun import TestRun, create_test_run, default_portfolios, get_test_run
from finance_ai.decision.agent import MarketCapLookup, holdings_from_orders
from finance_ai.decision.regelwerk import code_rules, fingerprint
from finance_ai.decision.run import download_recent_prices, run_test_run
from finance_ai.paper_trading.market_data import CachedPriceSource

# Liefert die Signale aus Meldungen zwischen `since` und `now`.
Scan = Callable[[datetime, datetime], list[Signal]]
Clock = Callable[[], datetime]

DEFAULT_DB = Path("data") / "finance_ai.sqlite"


@dataclass(frozen=True, slots=True)
class OperationRun:
    test_run: str
    started_at: datetime
    finished_at: datetime
    scan_since: datetime
    scan_until: datetime | None
    new_signals: int
    orders: int
    missing_prices: tuple[str, ...]
    backup: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


def scan_start(conn: sqlite3.Connection, run: TestRun) -> datetime:
    """Ende des letzten gelungenen Scans, sonst der Beginn des Testlaufs."""
    row = conn.execute(
        "SELECT MAX(scan_until) FROM operation_runs WHERE test_run = ?", (run.id,)
    ).fetchone()
    return storage.from_db_time(row[0]) if row[0] else run.started_at


def tracked_tickers(conn: sqlite3.Connection, run: TestRun, at: datetime) -> set[str]:
    """Ticker, für die der Lauf Kurse braucht: offene Signale, Bestände, ETF."""
    tickers = {run.settings.benchmark_ticker}
    for spec in run.portfolios:
        portfolio = run.portfolio(spec)
        pending = storage.pending_signals(
            conn, portfolio, at, experts=spec.experts, since=run.started_at
        )
        tickers |= {s.ticker for s in pending}
        tickers |= set(holdings_from_orders(storage.list_orders(conn, portfolio)))
    return tickers


def run_once(
    conn: sqlite3.Connection,
    run: TestRun,
    scan: Scan,
    prices: CachedPriceSource,
    market_cap: MarketCapLookup,
    backup_dir: Path,
    clock: Clock = lambda: datetime.now(UTC),
) -> OperationRun:
    """Ein Lauf: Backup, Scan, Kurse, Entscheidung, Protokoll. Wirft nicht.

    Fehler einzelner Schritte stehen im Protokoll. Netz und SEC werfen sehr
    verschiedene Ausnahmen, deshalb fängt jeder Schritt `Exception`.
    """
    now = clock()
    errors: list[str] = []

    backup = None
    try:
        path = backup_if_due(conn, backup_dir, now)
        backup = str(path) if path else None
    except Exception as error:  # noqa: BLE001
        errors.append(f"Backup: {error}")

    since, until, new = scan_start(conn, run), None, 0
    try:
        new = storage.save_new_signals(conn, scan(since, now))
        until = now
    except Exception as error:  # noqa: BLE001
        errors.append(f"Scan: {error}")

    missing: list[str] = []
    orders = 0
    try:
        missing = download_recent_prices(prices, tracked_tickers(conn, run, now), now)
    except Exception as error:  # noqa: BLE001
        errors.append(f"Kurse: {error}. Keine Entscheidung in diesem Lauf.")
    else:
        try:
            decisions = run_test_run(conn, run, now, prices, market_cap)
            orders = sum(len(d.orders) for d in decisions)
        except Exception as error:  # noqa: BLE001
            errors.append(f"Entscheidung: {error}")

    result = OperationRun(
        test_run=run.id,
        started_at=now,
        finished_at=clock(),
        scan_since=since,
        scan_until=until,
        new_signals=new,
        orders=orders,
        missing_prices=tuple(missing),
        backup=backup,
        error=" | ".join(errors) or None,
    )
    _save(conn, result)
    return result


def _save(conn: sqlite3.Connection, r: OperationRun) -> None:
    with conn:
        conn.execute(
            "INSERT INTO operation_runs (test_run, started_at, finished_at, scan_since, scan_until, "
            "new_signals, orders, missing_prices, backup, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.test_run, storage.to_db_time(r.started_at), storage.to_db_time(r.finished_at),
                storage.to_db_time(r.scan_since),
                storage.to_db_time(r.scan_until) if r.scan_until else None,
                r.new_signals, r.orders, json.dumps(list(r.missing_prices)), r.backup, r.error,
            ),
        )


def list_operation_runs(conn: sqlite3.Connection, run_id: str, limit: int = 20) -> list[OperationRun]:
    """Die letzten Läufe, neuester zuerst."""
    rows = conn.execute(
        "SELECT * FROM operation_runs WHERE test_run = ? ORDER BY started_at DESC, id DESC LIMIT ?",
        (run_id, limit),
    ).fetchall()
    return [
        OperationRun(
            test_run=r["test_run"],
            started_at=storage.from_db_time(r["started_at"]),
            finished_at=storage.from_db_time(r["finished_at"]),
            scan_since=storage.from_db_time(r["scan_since"]),
            scan_until=storage.from_db_time(r["scan_until"]) if r["scan_until"] else None,
            new_signals=r["new_signals"],
            orders=r["orders"],
            missing_prices=tuple(json.loads(r["missing_prices"])),
            backup=r["backup"],
            error=r["error"],
        )
        for r in rows
    ]


# --- Anbindung an SEC und Yahoo ------------------------------------------------------


def edgar_scan(client) -> Scan:
    """Atom-Feed für die letzten Stunden, Tagesindizes für längere Lücken.

    Der Feed reicht nur einige hundert Meldungen zurück. War der Laptop länger
    aus, holen die Tagesindizes die Tage seit `since` nach. Doppelte Signale
    sind unschädlich.
    """
    from finance_ai.experts.insider import scan_day, scan_recent

    def scan(since: datetime, now: datetime) -> list[Signal]:
        signals = scan_recent(client, since)
        if now - since > timedelta(days=1):
            day = since.date()
            while day < now.date():
                signals += scan_day(client, day)
                day += timedelta(days=1)
        return signals

    return scan


# --- Befehlszeile ------------------------------------------------------------------


def _paths(args) -> tuple[Path, Path]:
    db = Path(args.db or os.environ.get("FINANCE_AI_DB", DEFAULT_DB))
    backups = args.backup_dir or os.environ.get("FINANCE_AI_BACKUP_DIR")
    return db, Path(backups) if backups else db.parent / "backups"


def _require_run(conn: sqlite3.Connection, run_id: str) -> TestRun:
    run = get_test_run(conn, run_id)
    if run is None:
        raise SystemExit(f"Testlauf {run_id!r} gibt es nicht. Erst `testlauf-anlegen`.")
    return run


def _create(conn: sqlite3.Connection, args, now: datetime) -> int:
    from finance_ai.experts.insider import EXPERT

    rules = code_rules()
    run = create_test_run(
        conn, args.id, args.name, args.owner, now, load_settings(conn),
        default_portfolios([EXPERT]), code_rules=rules,
    )
    print(f"Testlauf {run.id} angelegt, Start {run.started_at:%Y-%m-%d %H:%M} UTC.")
    print(f"Portfolios: {', '.join(run.portfolio(s) for s in run.portfolios)}")
    print(f"Regeln im Code: {fingerprint(rules)[:12]}. Einstellungen sind eingefroren.")
    return 0


def _run(conn: sqlite3.Connection, args, backup_dir: Path) -> int:
    from finance_ai.config import sec_user_agent
    from finance_ai.data.sec_edgar import EdgarClient
    from finance_ai.decision.agent import yahoo_market_cap

    run = _require_run(conn, args.testlauf)
    result = run_once(
        conn, run, edgar_scan(EdgarClient(sec_user_agent())), CachedPriceSource(conn),
        yahoo_market_cap, backup_dir,
    )
    print(_line(result))
    return 0 if result.ok else 1


def _line(r: OperationRun) -> str:
    scan = "Scan fehlgeschlagen" if r.scan_until is None else f"{r.new_signals} neue Signale"
    parts = [f"{r.started_at:%Y-%m-%d %H:%M} UTC", scan, f"{r.orders} Orders"]
    if r.missing_prices:
        parts.append(f"ohne Kurs: {', '.join(r.missing_prices)}")
    if r.backup:
        parts.append("Backup angelegt")
    if r.error:
        parts.append(f"FEHLER {r.error}")
    return " · ".join(parts)


def main(argv: Sequence[str] | None = None, clock: Clock = lambda: datetime.now(UTC)) -> int:
    parser = argparse.ArgumentParser(prog="python -m finance_ai.betrieb")
    parser.add_argument("--db", help="Datenbank, sonst FINANCE_AI_DB oder data/finance_ai.sqlite")
    parser.add_argument("--backup-dir", help="sonst FINANCE_AI_BACKUP_DIR oder backups/ neben der DB")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("testlauf-anlegen", help="Testlauf mit den aktuellen Regeln einfrieren")
    create.add_argument("--id", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--owner", required=True)
    run = sub.add_parser("lauf", help="Backup, Scan, Kurse, Entscheidung (stündlich)")
    run.add_argument("--testlauf", required=True)
    log = sub.add_parser("protokoll", help="Die letzten Läufe anzeigen")
    log.add_argument("--testlauf", required=True)
    log.add_argument("--anzahl", type=int, default=20)
    args = parser.parse_args(argv)

    import finance_ai.config  # noqa: F401  lädt die .env, auch FINANCE_AI_BACKUP_DIR

    db, backup_dir = _paths(args)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = storage.connect(db, backup_dir=backup_dir)
    try:
        if args.command == "testlauf-anlegen":
            return _create(conn, args, clock())
        if args.command == "lauf":
            return _run(conn, args, backup_dir)
        _require_run(conn, args.testlauf)
        for entry in list_operation_runs(conn, args.testlauf, args.anzahl):
            print(_line(entry))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
