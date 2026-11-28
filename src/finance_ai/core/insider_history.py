"""Historie aller Insider-Trades und Einstufung als Routine oder opportunistisch.

Grundlage: docs/BEREICH-A.md, Beschlüsse 13 bis 15, nach Cohen, Malloy &
Pomorski (2012), "Decoding Inside Information", Journal of Finance 67(3).

- Die Tabelle `insider_trades` (Migration 4 in core/storage.py) enthält alle
  Trades, auch Verkäufe und kleine Käufe. Personen werden an der Owner-CIK
  erkannt, nicht am Namen.
- Gemeinsame Meldungen mehrerer Insider stehen je Person einmal in der Tabelle.
- Kein Look-ahead: Die Einstufung zum Zeitpunkt `at` sieht nur Trades, deren
  Meldung bis `at` veröffentlicht war (`filed_at`), nicht das Handelsdatum.

**Vorläufig:** Die genaue Definition von „Routine“ ist im Volltext der Studie
noch nicht geprüft (BEREICH-A.md, Offen Punkt 1). Die Regel unten folgt dem
Grundgedanken der Studie: Wer jedes Jahr im selben Kalendermonat handelt,
handelt aus Gewohnheit, nicht aus Information. Die Parameter (`ROUTINE_YEARS`,
`OPEN_MARKET_CODES`) stehen im eingefrorenen Regelwerk (decision/regelwerk.py).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from finance_ai.core.models import OPPORTUNISTIC, ROUTINE, UNCLASSIFIED
from finance_ai.core.storage import from_db_time, to_db_time

# Käufe und Verkäufe am offenen Markt (Form-4-Codes P und S).
OPEN_MARKET_CODES = frozenset({"P", "S"})
# Vorjahre, in denen gehandelt sein muss (Cohen, Malloy & Pomorski: drei).
ROUTINE_YEARS = 3


@dataclass(frozen=True, slots=True)
class InsiderTrade:
    """Eine Transaktion aus einer Form-4-Meldung, einer Person zugeordnet.

    `line` ist die Position der Transaktion in der Meldung. Zusammen mit
    Meldungsnummer und Owner-CIK ist sie eindeutig.
    """

    accession: str
    line: int
    owner_cik: str
    issuer_cik: str
    ticker: str | None
    code: str
    acquired: bool
    shares: Decimal
    price: Decimal
    trade_date: date
    filed_at: datetime

    def __post_init__(self) -> None:
        for name in ("accession", "owner_cik", "issuer_cik", "code"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} darf nicht leer sein")
        if not self.owner_cik.isdigit():
            raise ValueError("owner_cik besteht nur aus Ziffern")
        if self.line < 0:
            raise ValueError("line darf nicht negativ sein")
        if self.filed_at.utcoffset() is None:
            raise ValueError("filed_at braucht eine Zeitzone")
        if self.trade_date > self.filed_at.date():
            raise ValueError("Handelsdatum nach der Meldung")
        # Führende Nullen entfernen: EDGAR schreibt die CIK mal mit, mal ohne.
        object.__setattr__(self, "owner_cik", str(int(self.owner_cik)))
        object.__setattr__(self, "issuer_cik", str(int(self.issuer_cik)))


def save_trades(conn: sqlite3.Connection, trades: Iterable[InsiderTrade]) -> int:
    """Speichert neue Trades, bekannte bleiben unverändert. Gibt die Anzahl neuer zurück.

    So können Vorab-Laden und laufender Scan dieselbe Meldung liefern.
    """
    with conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO insider_trades (accession, line, owner_cik, issuer_cik, ticker, "
            "code, acquired, shares, price, trade_date, filed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    t.accession,
                    t.line,
                    t.owner_cik,
                    t.issuer_cik,
                    t.ticker,
                    t.code,
                    int(t.acquired),
                    str(t.shares),
                    str(t.price),
                    t.trade_date.isoformat(),
                    to_db_time(t.filed_at),
                )
                for t in trades
            ],
        )
        return conn.total_changes - before


def owner_trades(conn: sqlite3.Connection, owner_cik: str, known_at: datetime) -> list[InsiderTrade]:
    """Alle Trades einer Person, deren Meldung bis `known_at` veröffentlicht war."""
    rows = conn.execute(
        "SELECT * FROM insider_trades WHERE owner_cik = ? AND filed_at <= ? "
        "ORDER BY trade_date, accession, line",
        (str(int(owner_cik)), to_db_time(known_at)),
    )
    return [
        InsiderTrade(
            accession=r["accession"],
            line=r["line"],
            owner_cik=r["owner_cik"],
            issuer_cik=r["issuer_cik"],
            ticker=r["ticker"],
            code=r["code"],
            acquired=bool(r["acquired"]),
            shares=Decimal(r["shares"]),
            price=Decimal(r["price"]),
            trade_date=date.fromisoformat(r["trade_date"]),
            filed_at=from_db_time(r["filed_at"]),
        )
        for r in rows
    ]


def classify_trade_pattern(
    history: Iterable[InsiderTrade],
    trade_date: date,
    years: int = ROUTINE_YEARS,
    codes: frozenset[str] = OPEN_MARKET_CODES,
) -> str:
    """Stuft einen Trade am `trade_date` ein: routine, opportunistic oder unclassified.

    Betrachtet werden die `years` Kalenderjahre vor dem Jahr des Trades.

    - unclassified: nicht in jedem dieser Jahre ein Trade. Zu wenig Historie,
      etwa bei neuen Führungskräften oder jungen Börsennotierungen.
    - routine: in jedem dieser Jahre ein Trade im selben Kalendermonat.
    - opportunistic: sonst.

    `history` muss schon auf die Person und den Wissensstand (`owner_trades`)
    beschränkt sein. Spätere Jahre werden ignoriert.
    """
    if years < 1:
        raise ValueError("years muss mindestens 1 sein")
    window = range(trade_date.year - years, trade_date.year)
    months_by_year: dict[int, set[int]] = {y: set() for y in window}
    for trade in history:
        if trade.code in codes and trade.trade_date.year in months_by_year:
            months_by_year[trade.trade_date.year].add(trade.trade_date.month)
    if not all(months_by_year.values()):
        return UNCLASSIFIED
    if all(trade_date.month in months for months in months_by_year.values()):
        return ROUTINE
    return OPPORTUNISTIC


def classify_owner(
    conn: sqlite3.Connection,
    owner_cik: str,
    trade_date: date,
    known_at: datetime,
    years: int = ROUTINE_YEARS,
    codes: frozenset[str] = OPEN_MARKET_CODES,
) -> str:
    """Einstufung mit der gespeicherten Historie, nur mit dem Wissen bis `known_at`."""
    return classify_trade_pattern(owner_trades(conn, owner_cik, known_at), trade_date, years, codes)
