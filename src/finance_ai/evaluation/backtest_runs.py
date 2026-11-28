"""Lauf und Neulauf des Insider-Backtests (Plan-Schritt 7).

Der volle Lauf rechnet **einmal**. Gespeichert werden Zeitstempel, Urteil,
Ergebnis und ein Fingerabdruck des Regelwerks in `data/backtest.sqlite`.

Ein zweiter Lauf braucht `--rerun "<Begründung>"` (belegter Fehler im Code)
und dasselbe Regelwerk. Ein geändertes Regelwerk ist eine Strategie-Änderung
und braucht einen neuen Backtest, keinen Neulauf. Die Sperre greift, bevor
etwas gerechnet wird.

Das Regelwerk kommt aus derselben Quelle wie der Testlauf: Entscheidungsregeln,
Kosten und ETF aus den Einstellungen der Haupt-Datenbank, Insider-Regeln und
Zeitraum aus dem Code. Dazu kommt die Lesart von Kriterium 1. Sie muss beim
Lauf angegeben werden und steckt im Fingerabdruck. So lässt sie sich nach dem
Ergebnis nicht mehr wählen.

Aufruf (rechnet auf echten Daten, erst nach dem Einfrieren des Regelwerks):
    python -m finance_ai.evaluation.backtest run --fenster-regel 5pp
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from finance_ai.core.settings import Settings
from finance_ai.decision.agent import DecisionRules
from finance_ai.evaluation import backtest as bt
from finance_ai.evaluation import measure as m
from finance_ai.experts import insider
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.prices import PriceSource

log = logging.getLogger(__name__)

YAHOO_NOTE = "Das Urteil gilt nur für Signale, deren Aktie Yahoo bis heute führt."


class WindowRule(Enum):
    """Lesart von Kriterium 1: Welcher Anteil der Fenster muss 60 % erreichen?"""

    AHEAD = "vor-etf"  # Vorsprung > 0
    FIVE_PP = "5pp"  # Vorsprung ≥ 5 Prozentpunkte


class BacktestVerdict(Enum):
    PASSED = "bestanden"
    CLOSE = "knapp"
    FAILED = "durchgefallen"


@dataclass(frozen=True, slots=True)
class Regelwerk:
    benchmark: str
    second_benchmark: str
    rules: DecisionRules
    costs: CostModel
    window_rule: WindowRule
    # Aus dem Code gelesen, nicht einstellbar. Im Fingerabdruck, damit eine
    # Änderung im Code nicht als Neulauf durchgeht.
    min_value: Decimal = insider.DEFAULT_MIN_VALUE
    excluded_sic: frozenset[str] = insider.EXCLUDED_SIC
    confidence: tuple[float, float] = (insider.DEFAULT_CONFIDENCE, insider.TOP_EXECUTIVE_CONFIDENCE)
    start: date = bt.START
    stress_end: date = bt.STRESS_END
    end: date = bt.END
    realistic_tier: tuple[tuple[str, str | None], ...] = field(
        default_factory=lambda: tuple(
            (c.name, None if v is None else str(v)) for c, v in m._REALISTIC.items()
        )
    )

    def canonical(self) -> dict:
        r, c = self.rules, self.costs
        return {
            "ETF": self.benchmark,
            "Zweit-ETF": self.second_benchmark,
            "Startkapital": str(r.start_cash),
            "Plätze": r.max_positions,
            "Haltedauer_Tage": r.holding_period.days,
            "Signalalter_Tage": r.max_signal_age.days,
            "Mindestkonfidenz": r.min_confidence,
            "Börsenwert_Grenze": None if r.max_market_cap is None else str(r.max_market_cap),
            "Kosten": {n: str(getattr(c, n)) for n in ("fee_fixed", "fee_rate", "slippage_rate", "tax_rate")},
            "Fenster_Regel": self.window_rule.value,
            "Mindestbetrag": str(self.min_value),
            "ausgeschlossene_SIC": sorted(self.excluded_sic),
            "Konfidenz": list(self.confidence),
            "Zeitraum": [self.start.isoformat(), self.stress_end.isoformat(), self.end.isoformat()],
            "mittlere_Stufe": [list(x) for x in self.realistic_tier],
        }


def regelwerk_from_settings(settings: Settings, window_rule: WindowRule) -> Regelwerk:
    second = "IWM" if settings.benchmark_ticker == "IWC" else "IWC"
    return Regelwerk(settings.benchmark_ticker, second, settings.rules, settings.costs, window_rule)


def fingerprint(r: Regelwerk) -> str:
    text = json.dumps(r.canonical(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


# --- Urteil -------------------------------------------------------------------------


def verdict(windows: m.Summary, single_mean: Decimal, ci_low: float | None, rule: WindowRule) -> BacktestVerdict:
    """Bestanden: beide Kriterien. Durchgefallen: im Mittel nicht vor dem ETF. Sonst knapp."""
    if windows.count == 0 or windows.mean <= 0:
        return BacktestVerdict.FAILED
    share = windows.share_5pp if rule is WindowRule.FIVE_PP else windows.share_ahead
    first = windows.mean >= Decimal("0.05") and share >= 0.6
    second = single_mean > 0 and ci_low is not None and ci_low > 0
    return BacktestVerdict.PASSED if first and second else BacktestVerdict.CLOSE


# --- Rechnung -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunResult:
    verdict: BacktestVerdict
    details: dict


def _num(x: Decimal | float) -> float:
    return round(float(x), 6)


def _singles(results: Sequence[m.SignalResult], draws: int) -> tuple[dict, Decimal, float | None]:
    s = m.summarize([r.excess for r in results])
    ci = m.bootstrap_ci(results, draws=draws) if results else None
    return (
        {
            "Anzahl": s.count,
            "davon fester Wert": sum(not r.measured for r in results),
            "Mittel": _num(s.mean),
            "KI 95 %": None if ci is None else [round(ci[0], 6), round(ci[1], 6)],
        },
        s.mean,
        None if ci is None else ci[0],
    )


def _windows(results: Sequence[m.WindowResult]) -> tuple[dict, m.Summary]:
    s = m.summarize([w.excess for w in results])
    return (
        {"Anzahl": s.count, "Mittel": _num(s.mean), "Anteil vor ETF": round(s.share_ahead, 4),
         "Anteil ≥ 5 Pp": round(s.share_5pp, 4)},
        s,
    )


def _in_part(s: bt.BacktestSignal, section: bt.Section, name: str) -> bool:
    if s.section is not section:
        return False
    if name.endswith("2011–2018"):
        return s.filing_date < m.HALF_SPLIT
    if name.endswith("2019–2026"):
        return s.filing_date >= m.HALF_SPLIT
    return True


CAP_CLASSES = (Decimal("50000000"), Decimal("300000000"))


def _cap_class(cap: Decimal, limit: Decimal | None) -> str:
    if cap < CAP_CLASSES[0]:
        return "unter 50 Mio. USD"
    if cap < CAP_CLASSES[1]:
        return "50–300 Mio. USD"
    return "300 Mio. USD bis Grenze" if limit is not None else "ab 300 Mio. USD"


def _group(signals: Sequence[bt.BacktestSignal]) -> dict:
    measurable = [s for s in signals if s.status is bt.SignalStatus.OK]
    dropped = [s for s in signals if s.status in (bt.SignalStatus.NO_PRICE, bt.SignalStatus.MISMATCH)]
    n = len(measurable) + len(dropped)
    return {"messbar": len(measurable), "ohne Kurs": len(dropped),
            "Anteil messbar": round(len(measurable) / n, 4) if n else None}


def _later(signals: Sequence[bt.BacktestSignal]) -> dict:
    n = len(signals)
    return {
        "Anzahl": n,
        "später Insolvenz": round(sum(s.later_bankruptcy for s in signals) / n, 4) if n else None,
        "später Übernahme": round(sum(s.later_takeover for s in signals) / n, 4) if n else None,
    }


def coverage(signals: Sequence[bt.BacktestSignal], r: Regelwerk) -> dict:
    """Wie viele Signale messbar sind und wie sich die Weggefallenen unterscheiden. Keine Renditen."""
    limit = r.rules.max_market_cap
    candidates = [s for s in signals if s.signal.confidence >= r.rules.min_confidence]
    by_section = {sec.value: _group([s for s in candidates if s.section is sec]) for sec in bt.Section}
    target = [
        s for s in candidates
        if s.section is bt.Section.VERDICT and s.market_cap is not None
        and (limit is None or s.market_cap <= limit)
    ]
    classes: dict[str, list] = {}
    for s in target:
        classes.setdefault(_cap_class(s.market_cap, limit), []).append(s)
    order = ["unter 50 Mio. USD", "50–300 Mio. USD", "300 Mio. USD bis Grenze", "ab 300 Mio. USD"]
    pool = target + [s for s in candidates if s.section is bt.Section.STRESS]
    return {
        "Abschnitte": by_section,
        "Zielsegment": _group(target),
        "Klassen": {c: _group(classes[c]) for c in order if c in classes},
        "Vergleich": {
            "messbar": _later([s for s in pool if s.status is bt.SignalStatus.OK]),
            "weggefallen": _later([s for s in pool if s.status in (bt.SignalStatus.NO_PRICE, bt.SignalStatus.MISMATCH)]),
        },
    }


def _measure(signals, prices, r: Regelwerk, tier, etf, costs, starts, draws):
    """Einzelsignale und Fenster je Abschnitt und Hälfte für eine Stufe."""
    singles = m.single_results(signals, tier, prices, etf, r.rules, costs)
    candidates = [s for s in signals if m.eligible(s, r.rules)]
    out, key = {}, {}
    for section in bt.Section:
        sec_singles = [x for x in singles if x.signal.section is section]
        sec_starts = starts[section]
        windows = {d: m.run_window(signals, tier, d, section, prices, etf, r.rules, costs) for d in sec_starts}
        parts = [(section.value, sec_singles, sec_starts)]
        if section is bt.Section.VERDICT:
            first, second = m.halves(sec_starts)
            parts += [
                ("Urteil 2011–2018", [x for x in sec_singles if x.signal.filing_date < m.HALF_SPLIT], first),
                ("Urteil 2019–2026", [x for x in sec_singles if x.signal.filing_date >= m.HALF_SPLIT], second),
            ]
        for name, part_singles, part_starts in parts:
            single_info, mean, low = _singles(part_singles, draws)
            single_info["weggefallen"] = sum(
                _in_part(c, section, name) for c in candidates
            ) - len(part_singles)
            window_info, summary = _windows([windows[d] for d in part_starts])
            out[name] = {"Einzelsignale": single_info, "Fenster": window_info}
            key[name] = (summary, mean, low)
    return out, key


def compute(
    signals: Sequence[bt.BacktestSignal],
    prices: PriceSource,
    r: Regelwerk,
    starts: dict[bt.Section, list[date]] | None = None,
    draws: int = 10_000,
) -> RunResult:
    starts = starts or {s: m.window_starts(s) for s in bt.Section}
    tiers, per_tier, deciding = {}, {}, None
    for tier in m.Tier:
        out, key = _measure(signals, prices, r, tier, r.benchmark, r.costs, starts, draws)
        tiers[tier.value] = out
        summary, mean, low = key[bt.Section.VERDICT.value]
        per_tier[tier.value] = verdict(summary, mean, low, r.window_rule).value
        if tier is m.Tier.REALISTIC:
            deciding = key[bt.Section.VERDICT.value]
    extra = {
        "doppelte Slippage": _measure(
            signals, prices, r, m.Tier.REALISTIC, r.benchmark, m.double_slippage(r.costs), starts, draws
        )[0][bt.Section.VERDICT.value],
        f"Zweit-ETF {r.second_benchmark}": _measure(
            signals, prices, r, m.Tier.REALISTIC, r.second_benchmark, r.costs, starts, draws
        )[0][bt.Section.VERDICT.value],
    }
    summary, mean, low = deciding
    result = verdict(summary, mean, low, r.window_rule)
    details = {
        "Hinweis": YAHOO_NOTE,
        "Signale": {status.value: sum(s.status is status for s in signals) for status in bt.SignalStatus},
        "Abdeckung": coverage(signals, r),
        "Urteil je Stufe": per_tier,
        "Stufen": tiers,
        "Zusatz": extra,
    }
    return RunResult(result, details)


# --- Protokoll ----------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    regelwerk   TEXT NOT NULL,
    reason      TEXT,
    verdict     TEXT NOT NULL,
    result      TEXT NOT NULL
);
"""


class RunRefused(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RunEntry:
    at: datetime
    fingerprint: str
    regelwerk: dict
    reason: str | None
    verdict: BacktestVerdict
    result: dict


def list_runs(conn: sqlite3.Connection) -> list[RunEntry]:
    conn.executescript(SCHEMA)
    rows = conn.execute(
        "SELECT at, fingerprint, regelwerk, reason, verdict, result FROM backtest_runs ORDER BY id"
    ).fetchall()
    return [
        RunEntry(datetime.fromisoformat(a), f, json.loads(rw), reason, BacktestVerdict(v), json.loads(res))
        for a, f, rw, reason, v, res in rows
    ]


def check_allowed(conn: sqlite3.Connection, r: Regelwerk, reason: str | None) -> None:
    earlier = list_runs(conn)
    if reason is not None and not reason.strip():
        raise RunRefused("--rerun braucht eine Begründung: welcher Fehler, welcher Test belegt ihn")
    if not earlier:
        return
    if reason is None:
        raise RunRefused(
            f"Es gibt schon einen Lauf vom {earlier[0].at:%Y-%m-%d}. Neulauf nur nach belegtem "
            'Fehler im Code: --rerun "<Begründung>"'
        )
    if fingerprint(r) != earlier[0].fingerprint:
        raise RunRefused(
            "Das Regelwerk weicht vom ersten Lauf ab. Das ist eine Strategie-Änderung und "
            "braucht einen neuen Backtest, keinen Neulauf."
        )


def run(
    conn: sqlite3.Connection,
    r: Regelwerk,
    reason: str | None,
    compute_fn: Callable[[], RunResult],
    now: datetime,
) -> RunEntry:
    check_allowed(conn, r, reason)  # vor dem Rechnen
    result = compute_fn()
    entry = RunEntry(now, fingerprint(r), r.canonical(), reason.strip() if reason else None,
                     result.verdict, result.details)
    with conn:
        conn.execute(
            "INSERT INTO backtest_runs (at, fingerprint, regelwerk, reason, verdict, result) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now.isoformat(), entry.fingerprint, json.dumps(entry.regelwerk, ensure_ascii=False),
             entry.reason, result.verdict.value, json.dumps(result.details, ensure_ascii=False)),
        )
    return entry


# --- Befehl -------------------------------------------------------------------------


def _quarters(r: Regelwerk) -> set[str]:
    """Quartale, die den Zeitraum berühren."""
    return {
        f"{y}q{q}"
        for y in range(r.start.year, r.end.year + 1)
        for q in range(1, 5)
        if date(y, 3 * q - 2, 1) <= r.end and m.add_months(date(y, 3 * q - 2, 1), 3) > r.start
    }


REPORT_PATH = Path("docs") / "BACKTEST.md"


def write_report(db: Path, out: Path) -> None:
    from finance_ai.evaluation.backtest_report import markdown

    conn = sqlite3.connect(db)
    try:
        out.write_text(markdown(list_runs(conn)), encoding="utf-8")
    finally:
        conn.close()
    print(f"Bericht: {out}")


def main(argv: list[str] | None = None) -> None:
    from finance_ai.config import sec_user_agent
    from finance_ai.core import storage
    from finance_ai.core.settings import load_settings
    from finance_ai.data.sec_company import load_company
    from finance_ai.data.sec_edgar import EdgarClient
    from finance_ai.data.sec_insider_datasets import download_quarters, read_quarter
    from finance_ai.paper_trading.daily_prices import DailyPriceStore

    parser = argparse.ArgumentParser(prog="python -m finance_ai.evaluation.backtest")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("run", help="voller Lauf, einmal")
    cmd.add_argument("--fenster-regel", required=True, choices=[w.value for w in WindowRule])
    cmd.add_argument("--rerun", metavar="GRUND")
    cmd.add_argument("--data", type=Path, default=Path("data"))
    cmd.add_argument("--db", type=Path, default=Path("data") / "finance_ai.sqlite")
    rep = sub.add_parser("report", help="docs/BACKTEST.md aus den gespeicherten Läufen")
    rep.add_argument("--data", type=Path, default=Path("data"))
    rep.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    if args.command == "report":
        write_report(args.data / "backtest.sqlite", args.out)
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    settings_conn = storage.connect(args.db)
    r = regelwerk_from_settings(load_settings(settings_conn), WindowRule(args.fenster_regel))
    settings_conn.close()
    runs_conn = sqlite3.connect(args.data / "backtest.sqlite")
    try:
        check_allowed(runs_conn, r, args.rerun)
    except RunRefused as error:
        raise SystemExit(f"Abgelehnt: {error}") from None

    def compute_fn() -> RunResult:
        client = EdgarClient(sec_user_agent())
        companies: dict = {}

        def company_for(cik):
            if cik not in companies:
                companies[cik] = load_company(client, cik, args.data / "raw" / "companies")
            return companies[cik]

        paths = download_quarters(client, args.data / "raw", only=_quarters(r))
        filings = (f for path in paths for f in read_quarter(path))
        with DailyPriceStore(args.data / "prices_daily.sqlite") as store:
            signal_set = bt.build_signals(
                filings, company_for, bt.StorePrices(store), r.rules.holding_period, datetime.now(UTC)
            )
            log.info("%d Signale, %d ohne Firmendaten", len(signal_set.signals), signal_set.no_company)
            for etf in (r.benchmark, r.second_benchmark):
                if not store.ensure(etf):
                    raise SystemExit(f"Keine Kurse für den ETF {etf}")
            return compute(signal_set.signals, store.source(), r)

    entry = run(runs_conn, r, args.rerun, compute_fn, datetime.now(UTC))
    runs_conn.close()
    write_report(args.data / "backtest.sqlite", REPORT_PATH)
    print(YAHOO_NOTE)
    print(f"Urteil: {entry.verdict.value} (Regelwerk {entry.fingerprint[:12]})")
