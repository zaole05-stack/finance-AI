"""Gemeinsame Datentypen für alle Experten, das Paper Trading und die Auswertung.

Alle Typen sind unveränderlich und prüfen ihre Werte beim Erzeugen. Geldbeträge
und Stückzahlen sind `Decimal`, damit keine Rundungsfehler entstehen. Zeitpunkte
müssen eine Zeitzone haben.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from urllib.parse import urlparse

MAIN_PORTFOLIO = "main"

# Erlaubte Tags an Signalen (docs/BEREICH-A.md, Beschlüsse 12 und 15). Ein
# unbekannter Tag ist ein Fehler. Neue Tags kommen nur hier hinzu.
TOP_EXECUTIVE = "top_executive"
ROUTINE = "routine"
OPPORTUNISTIC = "opportunistic"
UNCLASSIFIED = "unclassified"
# Muster des Käufers nach Cohen, Malloy & Pomorski (2012). Höchstens einer je Signal.
TRADE_PATTERN_TAGS = frozenset({ROUTINE, OPPORTUNISTIC, UNCLASSIFIED})
TAGS = frozenset({TOP_EXECUTIVE}) | TRADE_PATTERN_TAGS


def require_tags(tags) -> frozenset[str]:
    """Prüft Tags gegen die erlaubte Liste und gibt sie als frozenset zurück."""
    if isinstance(tags, str):
        raise TypeError("tags muss eine Menge sein, kein einzelner Text")
    result = frozenset(tags)
    unknown = result - TAGS
    if unknown:
        raise ValueError(f"Unbekannte Tags: {', '.join(sorted(unknown))}")
    return result


def shadow_portfolio(expert: str) -> str:
    """Name des Schatten-Portfolios, in dem ein Experte einzeln bewertet wird."""
    return f"shadow:{_require_text('expert', expert)}"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class Signal:
    """Hinweis eines Experten auf eine Aktie, immer mit Quellenlink.

    `observed_at` ist der Zeitpunkt, zu dem die Quelle das Ereignis
    veröffentlicht hat; `created_at` der Zeitpunkt, zu dem der Experte das
    Signal erzeugt hat. Der Abstand zeigt, wie spät das System reagiert.
    """

    expert: str
    ticker: str
    side: Side
    source_url: str
    summary: str
    observed_at: datetime
    created_at: datetime
    confidence: float = 0.5
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "expert", _require_text("expert", self.expert))
        object.__setattr__(self, "tags", require_tags(self.tags))
        if len(self.tags & TRADE_PATTERN_TAGS) > 1:
            raise ValueError("Höchstens ein Tag aus routine, opportunistic, unclassified")
        object.__setattr__(self, "ticker", _normalize_ticker(self.ticker))
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "summary", _require_text("summary", self.summary))
        _require_source_url(self.source_url)
        _require_aware("observed_at", self.observed_at)
        _require_aware("created_at", self.created_at)
        if self.created_at < self.observed_at:
            raise ValueError("created_at darf nicht vor observed_at liegen")
        if isinstance(self.confidence, bool) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence muss zwischen 0 und 1 liegen")


@dataclass(frozen=True, slots=True)
class Order:
    """Kauf- oder Verkaufsauftrag für ein Portfolio.

    Jede Order verweist auf mindestens ein Signal, damit nachvollziehbar
    bleibt, welche Experten-Infos zu ihr geführt haben.
    """

    portfolio: str
    ticker: str
    side: Side
    quantity: Decimal
    created_at: datetime
    signal_ids: tuple[str, ...]
    rationale: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        object.__setattr__(self, "portfolio", _require_text("portfolio", self.portfolio))
        object.__setattr__(self, "ticker", _normalize_ticker(self.ticker))
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "quantity", _positive_decimal("quantity", self.quantity))
        object.__setattr__(self, "rationale", _require_text("rationale", self.rationale))
        _require_aware("created_at", self.created_at)
        signal_ids = tuple(self.signal_ids)
        if not signal_ids:
            raise ValueError("Eine Order braucht mindestens ein Signal")
        if len(set(signal_ids)) != len(signal_ids):
            raise ValueError("signal_ids enthält doppelte Einträge")
        object.__setattr__(self, "signal_ids", signal_ids)


@dataclass(frozen=True, slots=True)
class Position:
    """Bestand einer Aktie in einem Portfolio. Leerverkäufe sind nicht vorgesehen."""

    portfolio: str
    ticker: str
    quantity: Decimal
    avg_price: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "portfolio", _require_text("portfolio", self.portfolio))
        object.__setattr__(self, "ticker", _normalize_ticker(self.ticker))
        object.__setattr__(self, "quantity", _positive_decimal("quantity", self.quantity))
        object.__setattr__(self, "avg_price", _positive_decimal("avg_price", self.avg_price))

    @property
    def cost_basis(self) -> Decimal:
        """Einstandswert der Position."""
        return self.quantity * self.avg_price


def _require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} darf nicht leer sein")
    return value.strip()


def _normalize_ticker(ticker: str) -> str:
    return _require_text("ticker", ticker).upper()


def _require_source_url(url: str) -> None:
    parsed = urlparse(url) if isinstance(url, str) else None
    if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Ein Signal braucht einen Quellenlink (http oder https)")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} braucht eine Zeitzone")


def _positive_decimal(name: str, value: Decimal | int | str) -> Decimal:
    # float wird abgelehnt: Decimal(0.1) übernimmt den binären Rundungsfehler.
    if isinstance(value, (float, bool)):
        raise TypeError(f"{name} muss Decimal, int oder str sein, nicht {type(value).__name__}")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name} ist keine gültige Zahl: {value!r}") from None
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} muss größer als 0 sein")
    return result
