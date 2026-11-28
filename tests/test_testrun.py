import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from finance_ai.core import insider_history, storage
from finance_ai.core.settings import Settings, save_settings
from finance_ai.core.testrun import (
    PortfolioSpec,
    create_test_run,
    default_portfolios,
    end_test_run,
    get_test_run,
    list_test_runs,
)
from finance_ai.decision import regelwerk
from finance_ai.decision.regelwerk import CodeRulesChangedError, code_rules
from finance_ai.experts import insider
from finance_ai.decision.run import run_decisions, run_test_run
from test_decision import PRICES, RULES, T0, sig

START = T0 - timedelta(hours=2)
SETTINGS = Settings(rules=RULES)


@pytest.fixture
def conn():
    connection = storage.connect()
    yield connection
    connection.close()


def make_run(conn, portfolios=None, id="insider-91d", settings=SETTINGS):
    return create_test_run(
        conn,
        id=id,
        name="Insider, 91 Tage",
        owner="zaole05-stack",
        started_at=START,
        settings=settings,
        portfolios=portfolios or default_portfolios(["insider", "politik"]),
        code_rules=code_rules(),
    )


def test_run_roundtrip(conn):
    specs = default_portfolios(["politik", "insider"]) + (
        PortfolioSpec("beobachtung", experts=frozenset({"insider"}), counts_for_verdict=False),
    )
    run = make_run(conn, specs)

    loaded = get_test_run(conn, run.id)
    assert loaded == run
    assert loaded.settings.test_start == START
    assert [s.key for s in loaded.portfolios] == [
        "main", "shadow:insider", "shadow:politik", "kontrolle:routine", "beobachtung"
    ]
    assert loaded.portfolio(loaded.portfolios[1]) == "insider-91d/shadow:insider"
    assert list_test_runs(conn) == [run]


def test_settings_are_frozen_against_later_changes(conn):
    run = make_run(conn)
    save_settings(conn, Settings(rules=replace(RULES, max_positions=7)))
    assert get_test_run(conn, run.id).settings.rules == RULES


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE test_runs SET settings = '{}'",
        "UPDATE test_runs SET started_at = '2000-01-01T00:00:00.000000+00:00'",
        "UPDATE test_runs SET name = 'anders'",
        "UPDATE test_runs SET code_rules = '{}'",
        "DELETE FROM test_runs",
        "UPDATE run_portfolios SET experts = NULL",
        "UPDATE run_portfolios SET counts_for_verdict = 0",
        "DELETE FROM run_portfolios",
    ],
)
def test_database_refuses_changes_to_frozen_run(conn, sql):
    make_run(conn)
    with pytest.raises(sqlite3.IntegrityError, match="nicht gelöscht|eingefroren"):
        with conn:
            conn.execute(sql)


def test_portfolio_cannot_be_added_after_first_decision(conn):
    run = make_run(conn)
    storage.save_signal(conn, sig("AAA"))
    run_test_run(conn, run, T0, PRICES)
    with pytest.raises(sqlite3.IntegrityError, match="schon Entscheidungen"):
        with conn:
            conn.execute(
                "INSERT INTO run_portfolios (portfolio, run_id, key, counts_for_verdict, position) "
                "VALUES ('insider-91d/neu', 'insider-91d', 'neu', 1, 9)"
            )


def test_portfolios_get_only_their_experts(conn):
    run = make_run(conn)
    storage.save_new_signals(conn, [sig("AAA", "insider"), sig("BBB", "politik")])

    decisions = run_test_run(conn, run, T0, PRICES)

    by_portfolio = {d.portfolio: sorted(d.signals) for d in decisions}
    assert by_portfolio == {
        "insider-91d/main": ["insider:AAA:0", "politik:BBB:0"],
        "insider-91d/shadow:insider": ["insider:AAA:0"],
        "insider-91d/shadow:politik": ["politik:BBB:0"],
        "insider-91d/kontrolle:routine": ["insider:AAA:0"],
    }


def test_run_uses_frozen_rules_not_current_settings(conn):
    run = make_run(conn, settings=Settings(rules=replace(RULES, max_positions=1)))
    storage.save_new_signals(conn, [sig("AAA"), sig("BBB")])

    (main, *_) = run_test_run(conn, run, T0, PRICES)
    assert len(main.orders) == 1


def test_signals_before_start_are_not_part_of_the_run(conn):
    early = replace(sig("AAA"), created_at=START - timedelta(minutes=1), id="insider:AAA:frueh")
    storage.save_new_signals(conn, [early, sig("BBB")])
    run = make_run(conn)

    (main, *_) = run_test_run(conn, run, T0, PRICES)
    assert list(main.signals) == ["insider:BBB:0"]


def test_legacy_and_run_portfolios_do_not_mix(conn):
    run = make_run(conn)
    storage.save_signal(conn, sig("AAA"))
    run_decisions(conn, T0, PRICES, ["insider"], RULES)
    (main, *_) = run_test_run(conn, run, T0, PRICES)
    assert list(main.signals) == ["insider:AAA:0"]
    assert len(storage.list_orders(conn, "main")) == 1
    assert len(storage.list_orders(conn, "insider-91d/main")) == 1


def test_run_refuses_time_before_start(conn):
    run = make_run(conn)
    with pytest.raises(ValueError, match="beginnt erst"):
        run_test_run(conn, run, START - timedelta(seconds=1), PRICES)


def test_ended_run_takes_no_more_decisions(conn):
    run = make_run(conn)
    ended = end_test_run(conn, run.id, T0)
    assert ended.ended_at == T0

    storage.save_signal(conn, sig("AAA"))
    with pytest.raises(ValueError, match="beendet"):
        run_test_run(conn, ended, T0 + timedelta(hours=1), PRICES)
    # Auch mit einem veralteten Objekt lehnt die Datenbank ab.
    with pytest.raises(sqlite3.IntegrityError, match="außerhalb"):
        run_test_run(conn, run, T0 + timedelta(hours=1), PRICES)
    assert storage.list_orders(conn, "insider-91d/main") == []


def test_run_ends_only_once_and_not_before_its_decisions(conn):
    run = make_run(conn)
    storage.save_signal(conn, sig("AAA"))
    run_test_run(conn, run, T0, PRICES)

    with pytest.raises(sqlite3.IntegrityError, match="vor einer Entscheidung"):
        end_test_run(conn, run.id, T0)
    end_test_run(conn, run.id, T0 + timedelta(days=1))
    with pytest.raises(sqlite3.IntegrityError, match="schon beendet"):
        end_test_run(conn, run.id, T0 + timedelta(days=2))


def test_end_unknown_run(conn):
    with pytest.raises(KeyError):
        end_test_run(conn, "gibt-es-nicht", T0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "Mit Leerzeichen"},
        {"id": "a/b"},
        {"portfolios": ()},
        {"portfolios": (PortfolioSpec("main"), PortfolioSpec("main"))},
        {"portfolios": (PortfolioSpec("beob", counts_for_verdict=False),)},
    ],
)
def test_invalid_runs_are_rejected(conn, kwargs):
    args = dict(
        id="ok", name="x", owner="y", started_at=START, settings=SETTINGS,
        portfolios=default_portfolios(["insider"]), code_rules={},
    )
    args.update(kwargs)
    with pytest.raises(ValueError):
        create_test_run(conn, **args)
    assert list_test_runs(conn) == []


@pytest.mark.parametrize("key", ["a/b", "Main", ""])
def test_invalid_portfolio_keys(key):
    with pytest.raises(ValueError):
        PortfolioSpec(key)


def test_empty_expert_set_is_rejected():
    with pytest.raises(ValueError):
        PortfolioSpec("x", experts=frozenset())


def test_run_ids_are_unique(conn):
    make_run(conn)
    with pytest.raises(sqlite3.IntegrityError):
        make_run(conn)


def test_start_cash_is_frozen_too(conn):
    run = make_run(conn, settings=Settings(rules=replace(RULES, start_cash=D("5000"))))
    assert get_test_run(conn, run.id).settings.rules.start_cash == D("5000")


def test_code_rules_are_frozen_with_the_run(conn):
    run = make_run(conn)
    assert json.loads(get_test_run(conn, run.id).code_rules) == code_rules()


def test_run_refuses_when_rules_in_code_changed(conn, monkeypatch):
    run = make_run(conn)
    storage.save_signal(conn, sig("AAA"))
    monkeypatch.setattr(insider, "DEFAULT_MIN_VALUE", D("50000"))
    monkeypatch.setattr(insider_history, "ROUTINE_YEARS", 2)
    with pytest.raises(CodeRulesChangedError, match="Insider.Mindestbetrag, Routine.Vorjahre"):
        run_test_run(conn, run, T0, PRICES)
    assert storage.list_orders(conn) == []


def test_run_from_before_code_rules_takes_no_decisions(conn):
    run = make_run(conn)
    old = replace(run, code_rules="{}")
    with pytest.raises(CodeRulesChangedError, match="Insider.Mindestbetrag"):
        run_test_run(conn, old, T0, PRICES)


def test_fingerprint_ignores_key_order():
    rules = code_rules()
    reordered = dict(reversed(list(rules.items())))
    assert regelwerk.fingerprint(reordered) == regelwerk.fingerprint(rules)
    assert regelwerk.fingerprint({**rules, "Routine": {}}) != regelwerk.fingerprint(rules)


def test_run_with_market_cap_limit_needs_a_lookup(conn):
    limited = Settings(rules=replace(RULES, max_market_cap=D("2000000000")))
    run = make_run(conn, settings=limited)
    storage.save_signal(conn, sig("AAA"))
    with pytest.raises(ValueError, match="Börsenwert-Abfrage"):
        run_test_run(conn, run, T0, PRICES)
    (main, *_) = run_test_run(conn, run, T0, PRICES, market_cap=lambda _: D("3000000000"))
    assert main.orders == []
