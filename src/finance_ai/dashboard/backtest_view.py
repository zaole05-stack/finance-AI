"""Daten für den Dashboard-Tab „Backtest“, ohne Streamlit (Plan-Schritt 9).

Liest nur `data/backtest.sqlite` und rechnet nichts selbst. Tabellen kommen aus
denselben Funktionen wie `docs/BACKTEST.md`, damit beide dieselben Zahlen zeigen.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from finance_ai.dashboard.data import database_path
from finance_ai.evaluation import backtest_report as rep
from finance_ai.evaluation.backtest_runs import YAHOO_NOTE, RunEntry, list_runs

START_COMMAND = "python -m finance_ai.evaluation.backtest run --fenster-regel <vor-etf|5pp>"


def backtest_path() -> Path:
    env = os.environ.get("FINANCE_AI_BACKTEST_DB")
    return Path(env) if env else database_path().parent / "backtest.sqlite"


def load_runs(path: Path) -> list[RunEntry]:
    """Alle Läufe, nur lesend. Fehlt die Datei, gibt es keine Läufe."""
    if not path.exists():
        return []
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return list_runs(conn)
    except sqlite3.OperationalError:  # Datei ohne Tabelle: noch kein Lauf
        return []
    finally:
        conn.close()


def _rows(header, rows) -> list[dict]:
    return [dict(zip(header, row, strict=True)) for row in rows]


@dataclass(frozen=True, slots=True)
class BacktestView:
    verdict: str
    stand: str
    fingerprint: str
    note: str
    warning: str | None
    criteria: list[str]
    coverage: list[dict]
    classes: list[dict]
    comparison: list[dict]
    regelwerk: list[dict]
    tiers: list[dict]
    halves: list[dict]
    stress: list[dict]
    extra: list[dict]
    windows: dict[str, list[dict]]
    signals: list[dict]
    runs: list[dict]


def view(entries: list[RunEntry]) -> BacktestView | None:
    if not entries:
        return None
    last = entries[-1]
    d, r = last.result, last.regelwerk
    per_tier = d.get("Urteil je Stufe", {})
    cov_header = ["messbar", "ohne Kurs", "Anteil messbar"]
    cov = d["Abdeckung"]
    warning = None
    if per_tier.get(rep.WORST) and per_tier[rep.WORST] != per_tier.get(rep.DECIDING):
        warning = (f"Im schlimmsten Fall (alle Signale ohne Kurs −100 %) lautet das Urteil "
                   f"„{per_tier[rep.WORST]}“ statt „{per_tier[rep.DECIDING]}“.")
    tier_rows = []
    for tier, parts in d["Stufen"].items():
        tier_rows += [[tier, per_tier.get(tier, "–"), *row[1:]] for row in rep._part_rows(parts, [rep.DEC])]
    deciding = d["Stufen"][rep.DECIDING]
    return BacktestView(
        verdict=last.verdict.value,
        stand=f"{last.at:%Y-%m-%d %H:%M} UTC",
        fingerprint=last.fingerprint,
        note=YAHOO_NOTE,
        warning=warning,
        criteria=rep.criteria(d, r),
        coverage=_rows(["Abschnitt", *cov_header], rep._coverage_rows(cov["Abschnitte"])),
        classes=_rows(["Klasse", *cov_header],
                      rep._coverage_rows({**cov["Klassen"], "Zielsegment gesamt": cov["Zielsegment"]})),
        comparison=[
            {"Gruppe": name, "Signale": g["Anzahl"], "später Insolvenz": rep._pct(g["später Insolvenz"]),
             "später Übernahme": rep._pct(g["später Übernahme"])}
            for name, g in cov["Vergleich"].items()
        ],
        regelwerk=[{"Regel": k, "Wert": v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}
                   for k, v in r.items()],
        tiers=_rows(["Stufe", "Urteil", *rep.PART_HEADER[1:]], tier_rows),
        halves=_rows(rep.PART_HEADER, rep._part_rows(deciding, [rep.DEC, *rep.HALVES])),
        stress=_rows(rep.PART_HEADER, rep._part_rows(deciding, [rep.STRESS])),
        extra=_rows(rep.PART_HEADER, rep._part_rows(d["Zusatz"], list(d["Zusatz"]))),
        windows=d.get("Fensterverlauf", {}),
        signals=d.get("Einzelsignale", []),
        runs=[
            {"Zeit (UTC)": f"{e.at:%Y-%m-%d %H:%M}", "Urteil": e.verdict.value,
             "Regelwerk": e.fingerprint[:12], "Begründung": e.reason or "Erstlauf"}
            for e in entries
        ],
    )
