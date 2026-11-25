"""Einstellungen, die im Dashboard änderbar sind, gespeichert in SQLite.

Gespeichert werden Vergleichs-ETF, Teststart, die Regeln des
Entscheidungs-Agenten und das Kostenmodell. Fehlt ein Wert, gilt der Standard.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal

from finance_ai.core.storage import from_db_time, to_db_time
from finance_ai.decision.agent import DecisionRules
from finance_ai.paper_trading.costs import CostModel

# Vorläufig. Welcher Small-Cap-ETF gilt, ist in KONZEPT.md noch offen.
DEFAULT_BENCHMARK = "IWM"
_KEY = "settings"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class Settings:
    benchmark_ticker: str = DEFAULT_BENCHMARK
    # Beginn des Testlaufs. None: Zeitpunkt der ersten Order.
    test_start: datetime | None = None
    rules: DecisionRules = field(default_factory=DecisionRules)
    costs: CostModel = field(default_factory=CostModel)

    def __post_init__(self) -> None:
        ticker = self.benchmark_ticker.strip().upper()
        if not ticker:
            raise ValueError("Vergleichs-ETF fehlt")
        object.__setattr__(self, "benchmark_ticker", ticker)
        if self.test_start is not None and self.test_start.utcoffset() is None:
            raise ValueError("test_start braucht eine Zeitzone")


def load_settings(conn: sqlite3.Connection) -> Settings:
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_KEY,)).fetchone()
    if row is None:
        return Settings()
    data = json.loads(row[0])
    defaults = Settings()
    rules = data.get("rules", {})
    costs = data.get("costs", {})
    cap = rules.get("max_market_cap", str(defaults.rules.max_market_cap))
    return Settings(
        benchmark_ticker=data.get("benchmark_ticker", defaults.benchmark_ticker),
        test_start=from_db_time(data["test_start"]) if data.get("test_start") else None,
        rules=replace(
            defaults.rules,
            start_cash=Decimal(rules.get("start_cash", str(defaults.rules.start_cash))),
            max_positions=int(rules.get("max_positions", defaults.rules.max_positions)),
            holding_period=timedelta(days=int(rules.get("holding_days", defaults.rules.holding_period.days))),
            max_signal_age=timedelta(days=int(rules.get("max_signal_age_days", defaults.rules.max_signal_age.days))),
            min_confidence=float(rules.get("min_confidence", defaults.rules.min_confidence)),
            max_market_cap=Decimal(cap) if cap is not None else None,
        ),
        costs=CostModel(**{k: Decimal(v) for k, v in costs.items()}) if costs else defaults.costs,
    )


def save_settings(conn: sqlite3.Connection, settings: Settings) -> None:
    rules, costs = settings.rules, settings.costs
    data = {
        "benchmark_ticker": settings.benchmark_ticker,
        "test_start": to_db_time(settings.test_start) if settings.test_start else None,
        "rules": {
            "start_cash": str(rules.start_cash),
            "max_positions": rules.max_positions,
            "holding_days": rules.holding_period.days,
            "max_signal_age_days": rules.max_signal_age.days,
            "min_confidence": rules.min_confidence,
            "max_market_cap": str(rules.max_market_cap) if rules.max_market_cap is not None else None,
        },
        "costs": {
            name: str(getattr(costs, name))
            for name in ("fee_fixed", "fee_rate", "slippage_rate", "tax_rate")
        },
    }
    conn.executescript(SCHEMA)
    with conn:
        conn.execute(
            "INSERT INTO settings VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (_KEY, json.dumps(data)),
        )
