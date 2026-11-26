from dataclasses import replace

import pytest

from finance_ai.core import storage
from finance_ai.core.models import OPPORTUNISTIC, ROUTINE, TAGS, TOP_EXECUTIVE, UNCLASSIFIED
from finance_ai.core.settings import Settings
from finance_ai.core.testrun import (
    ROUTINE_CONTROL,
    PortfolioSpec,
    create_test_run,
    default_portfolios,
    get_test_run,
)
from finance_ai.decision.run import run_decisions, run_test_run
from test_decision import PRICES, RULES, T0, sig
from test_testrun import START


@pytest.fixture
def conn():
    connection = storage.connect()
    yield connection
    connection.close()


def tagged(ticker, *tags, expert="insider"):
    return replace(sig(ticker, expert), tags=frozenset(tags))


def reasons(conn, portfolio):
    return {row["signal_id"]: row["reason"] for row in storage.list_decisions(conn, portfolio)}


def test_tags_roundtrip_through_database(conn):
    signal = tagged("AAA", TOP_EXECUTIVE, OPPORTUNISTIC)
    storage.save_signal(conn, signal)
    assert storage.get_signal(conn, signal.id).tags == {TOP_EXECUTIVE, OPPORTUNISTIC}
    assert storage.get_signal(conn, signal.id) == signal


def test_signal_without_tags_has_empty_set():
    assert sig("AAA").tags == frozenset()


def test_unknown_tag_is_an_error():
    with pytest.raises(ValueError, match="Unbekannte Tags: ceo"):
        tagged("AAA", "ceo")


def test_single_string_is_not_split_into_letters():
    with pytest.raises(TypeError):
        replace(sig("AAA"), tags="routine")


def test_only_one_trade_pattern_per_signal():
    with pytest.raises(ValueError, match="Höchstens ein Tag"):
        tagged("AAA", ROUTINE, OPPORTUNISTIC)


def test_known_tags():
    assert TAGS == {TOP_EXECUTIVE, ROUTINE, OPPORTUNISTIC, UNCLASSIFIED}


def test_routine_is_rejected_with_reason_in_legacy_run(conn):
    storage.save_new_signals(conn, [tagged("AAA", ROUTINE), tagged("BBB", UNCLASSIFIED)])

    (main, shadow) = run_decisions(conn, T0, PRICES, ["insider"], RULES)

    assert [o.ticker for o in main.orders] == ["BBB"]
    assert reasons(conn, "main")["insider:AAA:0"] == "Tag-Filter: routine ausgeschlossen"
    assert reasons(conn, "shadow:insider")["insider:AAA:0"] == "Tag-Filter: routine ausgeschlossen"
    assert "insider:AAA:0" in main.signals  # auch im Briefing sichtbar


def test_portfolios_of_decision_17(conn):
    run = create_test_run(
        conn, "r", "Routine-Filter", "zaole05-stack", START, Settings(rules=RULES),
        default_portfolios(["insider", "politik"]),
    )
    storage.save_new_signals(
        conn,
        [
            tagged("AAA", ROUTINE),
            tagged("BBB", OPPORTUNISTIC),
            tagged("CCC", UNCLASSIFIED),
            tagged("AAA", expert="politik"),
        ],
    )

    decisions = {d.portfolio: d for d in run_test_run(conn, run, T0, PRICES)}

    bought = {p: sorted(o.ticker for o in d.orders) for p, d in decisions.items()}
    assert bought == {
        "r/main": ["AAA", "BBB"],  # AAA nur wegen des Politik-Signals
        "r/shadow:insider": ["BBB", "CCC"],
        "r/shadow:politik": ["AAA"],
        "r/kontrolle:routine": ["AAA"],
    }
    # Jedes Insider-Signal ist in jedem Insider-Portfolio entschieden, nichts fällt still weg.
    for portfolio in ["r/main", "r/shadow:insider", "r/kontrolle:routine"]:
        assert {"insider:AAA:0", "insider:BBB:0", "insider:CCC:0"} <= reasons(conn, portfolio).keys()
    assert reasons(conn, "r/kontrolle:routine")["insider:BBB:0"] == "Tag-Filter: braucht routine"
    control = next(s for s in get_test_run(conn, "r").portfolios if s.key == ROUTINE_CONTROL)
    assert not control.counts_for_verdict


def test_control_portfolio_only_with_insider():
    keys = [s.key for s in default_portfolios(["politik"])]
    assert keys == ["main", "shadow:politik"]


def test_tag_filters_are_frozen_with_the_run(conn):
    spec = PortfolioSpec("x", include_tags={OPPORTUNISTIC}, exclude_tags={TOP_EXECUTIVE})
    create_test_run(conn, "r", "n", "o", START, Settings(rules=RULES), [spec])
    assert get_test_run(conn, "r").portfolios == (spec,)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"include_tags": {"gibt_es_nicht"}},
        {"exclude_tags": {"gibt_es_nicht"}},
        {"include_tags": set()},
        {"include_tags": {ROUTINE}, "exclude_tags": {ROUTINE}},
    ],
)
def test_invalid_tag_filters(kwargs):
    with pytest.raises(ValueError):
        PortfolioSpec("x", **kwargs)
