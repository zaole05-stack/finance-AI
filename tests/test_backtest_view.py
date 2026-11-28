"""Tests für den Dashboard-Tab „Backtest“ (Plan-Schritt 9). Nur ausgedachte Zahlen."""

import sqlite3
from datetime import UTC, datetime, timedelta

from test_backtest_report import entries, result  # noqa: F401  (Fixture)
from test_backtest_runs import regelwerk

from finance_ai.dashboard import backtest_view as bv
from finance_ai.evaluation import backtest_report as report
from finance_ai.evaluation import backtest_runs as runs

NOW = datetime(2027, 1, 15, tzinfo=UTC)


def test_without_file_there_are_no_runs_and_no_file_is_created(tmp_path):
    path = tmp_path / "backtest.sqlite"
    assert bv.load_runs(path) == [] and bv.view([]) is None
    assert not path.exists()
    assert "python -m finance_ai.evaluation.backtest run" in bv.START_COMMAND


def test_empty_file_counts_as_no_run(tmp_path):
    path = tmp_path / "backtest.sqlite"
    sqlite3.connect(path).close()
    assert bv.load_runs(path) == []


def test_reads_stored_runs_read_only(tmp_path, result):
    path = tmp_path / "backtest.sqlite"
    conn = sqlite3.connect(path)
    runs.run(conn, regelwerk(), None, lambda: result, NOW)
    runs.run(conn, regelwerk(), "Fehler X, Test Y", lambda: result, NOW + timedelta(days=1))
    conn.close()
    loaded = bv.load_runs(path)
    assert [e.reason for e in loaded] == [None, "Fehler X, Test Y"]
    v = bv.view(loaded)
    assert [r["Begründung"] for r in v.runs] == ["Erstlauf", "Fehler X, Test Y"]


def test_view_shows_the_same_numbers_as_the_report(result):
    es = entries(result)
    v, text = bv.view(es), report.markdown(es)
    assert v.note == runs.YAHOO_NOTE and v.verdict in text
    assert v.fingerprint in text
    for c in v.criteria:
        assert c in text
    for row in v.tiers + v.halves + v.stress + v.extra + v.coverage + v.classes:
        assert "| " + " | ".join(str(x) for x in row.values()) + " |" in text
    assert {r["Stufe"] for r in v.tiers} == set(result.details["Stufen"])
    assert [r["Teil"] for r in v.halves] == [report.DEC, *report.HALVES]
    assert [r["Teil"] for r in v.stress] == [report.STRESS]


def test_view_has_window_series_and_signals_with_source_and_status(result):
    v = bv.view(entries(result))
    [window] = v.windows["Urteil"]
    assert window["Start"] == "2015-03-01" and isinstance(window["Vorsprung"], float)
    assert v.windows["Stresstest Finanzkrise"] == []
    [signal] = v.signals
    assert signal["Quelle"].startswith("https://www.sec.gov/") and signal["Status"] == "ok"
    assert signal["Vorsprung"] is not None


def test_worst_case_warning_only_if_verdict_flips(result):
    import copy
    from dataclasses import replace

    assert bv.view(entries(result)).warning is None
    details = copy.deepcopy(result.details)
    details["Urteil je Stufe"]["schlimmster Fall"] = "durchgefallen"
    flipped = replace(result, verdict=runs.BacktestVerdict.PASSED, details=details)
    assert "durchgefallen" in bv.view(entries(flipped)).warning
