"""Messung des Insider-Backtests (Plan-Schritt 6).

Zwei Messungen, beide in drei Stufen für die Signale ohne Kurs:

1. **Einzelsignale:** Rendite nach Kosten über die Haltedauer, minus ETF im
   selben Zeitraum. Einstieg zur Eröffnung am Handelstag nach dem Meldetag,
   Ausstieg zum ersten Kurs ab Einstieg plus Haltedauer. Die Steuer wirkt
   beidseitig: Ein Verlust senkt sie, wie später im Verlusttopf. Sonst würde
   jedes einzelne Verlustsignal ohne Steuergutschrift gezählt, und der
   Mittelwert läge zu niedrig. Da Aktie und ETF denselben Betrag und
   Steuersatz haben, ist der Vorsprung genau der Vorsprung vor Steuer mal
   (1 − Steuersatz): Vorzeichen und Konfidenzintervall über null hängen nicht
   an der Steuer. Ein Totalverlust zählt deshalb als −73,6 %, nicht −100 %.
2. **Portfolio je 6-Monats-Fenster:** Jedes Fenster startet mit dem
   Startkapital, wie der Testlauf im Paper Trading. Jeden Handelstag zur
   Eröffnung entscheidet `decide()`. Die Orders laufen über
   `Account.execute()`, so wie `simulate()` sie ohne Verzögerung ausführt.
   `simulate()` selbst spielt Orders erst hinterher ab und kann keine
   abgelehnten Käufe an `decide()` zurückmelden. Ein Test prüft, dass
   `simulate()` mit denselben Orders dasselbe Ergebnis liefert.

Signale ohne Kurs bekommen im Portfolio einen eigenen Schlüssel (kein
Zusammenstoß mit wiederverwendeten Kürzeln). Ihr Kurs ist bis zum Ende der
Haltedauer der gemeldete Kaufpreis, danach der feste Wert der Stufe. Der
Verlust fällt also erst beim Verkauf an, nicht irgendwann in der Haltedauer.

Diese Funktionen laufen nie auf echten Kursen, bevor das Regelwerk
eingefroren ist.
"""

from __future__ import annotations

import hashlib
import random
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum

from finance_ai.core.models import Order, Signal
from finance_ai.data.sec_company import MissingPrice
from finance_ai.data.sec_edgar import EASTERN
from finance_ai.decision.agent import DecisionRules, Holding, decide, holdings_from_orders
from finance_ai.evaluation.backtest import (
    END,
    START,
    STRESS_END,
    BacktestSignal,
    Section,
    SignalStatus,
)
from finance_ai.paper_trading.account import Account
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.engine import Comparison, buy_and_hold, compare
from finance_ai.paper_trading.prices import NoPriceError, PriceSource, Quote

PORTFOLIO = "insider"
WINDOW_MONTHS = 6
VERDICT_START = STRESS_END + timedelta(days=1)
HALF_SPLIT = date(2019, 1, 1)  # Urteilsabschnitt: Mitte 2011–2018 und 2019–2026
OPEN_TIME = time(9, 30)
ZERO = Decimal(0)


class Tier(Enum):
    OPTIMISTIC = "optimistisch"
    REALISTIC = "vorsichtig-realistisch"
    WORST = "schlimmster Fall"


_REALISTIC = {
    MissingPrice.TAKEOVER: Decimal("0"),
    MissingPrice.BANKRUPTCY: Decimal("-0.55"),
    MissingPrice.UNKNOWN: Decimal("-0.55"),
    MissingPrice.AFTER_HOLDING: None,
    MissingPrice.NO_EVENT: Decimal("-0.55"),
}


def fixed_return(tier: Tier, case: MissingPrice | None) -> Decimal | None:
    """Fester Kursverlauf für ein Signal ohne Kurs. None: Das Signal fällt weg."""
    if case is None or tier is Tier.OPTIMISTIC:
        return None
    if tier is Tier.WORST:
        return Decimal("-1")
    return _REALISTIC[case]


def double_slippage(costs: CostModel) -> CostModel:
    return replace(costs, slippage_rate=costs.slippage_rate * 2)


def eligible(s: BacktestSignal, rules: DecisionRules) -> bool:
    """Würde das Regelwerk das Signal kaufen (ohne Plätze und Bargeld)?"""
    if s.status is SignalStatus.MARKET_CAP_UNKNOWN or s.signal.confidence < rules.min_confidence:
        return False
    if s.section is Section.VERDICT and rules.max_market_cap is not None:
        return s.market_cap is not None and s.market_cap <= rules.max_market_cap
    return True


def round_trip_return(entry: Decimal, exit_: Decimal, costs: CostModel, position: Decimal) -> Decimal:
    """Rendite eines Kaufs zu `entry` und Verkaufs zu `exit_` nach allen Kosten."""
    gross = (position - costs.fee_fixed) / (1 + costs.fee_rate)
    quantity = gross / costs.buy_price(entry)
    paid = gross + costs.fee(gross)
    sale = quantity * costs.sell_price(exit_)
    proceeds = sale - costs.fee(sale) if sale > 0 else ZERO  # Totalverlust: nichts zu verkaufen
    gain = proceeds - paid
    return gain * (1 - costs.tax_rate) / position


# --- Einzelsignale ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignalResult:
    signal: BacktestSignal
    entry: datetime
    exit: datetime
    stock_return: Decimal
    etf_return: Decimal
    measured: bool  # True: mit Kursen, False: fester Wert der Stufe

    @property
    def excess(self) -> Decimal:
        return self.stock_return - self.etf_return


def _next_day(day: date) -> datetime:
    """Meldungen gelten als nach Börsenschluss eingegangen."""
    return datetime.combine(day + timedelta(days=1), time(0), tzinfo=EASTERN)


def _quote_after(prices: PriceSource, ticker: str, when: datetime) -> Quote:
    try:
        return prices.first_at_or_after(ticker, when)
    except NoPriceError as error:
        raise ValueError(
            f"Kein Kurs für {ticker} ab {when.isoformat()}: Haltedauer endet nach den vorhandenen Kursen?"
        ) from error


def single_result(
    s: BacktestSignal,
    tier: Tier,
    prices: PriceSource,
    etf: str,
    holding: timedelta,
    costs: CostModel,
    position: Decimal,
) -> SignalResult | None:
    if s.status is SignalStatus.OK:
        entry, q0 = _quote_after(prices, s.price_ticker, _next_day(s.filing_date))
        exit_, q1 = _quote_after(prices, s.price_ticker, entry + holding)
        stock, measured = round_trip_return(q0, q1, costs, position), True
    else:
        r = fixed_return(tier, s.missing_case)
        if r is None:
            return None
        entry, _ = _quote_after(prices, etf, _next_day(s.filing_date))
        exit_, _ = _quote_after(prices, etf, entry + holding)
        p0 = s.reported_price or Decimal(1)
        stock, measured = round_trip_return(p0, p0 * (1 + r), costs, position), False
    _, e0 = _quote_after(prices, etf, entry)
    _, e1 = _quote_after(prices, etf, exit_)
    return SignalResult(s, entry, exit_, stock, round_trip_return(e0, e1, costs, position), measured)


def single_results(
    signals: Iterable[BacktestSignal],
    tier: Tier,
    prices: PriceSource,
    etf: str,
    rules: DecisionRules,
    costs: CostModel,
) -> list[SignalResult]:
    results = []
    for s in signals:
        if eligible(s, rules):
            r = single_result(s, tier, prices, etf, rules.holding_period, costs, rules.position_budget)
            if r is not None:
                results.append(r)
    return results


# --- Bootstrap -------------------------------------------------------------------


def bootstrap_means(results: Sequence[SignalResult], draws: int = 10_000, seed: int = 0) -> list[float]:
    """Mittelwerte aus Ziehungen ganzer Kalendermonate (Signale eines Monats hängen zusammen)."""
    months: dict[tuple[int, int], list[float]] = defaultdict(list)
    for r in results:
        months[(r.signal.filing_date.year, r.signal.filing_date.month)].append(float(r.excess))
    blocks = [(sum(v), len(v)) for _, v in sorted(months.items())]
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        drawn = rng.choices(blocks, k=len(blocks))
        means.append(sum(t for t, _ in drawn) / sum(n for _, n in drawn))
    return means


def bootstrap_ci(
    results: Sequence[SignalResult], draws: int = 10_000, seed: int = 0, level: float = 0.95
) -> tuple[float, float]:
    means = sorted(bootstrap_means(results, draws, seed))
    tail = (1 - level) / 2
    return means[int(tail * (draws - 1))], means[int((1 - tail) * (draws - 1))]


# --- Fenster ---------------------------------------------------------------------


def add_months(day: date, months: int) -> date:
    total = day.year * 12 + day.month - 1 + months
    return date(total // 12, total % 12 + 1, 1)


def window_starts(section: Section) -> list[date]:
    """Monatliche Starts; jedes Fenster liegt ganz im Abschnitt."""
    first, last = (START, STRESS_END) if section is Section.STRESS else (VERDICT_START, END)
    starts, day = [], date(first.year, first.month, 1)
    if day < first:
        day = add_months(day, 1)
    while add_months(day, WINDOW_MONTHS) <= last:
        starts.append(day)
        day = add_months(day, 1)
    return starts


def halves(starts: Sequence[date]) -> tuple[list[date], list[date]]:
    """Fenster ganz vor bzw. ganz ab 2019. Fenster über den Jahreswechsel fallen aus beiden."""
    first = [d for d in starts if add_months(d, WINDOW_MONTHS) <= HALF_SPLIT]
    second = [d for d in starts if d >= HALF_SPLIT]
    return first, second


@dataclass(frozen=True, slots=True)
class Summary:
    count: int
    mean: Decimal
    share_ahead: float  # Anteil mit Vorsprung > 0
    share_5pp: float  # Anteil mit Vorsprung ≥ 5 Prozentpunkten


def summarize(excesses: Sequence[Decimal]) -> Summary:
    n = len(excesses)
    if n == 0:
        return Summary(0, ZERO, 0.0, 0.0)
    return Summary(
        n,
        sum(excesses, ZERO) / n,
        sum(e > 0 for e in excesses) / n,
        sum(e >= Decimal("0.05") for e in excesses) / n,
    )


# --- Portfolio -------------------------------------------------------------------


def fixed_key(s: BacktestSignal) -> str:
    """Eigener Schlüssel für ein Signal ohne Kurs (IDs haben live alle denselben Anfang)."""
    return f"FEST-{hashlib.sha256(s.signal.id.encode()).hexdigest()[:16]}".upper()


class TierPrices:
    """Echte Kurse plus fester Verlauf für die Signale ohne Kurs einer Stufe."""

    def __init__(self, base: PriceSource, signals: Iterable[BacktestSignal], tier: Tier, holding: timedelta):
        self._base = base
        self._fixed: dict[str, tuple[datetime, datetime, Decimal, Decimal]] = {}
        for s in signals:
            if s.status is SignalStatus.OK:
                continue
            r = fixed_return(tier, s.missing_case)
            if r is None:
                continue
            p0 = s.reported_price or Decimal(1)
            start = s.signal.observed_at
            self._fixed[fixed_key(s)] = (start, start + holding, p0, p0 * (1 + r))

    def has(self, key: str) -> bool:
        return key in self._fixed

    def first_at_or_after(self, ticker: str, when: datetime) -> Quote:
        if ticker not in self._fixed:
            return self._base.first_at_or_after(ticker, when)
        start, switch, p0, p1 = self._fixed[ticker]
        when = max(when, start)
        return when, (p0 if when < switch else p1)

    def last_at_or_before(self, ticker: str, when: datetime) -> Quote:
        if ticker not in self._fixed:
            return self._base.last_at_or_before(ticker, when)
        start, switch, p0, p1 = self._fixed[ticker]
        if when < start:
            raise NoPriceError(f"Kein Kurs für {ticker} bis {when.isoformat()}")
        return when, (p0 if when < switch else p1)


@dataclass(frozen=True, slots=True)
class WindowResult:
    start: date
    end: date
    comparison: Comparison
    orders: list[Order]
    account: Account

    @property
    def excess(self) -> Decimal:
        return self.comparison.excess_return


def _trading_days(prices: PriceSource, etf: str, start: date, end: date) -> list[datetime]:
    days, cursor = [], datetime.combine(start, time(0), tzinfo=EASTERN)
    stop = datetime.combine(end, time(0), tzinfo=EASTERN)
    while True:
        try:
            when, _ = prices.first_at_or_after(etf, cursor)
        except NoPriceError:
            break
        if when >= stop:
            break
        days.append(datetime.combine(when.date(), OPEN_TIME, tzinfo=EASTERN))
        cursor = datetime.combine(when.date() + timedelta(days=1), time(0), tzinfo=EASTERN)
    return days


def _portfolio_signals(
    signals: Iterable[BacktestSignal], section: Section, prices: TierPrices
) -> list[tuple[Signal, Decimal | None]]:
    """Signale des Abschnitts mit dem Kürzel, unter dem es Kurse gibt, sortiert nach Meldezeit."""
    chosen = []
    for s in signals:
        if s.section is not section:
            continue
        if s.status is SignalStatus.OK or s.status is SignalStatus.MARKET_CAP_UNKNOWN:
            ticker = s.price_ticker
        elif prices.has(fixed_key(s)):
            ticker = fixed_key(s)
        else:
            continue  # fällt in dieser Stufe weg
        # Erzeugt zum Meldezeitpunkt, damit `decide()` es am nächsten Morgen sieht.
        signal = replace(s.signal, ticker=ticker, created_at=s.signal.observed_at)
        chosen.append((signal, s.market_cap))
    chosen.sort(key=lambda c: (c[0].observed_at, c[0].id))
    return chosen


def run_window(
    signals: Iterable[BacktestSignal],
    tier: Tier,
    start: date,
    section: Section,
    prices: PriceSource,
    etf: str,
    rules: DecisionRules,
    costs: CostModel,
) -> WindowResult:
    """Ein Portfolio über 6 Monate ab `start`, nur mit Signalen des Abschnitts."""
    signals = list(signals)
    tier_prices = TierPrices(prices, signals, tier, rules.holding_period)
    chosen = _portfolio_signals(signals, section, tier_prices)
    times = [c[0].observed_at for c in chosen]
    end = add_months(start, WINDOW_MONTHS)
    days = _trading_days(prices, etf, start, end)
    if not days:
        raise ValueError(f"Keine ETF-Kurse für {etf} zwischen {start} und {end}")

    account = Account(f"{PORTFOLIO}/backtest", rules.start_cash, costs)
    filled: list[Order] = []
    orders: list[Order] = []
    for at in days:
        visible = chosen[bisect_left(times, at - rules.max_signal_age) : bisect_right(times, at)]
        caps = {sig.ticker: cap for sig, cap in visible}
        lookup = caps.get if section is Section.VERDICT else None
        holdings: dict[str, Holding] = holdings_from_orders(filled)
        decision = decide(PORTFOLIO, [sig for sig, _ in visible], holdings, at, tier_prices, rules, lookup)
        for order in decision.orders:
            orders.append(order)
            if account.execute(order, at, tier_prices) is not None:
                filled.append(order)

    benchmark = buy_and_hold(etf, days[0], prices, rules.start_cash, costs)
    stop = datetime.combine(end, time(0), tzinfo=EASTERN)
    return WindowResult(start, end, compare(account, benchmark, stop, tier_prices), orders, account)
