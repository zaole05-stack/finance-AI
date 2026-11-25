"""Echte Kurse: Stundenbalken von Yahoo Finance, zwischengespeichert in SQLite.

Regeln gegen Vorausschau (Lookahead), damit das Paper Trading nicht mit
Kursen rechnet, die es zum jeweiligen Zeitpunkt noch nicht gab:
- Eine Order wird zum **Eröffnungskurs** des ersten Balkens ausgeführt, der zu
  oder nach dem Ausführungszeitpunkt beginnt. Eine Order um 10:45 läuft also
  zum Eröffnungskurs um 11:30, eine Order nach Börsenschluss am nächsten Morgen.
- Ein Schlusskurs ist erst ab dem Ende seines Balkens bekannt.
- Balken, die beim Abruf noch nicht abgeschlossen sind, werden nicht gespeichert.

Kurse sind um Splits und Dividenden bereinigt (`auto_adjust=True`). Ein neuer
Abruf überschreibt ältere Werte. Ergebnisse deshalb immer per `simulate` über
die aktuelle Kursreihe neu berechnen, nicht aus alten Fills fortschreiben.

Yahoo liefert Stundenkurse nur für die letzten 730 Tage. Die Daten sind
inoffiziell und nur für private Nutzung gedacht.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finance_ai.core.storage import from_db_time, to_db_time
from finance_ai.paper_trading.prices import NoPriceError, Quote

HOUR = timedelta(hours=1)
PRICE_STEP = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Bar:
    ticker: str
    start: datetime
    end: datetime
    open: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        for name in ("start", "end"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} braucht eine Zeitzone")
        if self.end <= self.start:
            raise ValueError("end muss nach start liegen")
        if self.open <= 0 or self.close <= 0:
            raise ValueError("Kurse müssen größer als 0 sein")


Fetcher = Callable[[str, datetime, datetime], list[Bar]]


def fetch_yahoo_hourly(ticker: str, start: datetime, end: datetime) -> list[Bar]:
    """Lädt Stundenbalken über yfinance (Netzwerkzugriff)."""
    import yfinance as yf

    frame = yf.Ticker(ticker).history(start=start, end=end, interval="1h", auto_adjust=True)
    return bars_from_frame(ticker, frame, HOUR)


def bars_from_frame(ticker: str, frame, interval: timedelta) -> list[Bar]:
    """Wandelt einen pandas-DataFrame mit Zeitindex und Spalten Open/Close in Balken um."""
    bars = []
    for timestamp, row in frame.iterrows():
        open_, close = row["Open"], row["Close"]
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (open_, close)):
            continue
        start = timestamp.to_pydatetime()
        bars.append(Bar(ticker, start, start + interval, _to_decimal(open_), _to_decimal(close)))
    return bars


class CachedPriceSource:
    """Kursquelle auf dem SQLite-Zwischenspeicher.

    Abfragen greifen nie selbst aufs Netz zu. Kurse kommen nur über
    `download` in den Speicher, damit klar ist, wann Netzwerkzugriffe passieren.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        fetcher: Fetcher = fetch_yahoo_hourly,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._conn = conn
        self._fetcher = fetcher
        self._clock = clock

    def download(self, ticker: str, start: datetime, end: datetime) -> int:
        """Lädt Balken und speichert die abgeschlossenen. Gibt deren Anzahl zurück."""
        now = self._clock()
        bars = [bar for bar in self._fetcher(ticker, start, end) if bar.end <= now]
        if not bars:
            raise NoPriceError(
                f"Keine abgeschlossenen Kurse für {ticker} zwischen {start.isoformat()} "
                f"und {end.isoformat()} (Stundenkurse gibt es nur für die letzten 730 Tage)"
            )
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO price_bars VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (ticker, bar_start) DO UPDATE SET
                    bar_end = excluded.bar_end, open = excluded.open, close = excluded.close
                """,
                [
                    (b.ticker, to_db_time(b.start), to_db_time(b.end), str(b.open), str(b.close))
                    for b in bars
                ],
            )
        return len(bars)

    def first_at_or_after(self, ticker: str, when: datetime) -> Quote:
        row = self._conn.execute(
            "SELECT bar_start, open FROM price_bars WHERE ticker = ? AND bar_start >= ? "
            "ORDER BY bar_start LIMIT 1",
            (_key(ticker), to_db_time(when)),
        ).fetchone()
        if row is None:
            raise NoPriceError(f"Kein Kurs für {ticker} ab {when.isoformat()}")
        return from_db_time(row[0]), Decimal(row[1])

    def last_at_or_before(self, ticker: str, when: datetime) -> Quote:
        key, at = _key(ticker), to_db_time(when)
        opened = self._conn.execute(
            "SELECT bar_start, open FROM price_bars WHERE ticker = ? AND bar_start <= ? "
            "ORDER BY bar_start DESC LIMIT 1",
            (key, at),
        ).fetchone()
        closed = self._conn.execute(
            "SELECT bar_end, close FROM price_bars WHERE ticker = ? AND bar_end <= ? "
            "ORDER BY bar_end DESC LIMIT 1",
            (key, at),
        ).fetchone()
        candidates = [row for row in (opened, closed) if row is not None]
        if not candidates:
            raise NoPriceError(f"Kein Kurs für {ticker} bis {when.isoformat()}")
        # Bei gleichem Zeitpunkt gewinnt der Eröffnungskurs des neuen Balkens,
        # denn er entsteht nach dem Schluss des vorherigen.
        time, price = max(candidates, key=lambda row: (row[0], row is opened))
        return from_db_time(time), Decimal(price)


def _key(ticker: str) -> str:
    return ticker.strip().upper()


def _to_decimal(value) -> Decimal:
    return Decimal(str(float(value))).quantize(PRICE_STEP)
