"""Tests für den Einstiegsbefehl (betrieb.py). Kein Netz: Scan und Kurse sind ausgedacht."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from test_decision import RULES, T0, sig

from finance_ai import betrieb
from finance_ai.core import storage
from finance_ai.core.settings import Settings, save_settings
from finance_ai.core.testrun import create_test_run, default_portfolios, get_test_run
from finance_ai.decision.regelwerk import code_rules
from finance_ai.experts import insider
from finance_ai.paper_trading.market_data import Bar, CachedPriceSource

START = T0 - timedelta(hours=2)
HOUR = timedelta(hours=1)


def fetcher(ticker, start, end):
    bars, t = [], start.replace(minute=0, second=0, microsecond=0)
    while t + HOUR <= end:
        bars.append(Bar(ticker, t, t + HOUR, D("10"), D("10")))
        t += HOUR
    return bars


@pytest.fixture
def db(tmp_path):
    conn = storage.connect(tmp_path / "finance_ai.sqlite")
    run = create_test_run(
        conn, "insider-91d", "Insider", "a", START, Settings(rules=RULES),
        default_portfolios([insider.EXPERT]), code_rules=code_rules(),
    )
    yield conn, run, tmp_path / "backups"
    conn.close()


def once(conn, run, backups, scan, at=T0, fetch=fetcher):
    prices = CachedPriceSource(conn, fetch, clock=lambda: at)
    return betrieb.run_once(conn, run, scan, prices, lambda _: None, backups, clock=lambda: at)


def test_run_scans_downloads_decides_and_logs(db):
    conn, run, backups = db
    calls = []

    def scan(since, now):
        calls.append((since, now))
        return [sig("AAA")]

    result = once(conn, run, backups, scan)

    assert calls == [(START, T0)]
    assert result.ok and result.new_signals == 1 and result.orders >= 1
    assert result.scan_until == T0 and result.backup is not None
    assert betrieb.list_operation_runs(conn, run.id) == [result]


def test_second_run_continues_scan_and_creates_nothing_twice(db):
    conn, run, backups = db
    seen = []

    def scan(since, now):
        seen.append(since)
        return [sig("AAA")]

    first = once(conn, run, backups, scan)
    orders = len(storage.list_orders(conn))
    second = once(conn, run, backups, scan, at=T0 + HOUR)

    assert seen == [START, T0]
    assert second.new_signals == 0 and second.orders == 0 and second.backup is None
    assert len(storage.list_orders(conn)) == orders == first.orders


def test_failed_scan_is_logged_and_retried_from_the_same_point(db):
    conn, run, backups = db
    seen = []

    def broken(since, now):
        seen.append(since)
        raise OSError("SEC nicht erreichbar")

    result = once(conn, run, backups, broken)
    once(conn, run, backups, broken, at=T0 + HOUR)

    assert not result.ok and "Scan: SEC nicht erreichbar" in result.error
    assert result.scan_until is None
    assert seen == [START, START]


def test_failed_price_download_skips_the_decision(db):
    conn, run, backups = db

    def offline(ticker, start, end):
        raise ConnectionError("Yahoo nicht erreichbar")

    result = once(conn, run, backups, lambda s, n: [sig("AAA")], fetch=offline)

    assert "Keine Entscheidung" in result.error
    assert storage.list_orders(conn) == []
    # Das Signal bleibt offen und wird im nächsten Lauf entschieden.
    assert storage.pending_signals(conn, run.portfolio(run.portfolios[0]), T0)


def test_changed_code_rules_are_an_error_in_the_log(db, monkeypatch):
    conn, run, backups = db
    monkeypatch.setattr(insider, "DEFAULT_MIN_VALUE", D("1"))
    result = once(conn, run, backups, lambda s, n: [sig("AAA")])
    assert "Entscheidung" in result.error and "Insider.Mindestbetrag" in result.error
    assert storage.list_orders(conn) == []


def test_tickers_cover_pending_signals_holdings_and_benchmark(db):
    conn, run, backups = db
    once(conn, run, backups, lambda s, n: [sig("AAA")])
    storage.save_signal(conn, sig("BBB", n=1))
    tickers = betrieb.tracked_tickers(conn, run, T0 + HOUR)
    assert {"AAA", "BBB", run.settings.benchmark_ticker} <= tickers


def test_edgar_scan_fills_gaps_with_daily_indexes(monkeypatch):
    days = []
    monkeypatch.setattr(insider, "scan_recent", lambda client, since: [])
    monkeypatch.setattr(insider, "scan_day", lambda client, day: days.append(day) or [])
    scan = betrieb.edgar_scan(client=None)

    scan(T0 - timedelta(hours=3), T0)
    assert days == []
    scan(T0 - timedelta(days=3), T0)
    assert days == [(T0 - timedelta(days=d)).date() for d in (3, 2, 1)]


def test_cli_creates_run_with_current_settings_and_shows_log(tmp_path, capsys):
    db = tmp_path / "finance_ai.sqlite"
    conn = storage.connect(db)
    save_settings(conn, Settings(rules=RULES))
    conn.close()
    base = ["--db", str(db), "--backup-dir", str(tmp_path / "b")]

    assert betrieb.main([*base, "testlauf-anlegen", "--id", "t1", "--name", "Test", "--owner", "a"],
                        clock=lambda: START) == 0
    assert "t1/main" in capsys.readouterr().out

    conn = storage.connect(db)
    run = get_test_run(conn, "t1")
    assert run.settings.rules == RULES and run.started_at == START
    conn.close()
    assert betrieb.main([*base, "protokoll", "--testlauf", "t1"]) == 0
    with pytest.raises(SystemExit, match="gibt es nicht"):
        betrieb.main([*base, "lauf", "--testlauf", "fehlt"])
