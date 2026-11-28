"""Historischer Backtest des Insider-Experten: Signale mit Status (Plan-Schritt 5).

Aus jeder Meldung der Quartalsdatensätze entsteht über dieselbe Regel-Funktion
wie live (`insider.signal_from_form4`) höchstens ein Signal. Jedes Signal
bekommt einen Status, der sagt, ob es sich messen lässt:

- ok: Kurse vorhanden, bis über die Haltedauer hinaus;
- kein Kurs: keine Kurse oder Kurse enden in der Haltedauer, dazu der Fall
  aus `MissingPrice` für die drei Stufen;
- Kurs passt nicht: Kurse vorhanden, aber nicht zum gemeldeten Kaufpreis;
- Börsenwert unbekannt: nur im Urteilsabschnitt, wenn keine Aktienzahl
  bekannt war (wie live: dann kein Kauf).

Hier werden **keine Renditen** berechnet, das macht `measure` (Schritt 6).

Kein Blick in die Zukunft bei der Auswahl: Branchencode (heutiger, im Bericht
genannt), Aktienzahl nur aus Berichten, die vor dem Meldetag eingereicht waren,
Kurs für den Börsenwert ist der damalige Schlusskurs am Meldetag. Der Status
selbst nutzt spätere Daten (gibt es Kurse bis zum Verkauf?), er dient nur der
Messung, nicht der Auswahl.

Börsenwert ohne Yahoo-Kurs: Aktienzahl mal gemeldeter Kaufpreis. So lässt sich
die Börsenwert-Grenze auch auf die Signale ohne Kurs anwenden. Sonst gingen in
die Stufe mit −55 % auch Firmen ein, die das Regelwerk gar nicht kaufen würde.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Protocol

from finance_ai.core.models import Signal
from finance_ai.data.sec_company import CompanyInfo, MissingPrice
from finance_ai.data.sec_insider_datasets import DatasetFiling
from finance_ai.experts import insider
from finance_ai.paper_trading.daily_prices import (
    DailyPriceStore,
    PriceCheck,
    PriceStatus,
    check_price,
)

START = date(2006, 1, 1)
STRESS_END = date(2011, 6, 30)  # danach Urteilsabschnitt
END = date(2026, 9, 30)
# Für den ersten Filter vor dem Laden der Firmendaten: irgendein zulässiger Code.
ANY_OPERATING_SIC = "0000"


class Prices(Protocol):
    def check(self, ticker: str, info: CompanyInfo, day: date, price) -> PriceCheck: ...

    def last_bar_day(self, ticker: str) -> date | None: ...

    def raw_close(self, ticker: str, day: date) -> Decimal | None: ...


class StorePrices:
    """`Prices` über den Zwischenspeicher der Tageskurse."""

    def __init__(self, store: DailyPriceStore):
        self._store = store

    def check(self, ticker, info, day, price) -> PriceCheck:
        return check_price(self._store, ticker, info, day, price)

    def last_bar_day(self, ticker) -> date | None:
        bars = self._store.bars(ticker)
        return bars[-1].day if bars else None

    def raw_close(self, ticker, day) -> Decimal | None:
        return self._store.raw_close(ticker, day)


class Section(Enum):
    STRESS = "Stresstest Finanzkrise"
    VERDICT = "Urteil"


class SignalStatus(Enum):
    OK = "ok"
    NO_PRICE = "kein Kurs"
    MISMATCH = "Kurs passt nicht"
    MARKET_CAP_UNKNOWN = "Börsenwert unbekannt"


@dataclass(frozen=True, slots=True)
class PriceOutcome:
    """Ob ein Signal Kurse über die Haltedauer hat, sonst der Fall ohne Kurs."""

    check: PriceCheck
    with_price: bool
    missing_case: MissingPrice | None


@dataclass(frozen=True, slots=True)
class BacktestSignal:
    signal: Signal
    filing_date: date
    issuer_cik: str
    section: Section
    status: SignalStatus
    price_ticker: str | None
    via_current_ticker: bool
    market_cap: Decimal | None
    market_cap_source: str | None  # "Yahoo" oder "Meldung"
    missing_case: MissingPrice | None
    # Gewichteter gemeldeter Kaufpreis: Einstieg für die festen Werte ohne Kurs.
    reported_price: Decimal | None = None


@dataclass
class SignalSet:
    signals: list[BacktestSignal] = field(default_factory=list)
    no_company: int = 0  # Meldungen, für die die SEC keine Firmendaten liefert


def section_for(day: date) -> Section | None:
    if day < START or day > END:
        return None
    return Section.STRESS if day <= STRESS_END else Section.VERDICT


def insider_signal(filing: DatasetFiling, sic: str | None, created_at: datetime) -> Signal | None:
    return insider.signal_from_form4(
        filing.form4,
        accession=filing.accession,
        source_url=filing.source_url,
        observed_at=filing.observed_at,
        issuer_sic=sic,
        created_at=created_at,
    )


def _buys(filing: DatasetFiling):
    return [t for t in filing.form4.transactions if t.code == "P" and t.acquired]


def price_outcome(
    filing: DatasetFiling, info: CompanyInfo, prices: Prices, holding: timedelta
) -> PriceOutcome:
    """Kursprüfung am letzten Kauftag und Fall ohne Kurs (auch für den Datencheck)."""
    buy = _buys(filing)[-1]
    entry, exit_ = filing.filing_date, filing.filing_date + holding
    check = prices.check(filing.form4.ticker, info, buy.day, buy.price)
    if check.status is PriceStatus.OK:
        last = prices.last_bar_day(check.ticker)
        if last is not None and last >= exit_:
            return PriceOutcome(check, True, None)
        # Kurse enden in der Haltedauer: Die Aktie verschwand sicher in dieser Zeit.
        case = info.missing_price_case(entry, exit_)
        if case in (MissingPrice.AFTER_HOLDING, MissingPrice.NO_EVENT):
            case = MissingPrice.UNKNOWN
        return PriceOutcome(check, False, case)
    return PriceOutcome(check, False, info.missing_price_case(entry, exit_))


def classify(
    filing: DatasetFiling,
    info: CompanyInfo,
    prices: Prices,
    holding: timedelta,
    created_at: datetime,
) -> BacktestSignal | None:
    section = section_for(filing.filing_date)
    if section is None:
        return None
    signal = insider_signal(filing, info.sic, created_at)
    if signal is None:
        return None
    outcome = price_outcome(filing, info, prices, holding)
    cap, cap_source = _market_cap(filing, info, prices, outcome.check)

    if outcome.check.status is PriceStatus.MISMATCH:
        status = SignalStatus.MISMATCH
    elif not outcome.with_price:
        status = SignalStatus.NO_PRICE
    elif section is Section.VERDICT and cap is None:
        status = SignalStatus.MARKET_CAP_UNKNOWN
    else:
        status = SignalStatus.OK
    return BacktestSignal(
        signal=signal,
        filing_date=filing.filing_date,
        issuer_cik=filing.issuer_cik,
        section=section,
        status=status,
        price_ticker=outcome.check.ticker,
        via_current_ticker=outcome.check.via_current_ticker,
        market_cap=cap,
        market_cap_source=cap_source,
        missing_case=outcome.missing_case,
        reported_price=_reported_price(filing),
    )


def _reported_price(filing) -> Decimal | None:
    buys = _buys(filing)
    shares = sum((t.shares for t in buys), Decimal(0))
    return sum((t.value for t in buys), Decimal(0)) / shares if shares else None


def _market_cap(filing, info, prices, check) -> tuple[Decimal | None, str | None]:
    """Damaliger Börsenwert am Meldetag, nur aus Daten, die da schon öffentlich waren."""
    count = info.shares_at(filing.filing_date)
    if count is None:
        return None, None
    if check.status is PriceStatus.OK:
        close = prices.raw_close(check.ticker, filing.filing_date)
        if close is not None:
            return count * close, "Yahoo"
    price = _reported_price(filing)
    if price is None:
        return None, None
    return count * price, "Meldung"


def build_signals(
    filings: Iterable[DatasetFiling],
    company_for: Callable[[str], CompanyInfo | None],
    prices: Prices,
    holding: timedelta,
    created_at: datetime,
) -> SignalSet:
    result = SignalSet()
    for filing in filings:
        if section_for(filing.filing_date) is None:
            continue
        if insider_signal(filing, ANY_OPERATING_SIC, created_at) is None:
            continue  # Regeln ohne Branchencode schon nicht erfüllt, Firma nicht laden
        info = company_for(filing.issuer_cik)
        if info is None:
            result.no_company += 1
            continue
        signal = classify(filing, info, prices, holding, created_at)
        if signal is not None:
            result.signals.append(signal)
    return result
