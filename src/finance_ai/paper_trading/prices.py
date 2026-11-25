"""Kursquellen für das Paper Trading.

Die Engine kennt nur das Protokoll `PriceSource`. So bleibt die echte Quelle
(z. B. yfinance oder Stooq) austauschbar, und Tests laufen mit festen Kursen.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Protocol

Quote = tuple[datetime, Decimal]


class NoPriceError(LookupError):
    """Für den Ticker gibt es im gefragten Zeitraum keinen Kurs."""


class PriceSource(Protocol):
    def first_at_or_after(self, ticker: str, when: datetime) -> Quote:
        """Erster Kurs ab `when`: zu diesem Kurs wird eine Order ausgeführt.

        Bewusst nicht der letzte Kurs davor, sonst würde eine Order nachts zum
        Schlusskurs des Vortags gefüllt, den es real nicht mehr gibt.
        """
        ...

    def last_at_or_before(self, ticker: str, when: datetime) -> Quote:
        """Letzter bekannter Kurs bis `when`: damit wird ein Bestand bewertet."""
        ...


class StaticPriceSource:
    """Feste Kursreihen, z. B. für Tests oder vorab geladene historische Daten."""

    def __init__(self, quotes: Mapping[str, Iterable[tuple[datetime, Decimal | int | str]]]):
        self._times: dict[str, list[datetime]] = {}
        self._prices: dict[str, list[Decimal]] = {}
        for ticker, series in quotes.items():
            rows = sorted((_aware(t), _positive_price(p)) for t, p in series)
            key = ticker.strip().upper()
            self._times[key] = [t for t, _ in rows]
            self._prices[key] = [p for _, p in rows]

    def first_at_or_after(self, ticker: str, when: datetime) -> Quote:
        times, prices = self._series(ticker)
        i = bisect_left(times, _aware(when))
        if i == len(times):
            raise NoPriceError(f"Kein Kurs für {ticker} ab {when.isoformat()}")
        return times[i], prices[i]

    def last_at_or_before(self, ticker: str, when: datetime) -> Quote:
        times, prices = self._series(ticker)
        i = bisect_right(times, _aware(when))
        if i == 0:
            raise NoPriceError(f"Kein Kurs für {ticker} bis {when.isoformat()}")
        return times[i - 1], prices[i - 1]

    def _series(self, ticker: str) -> tuple[list[datetime], list[Decimal]]:
        key = ticker.strip().upper()
        if key not in self._times:
            raise NoPriceError(f"Keine Kurse für {ticker}")
        return self._times[key], self._prices[key]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Kurszeitpunkte brauchen eine Zeitzone")
    return value


def _positive_price(value: Decimal | int | str) -> Decimal:
    if isinstance(value, (float, bool)):
        raise TypeError("Kurse als Decimal, int oder str angeben, nicht float")
    price = Decimal(value)
    if not price.is_finite() or price <= 0:
        raise ValueError(f"Ungültiger Kurs: {value!r}")
    return price
