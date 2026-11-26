"""Tageskurse von Yahoo Finance für den Backtest, zwischengespeichert in SQLite.

Yahoo liefert Stundenkurse nur für 730 Tage, deshalb arbeitet der Backtest mit
Tageskursen. Jeder Handelstag ergibt zwei Kurse für `PriceSource`:
Eröffnung um 09:30 und Schluss um 16:00 New York. So laufen `decide()` und
`simulate()` unverändert. Eine Order nach Börsenschluss wird am nächsten
Morgen zur Eröffnung ausgeführt.

Bereinigung (geprüft an AAPL rund um den 4:1-Split vom 31.8.2020):
- `Close` von Yahoo ist bereits um Splits bereinigt, `Adj Close` zusätzlich um
  Dividenden. Für Renditen gilt `Adj Close`, die Eröffnung wird im selben
  Verhältnis bereinigt.
- `Stock Splits` ist am Split-Tag der Faktor (4 bei 4:1), sonst 0.
- Den damaligen, unbereinigten Kurs ergibt `raw_close`: Schlusskurs mal alle
  späteren Split-Faktoren. Er wird für den Abgleich mit dem gemeldeten
  Kaufpreis und für den damaligen Börsenwert gebraucht.

Für pleitegegangene und delistete Firmen hat Yahoo meist keine Kurse. Auch
„nichts gefunden“ wird gespeichert, damit kein Ticker zweimal abgefragt wird.
Die Daten sind inoffiziell, nur für private Nutzung, und gehören nicht ins Repo.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time as clock
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path

from finance_ai.data.sec_company import CompanyInfo
from finance_ai.data.sec_edgar import EASTERN
from finance_ai.paper_trading.prices import NoPriceError, Quote

OPEN_TIME = time(9, 30)
CLOSE_TIME = time(16, 0)
PRICE_STEP = Decimal("0.000001")
PRICE_TOLERANCE = Decimal("0.25")  # Abweichung zum gemeldeten Kaufpreis

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DailyBar:
    day: date
    open: Decimal  # um Splits bereinigt
    close: Decimal  # um Splits bereinigt
    adj_close: Decimal  # um Splits und Dividenden bereinigt
    split: Decimal  # Faktor am Split-Tag, sonst 0


Fetcher = Callable[[str], list[DailyBar]]


def yahoo_symbol(ticker: str) -> str:
    """Kürzel in Yahoo-Schreibweise: Aktiengattungen mit Bindestrich (BRK.B → BRK-B)."""
    return ticker.strip().upper().replace(".", "-").replace("/", "-")


def bars_from_frame(frame) -> list[DailyBar]:
    """pandas-DataFrame von `yfinance.Ticker.history(auto_adjust=False, actions=True)`."""
    bars = []
    for timestamp, row in frame.iterrows():
        values = [row.get(name) for name in ("Open", "Close", "Adj Close")]
        if any(v is None or (isinstance(v, float) and math.isnan(v)) or v <= 0 for v in values):
            continue
        split = row.get("Stock Splits") or 0.0
        bars.append(DailyBar(
            timestamp.date(),
            *(_decimal(v) for v in values),
            _decimal(0.0 if math.isnan(split) else split),
        ))
    return bars


def fetch_yahoo_daily(ticker: str, retries: int = 3, backoff: float = 2.0) -> list[DailyBar]:
    """Alle Tageskurse eines Tickers (Netzwerkzugriff). Leer, wenn Yahoo ihn nicht kennt."""
    import yfinance as yf

    for attempt in range(retries + 1):
        try:
            frame = yf.Ticker(ticker).history(
                period="max", interval="1d", auto_adjust=False, actions=True
            )
            return bars_from_frame(frame)
        except Exception as error:  # yfinance wirft je nach Fehler sehr verschiedene Ausnahmen
            if attempt == retries:
                raise
            log.warning("Yahoo %s, Versuch %d: %s", ticker, attempt + 1, error)
            clock.sleep(backoff * 2**attempt)
    raise AssertionError("unerreichbar")


class DailyPriceStore:
    """Zwischenspeicher der Tageskurse. Nur `ensure` greift aufs Netz zu."""

    def __init__(self, path: Path, fetcher: Fetcher = fetch_yahoo_daily):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_bars (
                ticker TEXT NOT NULL, day TEXT NOT NULL, open TEXT NOT NULL,
                close TEXT NOT NULL, adj_close TEXT NOT NULL, split TEXT NOT NULL,
                PRIMARY KEY (ticker, day));
            CREATE TABLE IF NOT EXISTS fetched (
                ticker TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, bars INTEGER NOT NULL);
            """
        )
        self._fetcher = fetcher
        self._series: dict[str, list[DailyBar]] = {}

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DailyPriceStore:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def ensure(self, ticker: str) -> bool:
        """Lädt die Kurse beim ersten Mal. True, wenn es Kurse gibt."""
        key = yahoo_symbol(ticker)
        row = self._conn.execute("SELECT bars FROM fetched WHERE ticker = ?", (key,)).fetchone()
        if row is not None:
            return row[0] > 0
        bars = self._fetcher(key)
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO daily_bars VALUES (?, ?, ?, ?, ?, ?)",
                [(key, b.day.isoformat(), str(b.open), str(b.close), str(b.adj_close), str(b.split))
                 for b in bars],
            )
            self._conn.execute(
                "INSERT INTO fetched VALUES (?, ?, ?)",
                (key, datetime.now(UTC).isoformat(timespec="seconds"), len(bars)),
            )
        self._series.pop(key, None)
        return bool(bars)

    def bars(self, ticker: str) -> list[DailyBar]:
        key = yahoo_symbol(ticker)
        if key not in self._series:
            rows = self._conn.execute(
                "SELECT day, open, close, adj_close, split FROM daily_bars "
                "WHERE ticker = ? ORDER BY day", (key,),
            ).fetchall()
            self._series[key] = [
                DailyBar(date.fromisoformat(d), Decimal(o), Decimal(c), Decimal(a), Decimal(s))
                for d, o, c, a, s in rows
            ]
        return self._series[key]

    def raw_close(self, ticker: str, day: date) -> Decimal | None:
        """Damaliger, unbereinigter Schlusskurs am letzten Handelstag bis `day`."""
        bars = self.bars(ticker)
        i = bisect_right([b.day for b in bars], day)
        if i == 0:
            return None
        factor = Decimal(1)
        for later in bars[i:]:
            if later.split > 0:
                factor *= later.split
        return bars[i - 1].close * factor

    def source(self) -> DailyPriceSource:
        return DailyPriceSource(self)


class DailyPriceSource:
    """`PriceSource` mit Eröffnung (09:30) und Schluss (16:00) je Handelstag."""

    def __init__(self, store: DailyPriceStore):
        self._store = store
        self._quotes: dict[str, tuple[list[datetime], list[Decimal]]] = {}

    def first_at_or_after(self, ticker: str, when: datetime) -> Quote:
        times, prices = self._series(ticker)
        i = bisect_left(times, when)
        if i == len(times):
            raise NoPriceError(f"Kein Kurs für {ticker} ab {when.isoformat()}")
        return times[i], prices[i]

    def last_at_or_before(self, ticker: str, when: datetime) -> Quote:
        times, prices = self._series(ticker)
        i = bisect_right(times, when)
        if i == 0:
            raise NoPriceError(f"Kein Kurs für {ticker} bis {when.isoformat()}")
        return times[i - 1], prices[i - 1]

    def _series(self, ticker: str) -> tuple[list[datetime], list[Decimal]]:
        key = yahoo_symbol(ticker)
        if key not in self._quotes:
            times, prices = [], []
            for bar in self._store.bars(key):
                ratio = bar.adj_close / bar.close
                times += [datetime.combine(bar.day, OPEN_TIME, tzinfo=EASTERN),
                          datetime.combine(bar.day, CLOSE_TIME, tzinfo=EASTERN)]
                prices += [(bar.open * ratio).quantize(PRICE_STEP), bar.adj_close]
            if not times:
                raise NoPriceError(f"Keine Kurse für {ticker}")
            self._quotes[key] = (times, prices)
        return self._quotes[key]


class PriceStatus(Enum):
    OK = "ok"
    MISSING = "kein Kurs"
    MISMATCH = "Kurs passt nicht"


@dataclass(frozen=True, slots=True)
class PriceCheck:
    status: PriceStatus
    ticker: str | None  # das Kürzel, unter dem die Kurse gefunden wurden
    via_current_ticker: bool = False


def check_price(
    store: DailyPriceStore,
    ticker: str,
    company: CompanyInfo | None,
    day: date,
    reported_price: Decimal,
    tolerance: Decimal = PRICE_TOLERANCE,
) -> PriceCheck:
    """Gibt es Kurse, und gehören sie zur gemeldeten Firma?

    Versucht zuerst das damalige Kürzel, dann die heutigen der Firma (Firmen
    ändern ihr Kürzel). Passt der damalige Kurs nicht zum gemeldeten
    Kaufpreis, gehört das Kürzel vermutlich einer anderen Firma.
    """
    candidates = [ticker] + [t for t in (company.tickers if company else ()) if t != ticker]
    had_prices = False
    for position, candidate in enumerate(candidates):
        if not store.ensure(candidate):
            continue
        raw = store.raw_close(candidate, day)
        if raw is None:
            continue
        had_prices = True
        if abs(raw - reported_price) <= tolerance * reported_price:
            return PriceCheck(PriceStatus.OK, yahoo_symbol(candidate), position > 0)
    return PriceCheck(PriceStatus.MISMATCH if had_prices else PriceStatus.MISSING, None)


def _decimal(value) -> Decimal:
    return Decimal(str(float(value)))
