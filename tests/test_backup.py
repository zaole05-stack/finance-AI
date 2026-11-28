from datetime import UTC, datetime, timedelta

import pytest

from finance_ai.core import storage
from finance_ai.core.backup import backup, backup_if_due, latest_backup_time
from test_storage import make_signal

NOW = datetime(2026, 11, 26, 6, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = storage.connect(tmp_path / "live.sqlite", now=NOW)
    yield connection
    connection.close()


def test_backup_can_be_restored(conn, tmp_path):
    signal = make_signal()
    storage.save_signal(conn, signal)

    path = backup(conn, tmp_path / "onedrive", "taeglich", NOW)

    assert path.name == "finance_ai-20261126T060000Z-taeglich.sqlite"
    assert not list((tmp_path / "onedrive").glob("*.partial"))
    restored = storage.connect(path, now=NOW)
    assert storage.list_signals(restored) == [signal]
    assert storage.schema_version(restored) == storage.schema_version(conn)
    restored.close()


def test_backup_refuses_open_transaction_instead_of_hanging(conn, tmp_path):
    conn.execute("INSERT INTO settings VALUES ('offen', 'x')")  # Transaktion offen
    with pytest.raises(RuntimeError):
        backup(conn, tmp_path, "test", NOW)
    conn.rollback()
    assert not list(tmp_path.glob("finance_ai-*"))


def test_backup_never_overwrites(conn, tmp_path):
    backup(conn, tmp_path, "test", NOW)
    with pytest.raises(FileExistsError):
        backup(conn, tmp_path, "test", NOW)


def test_backup_time_is_stored_in_utc(conn, tmp_path):
    berlin = NOW.astimezone(datetime.now().astimezone().tzinfo)
    backup(conn, tmp_path, "test", berlin)
    assert latest_backup_time(tmp_path) == NOW


@pytest.mark.parametrize("label", ["", "Täglich", "a b", "../x"])
def test_backup_rejects_bad_labels(conn, tmp_path, label):
    with pytest.raises(ValueError):
        backup(conn, tmp_path, label, NOW)


def test_backup_needs_timezone(conn, tmp_path):
    with pytest.raises(ValueError):
        backup(conn, tmp_path, "test", datetime(2026, 11, 26))


def test_daily_backup_only_when_due(conn, tmp_path):
    target = tmp_path / "onedrive"
    assert latest_backup_time(target) is None

    first = backup_if_due(conn, target, NOW)
    assert first is not None
    assert backup_if_due(conn, target, NOW + timedelta(hours=23)) is None
    second = backup_if_due(conn, target, NOW + timedelta(days=1))
    assert second is not None and second != first
    assert latest_backup_time(target) == NOW + timedelta(days=1)


def test_daily_backup_ignores_foreign_files(conn, tmp_path):
    (tmp_path / "finance_ai-kaputt.sqlite").write_text("x")
    (tmp_path / "notizen.txt").write_text("x")
    assert latest_backup_time(tmp_path) is None
    assert backup_if_due(conn, tmp_path, NOW) is not None
