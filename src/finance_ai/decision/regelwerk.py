"""Regeln, die im Code stehen statt in den Einstellungen, und ihr Fingerabdruck.

Ein Testlauf friert seine Einstellungen ein (core/testrun.py). Ein Teil der
Strategie steht aber im Code: welche Insider-Käufe ein Signal werden und wie
Routinekäufer erkannt werden. Ändert sich das während eines Testlaufs, misst
er eine andere Strategie als die, mit der er begonnen hat.

Deshalb speichert der Testlauf beim Anlegen `code_rules()`, und
`run_test_run` vergleicht vor jeder Entscheidung den Fingerabdruck. Weicht er
ab, braucht es einen neuen Testlauf. Der Backtest soll dieselbe Funktion
nutzen, damit beide dasselbe Regelwerk meinen.

Neue Regeln im Code gehören hier hinein. Sonst sind sie nicht eingefroren.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from finance_ai.core import insider_history
from finance_ai.experts import insider


def code_rules() -> dict:
    """Die Regeln aus dem Code als JSON-fähiges Dict, sortiert und ohne Decimal."""
    return {
        "Insider": {
            "Mindestbetrag": str(insider.DEFAULT_MIN_VALUE),
            "ausgeschlossene_SIC": sorted(insider.EXCLUDED_SIC),
            "Konfidenz": [insider.DEFAULT_CONFIDENCE, insider.TOP_EXECUTIVE_CONFIDENCE],
            "Top-Titel": list(insider.TOP_TITLES),
        },
        "Routine": {
            "Vorjahre": insider_history.ROUTINE_YEARS,
            "Codes": sorted(insider_history.OPEN_MARKET_CODES),
        },
    }


def canonical_json(data: Mapping) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(data: Mapping) -> str:
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


def changed_rules(frozen: Mapping, current: Mapping) -> list[str]:
    """Namen der Regeln, die sich unterscheiden, als `Gruppe.Regel`."""
    names = []
    for group in sorted(set(frozen) | set(current)):
        old, new = frozen.get(group, {}), current.get(group, {})
        if not isinstance(old, Mapping) or not isinstance(new, Mapping):
            if old != new:
                names.append(group)
            continue
        names += [f"{group}.{k}" for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
    return names


class CodeRulesChangedError(RuntimeError):
    """Die Regeln im Code weichen vom eingefrorenen Stand des Testlaufs ab."""
