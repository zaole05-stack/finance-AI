import sqlite3
from datetime import UTC, datetime

import pytest

from finance_ai.core import storage
from finance_ai.core.backup import latest_backup_time
from finance_ai.core.settings import Settings, load_settings, save_settings
from test_storage import make_signal

NOW = datetime(2026, 11, 26, 6, 0, tzinfo=UTC)

# Schema der Signal-Tabelle vor Einführung der Migrationen, wie es in
# bestehenden Dateien wie data/demo.sqlite steht (user_version 0).
LEGACY_SIGNALS = """
CREATE TABLE signals (
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
"""


def legacy_db(path, signal):
    raw = sqlite3.connect(path)
    raw.executescript(LEGACY_SIGNALS)
    with raw:
        raw.execute(
            "INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", storage._signal_row(signal)[:9]
        )
    raw.close()


def test_new_database_gets_latest_version():
    conn = storage.connect()
    assert storage.schema_version(conn) == len(storage.MIGRATIONS)
    assert not storage.pending_migrations(conn)
    assert load_settings(conn) == Settings()


def test_new_file_database_needs_no_backup(tmp_path):
    storage.connect(tmp_path / "neu.sqlite", now=NOW).close()
    assert not (tmp_path / "backups").exists()


def test_legacy_database_keeps_data_and_is_backed_up_first(tmp_path):
    path = tmp_path / "alt.sqlite"
    signal = make_signal()
    legacy_db(path, signal)

    conn = storage.connect(path, now=NOW)

    assert storage.schema_version(conn) == len(storage.MIGRATIONS)
    assert storage.get_signal(conn, signal.id) == signal
    save_settings(conn, Settings(benchmark_ticker="IWC"))  # Tabelle aus Migration 1
    conn.close()

    # Die Kopie zeigt den Stand vor der Migration und lässt sich wieder öffnen.
    assert latest_backup_time(tmp_path / "backups") == NOW
    (copy,) = (tmp_path / "backups").glob("*-vor_migration.sqlite")
    raw = sqlite3.connect(copy)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    raw.close()
    restored = storage.connect(copy, backup_dir=tmp_path / "andere", now=NOW)
    assert storage.get_signal(restored, signal.id) == signal
    restored.close()


def test_backup_dir_can_be_chosen(tmp_path):
    path = tmp_path / "alt.sqlite"
    legacy_db(path, make_signal())
    storage.connect(path, backup_dir=tmp_path / "onedrive", now=NOW).close()
    assert latest_backup_time(tmp_path / "onedrive") == NOW
    assert not (tmp_path / "backups").exists()


def test_reopening_runs_no_migration_and_no_backup(tmp_path):
    path = tmp_path / "alt.sqlite"
    legacy_db(path, make_signal())
    storage.connect(path, now=NOW).close()
    storage.connect(path, now=datetime(2026, 11, 27, tzinfo=UTC)).close()
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_database_from_newer_program_is_refused(tmp_path):
    path = tmp_path / "neuer.sqlite"
    raw = sqlite3.connect(path)
    raw.execute(f"PRAGMA user_version = {len(storage.MIGRATIONS) + 1}")
    raw.close()
    with pytest.raises(storage.SchemaTooNewError):
        storage.connect(path, now=NOW)


def test_failed_migration_leaves_previous_state(tmp_path, monkeypatch):
    path = tmp_path / "db.sqlite"
    storage.connect(path, now=NOW).close()
    broken = "CREATE TABLE neu (x INTEGER);\nINSERT INTO gibt_es_nicht VALUES (1);"
    monkeypatch.setattr(storage, "MIGRATIONS", storage.MIGRATIONS + (broken,))

    with pytest.raises(sqlite3.OperationalError):
        storage.connect(path, now=NOW)

    monkeypatch.undo()
    conn = storage.connect(path, now=NOW)
    assert storage.schema_version(conn) == len(storage.MIGRATIONS)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'neu'").fetchone() is None
    conn.close()
    # Vor dem Versuch wurde gesichert, danach nicht erneut.
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_new_migration_runs_once_on_existing_data(tmp_path, monkeypatch):
    path = tmp_path / "db.sqlite"
    signal = make_signal()
    conn = storage.connect(path, now=NOW)
    storage.save_signal(conn, signal)
    conn.close()
    monkeypatch.setattr(
        storage, "MIGRATIONS", storage.MIGRATIONS + ("ALTER TABLE signals ADD COLUMN extra TEXT;",)
    )

    conn = storage.connect(path, now=NOW)
    assert storage.schema_version(conn) == len(storage.MIGRATIONS)
    assert conn.execute("SELECT extra FROM signals WHERE id = ?", (signal.id,)).fetchone()[0] is None
    conn.close()
    storage.connect(path, now=NOW).close()  # zweites Öffnen: ALTER läuft nicht erneut
