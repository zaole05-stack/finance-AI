from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from finance_ai.core import storage
from finance_ai.core.insider_history import (
    InsiderTrade,
    classify_owner,
    classify_trade_pattern,
    owner_trades,
    save_trades,
)
from finance_ai.core.models import OPPORTUNISTIC, ROUTINE, UNCLASSIFIED


@pytest.fixture
def conn():
    connection = storage.connect()
    yield connection
    connection.close()


def trade(day, owner="0001234", code="P", line=0, filed=None, accession=None):
    filed = filed or datetime(day.year, day.month, day.day, 21, tzinfo=UTC) + timedelta(days=2)
    return InsiderTrade(
        accession=accession or f"0000-{day.isoformat()}-{owner}",
        line=line,
        owner_cik=owner,
        issuer_cik="0000320193",
        ticker="ABCD",
        code=code,
        acquired=code == "P",
        shares=D("100"),
        price=D("12.5"),
        trade_date=day,
        filed_at=filed,
    )


NOW = datetime(2026, 11, 26, tzinfo=UTC)
NOVEMBER = date(2026, 11, 20)


def every_year(month, years=(2023, 2024, 2025), code="P"):
    return [trade(date(y, month, 10), code=code) for y in years]


def test_same_month_every_year_is_routine():
    assert classify_trade_pattern(every_year(11), NOVEMBER) == ROUTINE


def test_sales_count_as_trading_history():
    assert classify_trade_pattern(every_year(11, code="S"), NOVEMBER) == ROUTINE


def test_other_month_is_opportunistic():
    assert classify_trade_pattern(every_year(3), NOVEMBER) == OPPORTUNISTIC


def test_month_missing_in_one_year_is_opportunistic():
    history = every_year(11, (2023, 2025)) + [trade(date(2024, 3, 1))]
    assert classify_trade_pattern(history, NOVEMBER) == OPPORTUNISTIC


def test_gap_year_is_unclassified():
    assert classify_trade_pattern(every_year(11, (2023, 2025)), NOVEMBER) == UNCLASSIFIED


def test_first_buy_is_unclassified():
    assert classify_trade_pattern([], NOVEMBER) == UNCLASSIFIED


def test_same_year_and_older_years_do_not_count():
    history = every_year(11, (2019, 2020, 2021)) + [trade(date(2026, 11, 1))]
    assert classify_trade_pattern(history, NOVEMBER) == UNCLASSIFIED


def test_other_transaction_codes_are_ignored():
    # z. B. A = Zuteilung aus Vergütung, kein Handel am Markt
    assert classify_trade_pattern(every_year(11, code="A"), NOVEMBER) == UNCLASSIFIED


def test_years_parameter():
    assert classify_trade_pattern(every_year(11, (2025,)), NOVEMBER, years=1) == ROUTINE
    with pytest.raises(ValueError):
        classify_trade_pattern([], NOVEMBER, years=0)


def test_roundtrip_and_duplicates_are_ignored(conn):
    trades = every_year(11)
    assert save_trades(conn, trades) == 3
    assert save_trades(conn, trades) == 0
    assert owner_trades(conn, "1234", NOW) == trades


def test_cik_with_or_without_leading_zeros_is_the_same_person(conn):
    save_trades(conn, [trade(date(2025, 1, 2), owner="0001234")])
    assert len(owner_trades(conn, "1234", NOW)) == 1
    assert len(owner_trades(conn, "0001234", NOW)) == 1


def test_no_look_ahead_late_filing_is_not_known_yet(conn):
    late = trade(date(2025, 11, 10), filed=datetime(2026, 12, 1, tzinfo=UTC))
    save_trades(conn, every_year(11, (2023, 2024)) + [late])

    assert classify_owner(conn, "1234", NOVEMBER, known_at=NOW) == UNCLASSIFIED
    assert classify_owner(conn, "1234", NOVEMBER, known_at=datetime(2026, 12, 2, tzinfo=UTC)) == ROUTINE


def test_other_people_do_not_count(conn):
    save_trades(conn, [trade(date(y, 11, 10), owner="999") for y in (2023, 2024, 2025)])
    assert classify_owner(conn, "1234", NOVEMBER, known_at=NOW) == UNCLASSIFIED


def test_joint_filing_is_stored_per_person(conn):
    day = date(2025, 11, 10)
    shared = "0000-gemeinsam"
    assert save_trades(conn, [trade(day, "1", accession=shared), trade(day, "2", accession=shared)]) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"owner_cik": "Max Mustermann"},
        {"owner_cik": ""},
        {"line": -1},
        {"filed_at": datetime(2025, 1, 1)},
        {"trade_date": date(2025, 1, 5), "filed_at": datetime(2025, 1, 1, tzinfo=UTC)},
    ],
)
def test_invalid_trades(kwargs):
    base = dict(
        accession="a", line=0, owner_cik="1", issuer_cik="2", ticker=None, code="P",
        acquired=True, shares=D("1"), price=D("1"), trade_date=date(2025, 1, 1),
        filed_at=datetime(2025, 1, 2, tzinfo=UTC),
    )
    base.update(kwargs)
    with pytest.raises(ValueError):
        InsiderTrade(**base)
