"""Sicherungskopien der SQLite-Datenbank.

Kopiert wird über die Backup-Funktion von SQLite, nicht durch Kopieren der
Datei. So entsteht auch während eines laufenden Schreibvorgangs eine
vollständige, in sich stimmige Kopie.

Die laufende Datenbank bleibt lokal. Nur die Kopien gehören in einen
synchronisierten Ordner wie OneDrive (siehe docs/BEREICH-A.md, Beschluss 8).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

PREFIX = "finance_ai"
_STAMP = "%Y%m%dT%H%M%SZ"
_NAME = re.compile(rf"^{PREFIX}-(\d{{8}}T\d{{6}}Z)-[a-z0-9_]+\.sqlite$")


class BackupError(RuntimeError):
    """Die Kopie ist entstanden, besteht aber die Prüfung nicht."""


def backup(conn: sqlite3.Connection, target_dir: str | Path, label: str, now: datetime) -> Path:
    """Schreibt eine geprüfte Kopie nach `target_dir` und gibt ihren Pfad zurück.

    Der Dateiname enthält Zeitpunkt (UTC) und Anlass, z. B.
    `finance_ai-20261126T060000Z-taeglich.sqlite`.
    """
    if now.utcoffset() is None:
        raise ValueError("now braucht eine Zeitzone")
    if not re.fullmatch(r"[a-z0-9_]+", label):
        raise ValueError("label darf nur aus a-z, 0-9 und _ bestehen")
    if conn.in_transaction:
        # Sonst wartet die Kopie auf die Sperre der eigenen Verbindung und
        # hängt für immer.
        raise RuntimeError("Backup nicht während einer offenen Transaktion")
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{PREFIX}-{now.astimezone(UTC):{_STAMP}}-{label}.sqlite"
    if path.exists():
        raise FileExistsError(path)
    partial = path.with_suffix(".partial")
    dest = sqlite3.connect(partial)
    try:
        conn.backup(dest)
        result = dest.execute("PRAGMA quick_check").fetchone()[0]
    except BaseException:
        dest.close()
        partial.unlink(missing_ok=True)
        raise
    dest.close()
    if result != "ok":
        partial.unlink(missing_ok=True)
        raise BackupError(f"Kopie fehlerhaft: {result}")
    # Erst die fertige Kopie bekommt den endgültigen Namen. Eine abgebrochene
    # Kopie wird so nie für ein gültiges Backup gehalten.
    partial.rename(path)
    return path


def latest_backup_time(target_dir: str | Path) -> datetime | None:
    """Zeitpunkt der jüngsten Kopie laut Dateiname, oder None."""
    target = Path(target_dir)
    if not target.is_dir():
        return None
    stamps = [
        datetime.strptime(m.group(1), _STAMP).replace(tzinfo=UTC)
        for p in target.iterdir()
        if (m := _NAME.match(p.name))
    ]
    return max(stamps, default=None)


def backup_if_due(
    conn: sqlite3.Connection,
    target_dir: str | Path,
    now: datetime,
    every: timedelta = timedelta(days=1),
) -> Path | None:
    """Tägliche Kopie: nur wenn die jüngste Kopie älter als `every` ist.

    Maßgeblich ist der Zeitpunkt im Dateinamen, nicht das Änderungsdatum der
    Datei. Synchronisierende Ordner wie OneDrive setzen das Änderungsdatum
    beim Herunterladen neu.
    """
    last = latest_backup_time(target_dir)
    if last is not None and now - last < every:
        return None
    return backup(conn, target_dir, "taeglich", now)
