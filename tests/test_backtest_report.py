"""Tests für den Bericht docs/BACKTEST.md (Plan-Schritt 8). Nur ausgedachte Zahlen."""

import copy
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from test_backtest_runs import regelwerk
from test_measure import bsignal, series

from finance_ai.evaluation import backtest_report as report
from finance_ai.evaluation import backtest_runs as runs
from finance_ai.evaluation.backtest import Section
from finance_ai.paper_trading.prices import StaticPriceSource

NOW = datetime(2027, 1, 15, tzinfo=UTC)


@pytest.fixture(scope="module")
def result():
    prices = StaticPriceSource({
        "ABC": series(date(2015, 2, 2), date(2015, 10, 30), lambda d: "10" if d < date(2015, 6, 8) else "12"),
        "IWM": series(date(2015, 2, 2), date(2015, 10, 30), "100"),
        "IWC": series(date(2015, 2, 2), date(2015, 10, 30), "50"),
    })
    starts = {Section.STRESS: [], Section.VERDICT: [date(2015, 3, 1)]}
    return runs.compute([bsignal()], prices, regelwerk(), starts=starts, draws=50)


def entries(result, *reasons):
    conn = sqlite3.connect(":memory:")
    for i, reason in enumerate((None, *reasons)):
        runs.run(conn, regelwerk(), reason, lambda: result, NOW + timedelta(days=i))
    return runs.list_runs(conn)


def test_yahoo_note_comes_first(result):
    text = report.markdown(entries(result))
    first_lines = [line for line in text.splitlines() if line.strip()][:3]
    assert any(runs.YAHOO_NOTE in line for line in first_lines)


def test_report_has_every_section_from_the_plan(result):
    text = report.markdown(entries(result))
    for heading in (
        "Messbare Signale", "Messbar und weggefallen", "Regelwerk", "Urteil",
        "Drei Stufen", "Stresstest Finanzkrise", "Hälften", "Doppelte Slippage",
        "Alle Läufe", "Bekannte Lücken",
    ):
        assert f"## {heading}" in text, heading
    assert "ohne Börsenwert-Grenze" in text
    assert runs.fingerprint(regelwerk()) in text
    for gap in ("10b5-1", "SIC", "Yahoo"):
        assert gap in text.split("## Bekannte Lücken")[1]


def test_all_runs_are_listed_with_reason(result):
    text = report.markdown(entries(result, "Fehler im Bootstrap, Test test_x"))
    runs_part = text.split("## Alle Läufe")[1]
    assert "Fehler im Bootstrap, Test test_x" in runs_part
    assert "2027-01-15" in runs_part and "2027-01-16" in runs_part
    assert "Erstlauf" in runs_part


def test_latest_run_is_reported(result):
    other = runs.RunResult(runs.BacktestVerdict.FAILED, result.details)
    conn = sqlite3.connect(":memory:")
    runs.run(conn, regelwerk(), None, lambda: result, NOW)
    runs.run(conn, regelwerk(), "Fehler Y", lambda: other, NOW + timedelta(days=1))
    text = report.markdown(runs.list_runs(conn))
    assert "**durchgefallen**" in text.split("## Urteil")[1].split("##")[0]


def test_worst_case_warning_on_top_only_if_verdict_flips(result):
    plain = report.markdown(entries(result))
    assert "Warnung" not in plain.split("## ")[0]
    details = copy.deepcopy(result.details)
    details["Urteil je Stufe"]["schlimmster Fall"] = "durchgefallen"
    flipped = replace(result, verdict=runs.BacktestVerdict.PASSED, details=details)
    text = report.markdown(entries(flipped))
    assert "Warnung" in text.split("## ")[0]


def test_numbers_are_shown_as_percentage_points(result):
    text = report.markdown(entries(result))
    assert "Pp" in text and "%" in text


def test_without_runs_the_report_says_how_to_start():
    text = report.markdown([])
    assert "python -m finance_ai.evaluation.backtest run" in text


def test_report_command_writes_file_from_stored_runs(tmp_path, result):
    db = tmp_path / "backtest.sqlite"
    conn = sqlite3.connect(db)
    runs.run(conn, regelwerk(), None, lambda: result, NOW)
    conn.close()
    out = tmp_path / "BACKTEST.md"
    runs.main(["report", "--data", str(tmp_path), "--out", str(out)])
    assert runs.YAHOO_NOTE in out.read_text(encoding="utf-8")


def test_empty_parts_show_a_dash_not_zero(result):
    stress = report.markdown(entries(result)).split("## Stresstest Finanzkrise")[1].split("##")[0]
    assert "+0,0 Pp" not in stress and "–" in stress
