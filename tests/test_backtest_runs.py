"""Tests für Lauf und Neulauf des Insider-Backtests (Plan-Schritt 7).

Nur feste, ausgedachte Kurse und eine Datenbank im Speicher.
"""

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from finance_ai.core.settings import Settings
from finance_ai.decision.agent import DecisionRules
from finance_ai.evaluation import backtest_runs as runs
from finance_ai.evaluation import measure as m
from finance_ai.evaluation.backtest import Section
from finance_ai.paper_trading.prices import StaticPriceSource
from test_measure import bsignal, series  # pytest legt tests/ in den Suchpfad

NOW = datetime(2027, 1, 15, tzinfo=UTC)


def regelwerk(**changes):
    settings = Settings(rules=DecisionRules(), benchmark_ticker="IWM")
    r = runs.regelwerk_from_settings(settings, runs.WindowRule.FIVE_PP)
    return replace(r, **changes)


def fake_result(verdict=runs.BacktestVerdict.PASSED):
    return runs.RunResult(verdict, {"Urteil": {"Fenster": 1}})


# --- Fingerabdruck -------------------------------------------------------------------


def test_fingerprint_is_stable_and_covers_every_rule():
    base = regelwerk()
    assert runs.fingerprint(base) == runs.fingerprint(regelwerk())
    changed = [
        regelwerk(benchmark="IWC"),
        regelwerk(rules=replace(base.rules, max_positions=12)),
        regelwerk(rules=replace(base.rules, max_market_cap=None)),
        regelwerk(costs=replace(base.costs, slippage_rate=D("0.01"))),
        regelwerk(window_rule=runs.WindowRule.AHEAD),
        regelwerk(min_value=D("50000")),
        regelwerk(end=date(2026, 8, 28)),
    ]
    prints = {runs.fingerprint(r) for r in changed}
    assert runs.fingerprint(base) not in prints
    assert len(prints) == len(changed)


def test_regelwerk_reads_live_settings():
    settings = Settings(benchmark_ticker="IWC", rules=DecisionRules(max_positions=7))
    r = runs.regelwerk_from_settings(settings, runs.WindowRule.AHEAD)
    assert r.benchmark == "IWC" and r.rules.max_positions == 7
    assert r.second_benchmark == "IWM"  # der jeweils andere als Zweitwert


# --- Lauf und Neulauf -------------------------------------------------------------------


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


def test_first_run_is_stored_with_time_fingerprint_and_verdict(conn):
    r = regelwerk()
    runs.run(conn, r, None, lambda: fake_result(), NOW)
    [entry] = runs.list_runs(conn)
    assert entry.at == NOW and entry.fingerprint == runs.fingerprint(r)
    assert entry.reason is None and entry.verdict is runs.BacktestVerdict.PASSED
    assert entry.result == {"Urteil": {"Fenster": 1}}


def test_second_run_without_rerun_is_refused_before_computing(conn):
    runs.run(conn, regelwerk(), None, lambda: fake_result(), NOW)
    calls = []
    with pytest.raises(runs.RunRefused, match="--rerun"):
        runs.run(conn, regelwerk(), None, lambda: calls.append(1) or fake_result(), NOW)
    assert calls == [] and len(runs.list_runs(conn)) == 1


def test_rerun_with_changed_regelwerk_is_refused(conn):
    runs.run(conn, regelwerk(), None, lambda: fake_result(), NOW)
    with pytest.raises(runs.RunRefused, match="Regelwerk"):
        runs.run(conn, regelwerk(min_value=D("50000")), "Fehler in X, Test Y", lambda: fake_result(), NOW)
    assert len(runs.list_runs(conn)) == 1


def test_rerun_with_same_regelwerk_is_listed_with_reason(conn):
    runs.run(conn, regelwerk(), None, lambda: fake_result(), NOW)
    later = NOW + timedelta(days=3)
    runs.run(conn, regelwerk(), "Fehler im Bootstrap, Test test_x", lambda: fake_result(runs.BacktestVerdict.CLOSE), later)
    first, second = runs.list_runs(conn)
    assert second.reason == "Fehler im Bootstrap, Test test_x" and second.at == later
    assert second.verdict is runs.BacktestVerdict.CLOSE


@pytest.mark.parametrize("reason", ["", "   "])
def test_rerun_needs_a_real_reason(conn, reason):
    runs.run(conn, regelwerk(), None, lambda: fake_result(), NOW)
    with pytest.raises(runs.RunRefused):
        runs.run(conn, regelwerk(), reason, lambda: fake_result(), NOW)


# --- Urteil -------------------------------------------------------------------------


def summary(mean, ahead, five):
    return m.Summary(100, D(mean), ahead, five)


@pytest.mark.parametrize(
    ("rule", "windows", "single", "low", "expected"),
    [
        (runs.WindowRule.FIVE_PP, summary("0.06", 0.8, 0.6), D("0.01"), 0.001, runs.BacktestVerdict.PASSED),
        (runs.WindowRule.FIVE_PP, summary("0.06", 0.8, 0.5), D("0.01"), 0.001, runs.BacktestVerdict.CLOSE),
        (runs.WindowRule.AHEAD, summary("0.06", 0.8, 0.5), D("0.01"), 0.001, runs.BacktestVerdict.PASSED),
        (runs.WindowRule.AHEAD, summary("0.04", 0.8, 0.5), D("0.01"), 0.001, runs.BacktestVerdict.CLOSE),
        # Kriterium 1 erfüllt, Kriterium 2 nicht: im Mittel vorn, also knapp.
        (runs.WindowRule.AHEAD, summary("0.06", 0.8, 0.6), D("0.01"), -0.002, runs.BacktestVerdict.CLOSE),
        (runs.WindowRule.AHEAD, summary("0", 0.5, 0.2), D("0.01"), 0.001, runs.BacktestVerdict.FAILED),
        (runs.WindowRule.AHEAD, summary("-0.01", 0.4, 0.2), D("0.01"), 0.001, runs.BacktestVerdict.FAILED),
    ],
)
def test_verdict_follows_the_plan(rule, windows, single, low, expected):
    assert runs.verdict(windows, single, low, rule) is expected


# --- Rechnung im Ganzen -----------------------------------------------------------------


def test_compute_reports_every_tier_and_extra_runs():
    prices = StaticPriceSource({
        "ABC": series(date(2015, 2, 2), date(2015, 10, 30), lambda d: "10" if d < date(2015, 6, 8) else "12"),
        "IWM": series(date(2015, 2, 2), date(2015, 10, 30), "100"),
        "IWC": series(date(2015, 2, 2), date(2015, 10, 30), "50"),
    })
    starts = {Section.STRESS: [], Section.VERDICT: [date(2015, 3, 1)]}
    result = runs.compute([bsignal()], prices, regelwerk(), starts=starts, draws=50)
    tiers = result.details["Stufen"]
    assert set(tiers) == {t.value for t in m.Tier}
    realistic = tiers[m.Tier.REALISTIC.value]["Urteil"]
    assert realistic["Einzelsignale"]["Anzahl"] == 1
    assert realistic["Fenster"]["Anzahl"] == 1
    assert set(result.details["Zusatz"]) == {"doppelte Slippage", "Zweit-ETF IWC"}
    assert result.verdict in runs.BacktestVerdict


def test_command_refuses_second_run_before_loading_any_data(tmp_path):
    from finance_ai.core import storage
    from finance_ai.core.settings import load_settings

    db = tmp_path / "finance_ai.sqlite"
    conn = storage.connect(db)
    r = runs.regelwerk_from_settings(load_settings(conn), runs.WindowRule.FIVE_PP)
    conn.close()
    log = sqlite3.connect(tmp_path / "backtest.sqlite")
    runs.run(log, r, None, lambda: fake_result(), NOW)
    log.close()
    # Ohne Netz und ohne SEC_USER_AGENT: Die Sperre muss vorher greifen.
    with pytest.raises(SystemExit, match="Abgelehnt"):
        runs.main(["run", "--fenster-regel", "5pp", "--data", str(tmp_path), "--db", str(db)])


def test_quarters_cover_the_whole_period():
    q = runs._quarters(regelwerk())
    assert min(q) == "2006q1" and "2026q3" in q and "2026q4" not in q
    assert len(q) == 4 * 20 + 3


def test_coverage_counts_measurable_by_section_and_size_without_returns():
    from finance_ai.data.sec_company import MissingPrice
    from finance_ai.evaluation.backtest import SignalStatus

    gone = replace(bsignal(status=SignalStatus.NO_PRICE, case=MissingPrice.BANKRUPTCY, cap=D("20000000")),
                   later_bankruptcy=True)
    signals = [
        bsignal(cap=D("20000000")),
        gone,
        replace(bsignal(cap=D("1000000000")), later_takeover=True),
        bsignal(cap=D("5000000000")),  # über der Grenze: nicht im Zielsegment
        bsignal(section=Section.STRESS, cap=None),
    ]
    c = runs.coverage(signals, regelwerk())
    assert c["Abschnitte"]["Urteil"] == {"messbar": 3, "ohne Kurs": 1, "Anteil messbar": 0.75}
    assert c["Zielsegment"]["messbar"] == 2 and c["Zielsegment"]["ohne Kurs"] == 1
    assert c["Klassen"]["unter 50 Mio. USD"]["Anteil messbar"] == 0.5
    assert c["Klassen"]["300 Mio. USD bis Grenze"]["messbar"] == 1
    assert c["Vergleich"]["weggefallen"] == {"Anzahl": 1, "später Insolvenz": 1.0, "später Übernahme": 0.0}
    # Zielsegment plus Stresstest: 3 messbare, davon 1 später übernommen.
    assert c["Vergleich"]["messbar"]["später Übernahme"] == 0.3333


def test_compute_stores_window_series_and_every_signal_for_the_dashboard():
    from finance_ai.data.sec_company import MissingPrice
    from finance_ai.evaluation.backtest import SignalStatus

    prices = StaticPriceSource({
        "ABC": series(date(2015, 2, 2), date(2015, 10, 30), lambda d: "10" if d < date(2015, 6, 8) else "12"),
        "IWM": series(date(2015, 2, 2), date(2015, 10, 30), "100"),
        "IWC": series(date(2015, 2, 2), date(2015, 10, 30), "50"),
    })
    gone = bsignal(ticker="ZZZ", status=SignalStatus.NO_PRICE, case=MissingPrice.BANKRUPTCY)
    gone = replace(gone, signal=replace(gone.signal, id="insider:zzz"))
    starts = {Section.STRESS: [], Section.VERDICT: [date(2015, 3, 1), date(2015, 4, 1)]}
    d = runs.compute([bsignal(), gone], prices, regelwerk(), starts=starts, draws=20).details
    assert [w["Start"] for w in d["Fensterverlauf"]["Urteil"]] == ["2015-03-01", "2015-04-01"]
    rows = {r["Ticker"]: r for r in d["Einzelsignale"]}
    assert rows["ZZZ"]["Status"] == "kein Kurs" and rows["ZZZ"]["ohne Kurs"] == MissingPrice.BANKRUPTCY.value
    # mittlere Stufe: Insolvenz ohne Kurs −55 % vor Steuern, also ein fester Wert
    assert rows["ZZZ"]["Vorsprung"] < -0.3
    assert rows["ABC"]["Vorsprung"] > 0
