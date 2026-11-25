import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_ai.core import storage
from finance_ai.core.models import MAIN_PORTFOLIO, Order, Position, Side, Signal

T0 = datetime(2026, 11, 25, 14, 30, tzinfo=UTC)


@pytest.fixture
def conn():
    connection = storage.connect()
    yield connection
    connection.close()


def make_signal(expert="insider", minutes=0) -> Signal:
    return Signal(
        expert=expert,
        ticker="ABCD",
        side=Side.BUY,
        source_url="https://www.sec.gov/x",
        summary="CEO kauft",
        observed_at=T0,
        created_at=T0 + timedelta(minutes=minutes),
        confidence=0.7,
    )


def test_signal_roundtrip_keeps_instant_across_timezones(conn):
    cet = timezone(timedelta(hours=1))
    signal = Signal(
        expert="insider",
        ticker="ABCD",
        side=Side.BUY,
        source_url="https://www.sec.gov/x",
        summary="CEO kauft",
        observed_at=T0.astimezone(cet),
        created_at=T0 + timedelta(microseconds=1),
    )
    storage.save_signal(conn, signal)
    assert storage.get_signal(conn, signal.id) == signal


def test_get_missing_returns_none(conn):
    assert storage.get_signal(conn, "fehlt") is None
    assert storage.get_order(conn, "fehlt") is None


def test_list_signals_sorted_and_filtered(conn):
    late = make_signal(minutes=10)
    early = make_signal(minutes=0)
    other = make_signal(expert="politics", minutes=5)
    for signal in (late, early, other):
        storage.save_signal(conn, signal)
    assert storage.list_signals(conn) == [early, other, late]
    assert storage.list_signals(conn, expert="insider") == [early, late]


def test_list_signals_sorts_by_instant_across_timezones(conn):
    # Gespeichert wird in UTC: 15:00 MEZ (= 14:00 UTC) liegt vor 14:30 UTC.
    cet = timezone(timedelta(hours=1))
    utc_signal = make_signal(minutes=0)
    cet_signal = Signal(
        expert="insider",
        ticker="ABCD",
        side=Side.BUY,
        source_url="https://www.sec.gov/x",
        summary="CEO kauft",
        observed_at=T0 - timedelta(hours=1),
        created_at=(T0 - timedelta(minutes=30)).astimezone(cet),
    )
    storage.save_signal(conn, utc_signal)
    storage.save_signal(conn, cet_signal)
    assert storage.list_signals(conn) == [cet_signal, utc_signal]


def test_order_roundtrip_keeps_signal_order_and_decimal(conn):
    first, second = make_signal(), make_signal(expert="funds")
    storage.save_signal(conn, first)
    storage.save_signal(conn, second)
    order = Order(
        portfolio=MAIN_PORTFOLIO,
        ticker="ABCD",
        side=Side.BUY,
        quantity=Decimal("0.1"),
        created_at=T0,
        signal_ids=(second.id, first.id),
        rationale="Insider und Fonds kaufen",
    )
    storage.save_order(conn, order)
    loaded = storage.get_order(conn, order.id)
    assert loaded == order
    assert loaded.quantity == Decimal("0.1")


def test_order_with_unknown_signal_is_rejected_completely(conn):
    order = Order(
        portfolio=MAIN_PORTFOLIO,
        ticker="ABCD",
        side=Side.BUY,
        quantity=Decimal("1"),
        created_at=T0,
        signal_ids=("gibt-es-nicht",),
        rationale="x",
    )
    with pytest.raises(sqlite3.IntegrityError):
        storage.save_order(conn, order)
    # Transaktion zurückgerollt: keine halbe Order in der Datenbank.
    assert storage.get_order(conn, order.id) is None


def test_duplicate_signal_id_is_rejected(conn):
    signal = make_signal()
    storage.save_signal(conn, signal)
    with pytest.raises(sqlite3.IntegrityError):
        storage.save_signal(conn, signal)


def test_positions_upsert_list_and_delete(conn):
    storage.save_position(conn, Position("main", "ZZZ", Decimal("1"), Decimal("5")))
    storage.save_position(conn, Position("main", "AAA", Decimal("2"), Decimal("10")))
    storage.save_position(conn, Position("main", "AAA", Decimal("3"), Decimal("11.5")))
    storage.save_position(conn, Position("shadow:insider", "AAA", Decimal("9"), Decimal("1")))

    assert storage.get_positions(conn, "main") == [
        Position("main", "AAA", Decimal("3"), Decimal("11.5")),
        Position("main", "ZZZ", Decimal("1"), Decimal("5")),
    ]

    storage.delete_position(conn, "main", "aaa")
    assert [p.ticker for p in storage.get_positions(conn, "main")] == ["ZZZ"]
    assert len(storage.get_positions(conn, "shadow:insider")) == 1


def test_file_database_persists(tmp_path):
    path = tmp_path / "finance.sqlite"
    signal = make_signal()
    conn = storage.connect(path)
    storage.save_signal(conn, signal)
    conn.close()

    reopened = storage.connect(path)
    assert storage.get_signal(reopened, signal.id) == signal
    reopened.close()
