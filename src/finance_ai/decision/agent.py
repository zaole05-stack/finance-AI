"""Entscheidungs-Agent: macht aus Expertensignalen Orders, mit Begründung.

Er arbeitet vorerst nur mit festen Regeln, ohne LLM. Das LLM-Budget ist noch
offen, und feste Regeln lassen sich sauber messen. Ein LLM kann später als
zusätzliche Prüfung der übrig gebliebenen Kandidaten dazukommen.

Regeln je Lauf:
1. Positionen, deren Haltedauer abgelaufen ist, werden verkauft.
2. Kaufsignale werden je Ticker gebündelt. Mehrere Signale zum selben Ticker
   ergeben eine Order, die auf alle verweist.
3. Ein Kandidat fällt weg, wenn
   - sein jüngstes Signal zu alt ist,
   - die Konfidenz unter der Schwelle liegt,
   - die Aktie schon im Depot liegt,
   - der Börsenwert zu hoch oder unbekannt ist (Filter auf kleine Firmen),
   - kein aktueller Kurs vorliegt.
4. Die übrigen Kandidaten werden gereiht: zuerst nach höchster Konfidenz,
   dann nach Anzahl der Signale, dann nach Alter. Gekauft wird, solange
   Plätze frei sind.
5. Jede Position bekommt denselben Betrag: Startkapital / Anzahl Plätze,
   abzüglich 2 % Puffer für Kosten. Gekauft werden ganze Aktien.

Über jedes Signal wird je Portfolio genau einmal entschieden. Abgelehnte
Signale werden mit Grund gespeichert und später nicht erneut geprüft.

Der Depotbestand ergibt sich aus den bisherigen Orders, nicht aus den
Ausführungen. Wird eine Kauforder in der Simulation abgelehnt (z. B. zu wenig
Bargeld), zählt die Aktie trotzdem als gehalten. Die spätere Verkaufsorder
wird dann ebenfalls abgelehnt. Das ist harmlos, belegt aber einen Platz.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from finance_ai.core.models import Order, Side, Signal
from finance_ai.paper_trading.prices import NoPriceError, PriceSource

MarketCapLookup = Callable[[str], Decimal | None]
COST_BUFFER = Decimal("0.98")


@dataclass(frozen=True, slots=True)
class DecisionRules:
    start_cash: Decimal = Decimal("10000")
    max_positions: int = 10
    holding_period: timedelta = timedelta(days=91)
    max_signal_age: timedelta = timedelta(days=3)
    min_confidence: float = 0.5
    # Russell-2000-Bereich. None schaltet den Filter ab.
    max_market_cap: Decimal | None = Decimal("2000000000")

    def __post_init__(self) -> None:
        if self.start_cash <= 0 or self.max_positions < 1:
            raise ValueError("Startkapital und Anzahl Plätze müssen positiv sein")
        if self.holding_period <= timedelta(0) or self.max_signal_age <= timedelta(0):
            raise ValueError("Haltedauer und Signalalter müssen positiv sein")

    @property
    def position_budget(self) -> Decimal:
        return self.start_cash / self.max_positions * COST_BUFFER


@dataclass(frozen=True, slots=True)
class Holding:
    ticker: str
    quantity: Decimal
    opened_at: datetime
    signal_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Decision:
    portfolio: str
    at: datetime
    orders: list[Order]
    # (signal_id, order_id oder None, Grund)
    outcomes: list[tuple[str, str | None, str]]
    signals: dict[str, Signal] = field(repr=False)

    @property
    def briefing(self) -> str:
        return write_briefing(self)


def holdings_from_orders(orders: Iterable[Order]) -> dict[str, Holding]:
    """Aktueller Bestand laut bisherigen Orders (siehe Hinweis im Modultext)."""
    holdings: dict[str, Holding] = {}
    for order in sorted(orders, key=lambda o: (o.created_at, o.id)):
        held = holdings.get(order.ticker)
        if order.side is Side.BUY:
            if held is None:
                holdings[order.ticker] = Holding(
                    order.ticker, order.quantity, order.created_at, order.signal_ids
                )
            else:
                holdings[order.ticker] = Holding(
                    order.ticker,
                    held.quantity + order.quantity,
                    held.opened_at,
                    held.signal_ids + order.signal_ids,
                )
        elif held is not None:
            rest = held.quantity - order.quantity
            if rest > 0:
                holdings[order.ticker] = Holding(order.ticker, rest, held.opened_at, held.signal_ids)
            else:
                del holdings[order.ticker]
    return holdings


def decide(
    portfolio: str,
    signals: Iterable[Signal],
    holdings: dict[str, Holding],
    at: datetime,
    prices: PriceSource,
    rules: DecisionRules = DecisionRules(),
    market_cap: MarketCapLookup | None = None,
) -> Decision:
    signals = [s for s in signals if s.created_at <= at]
    by_id = {s.id: s for s in signals}
    orders: list[Order] = []
    outcomes: list[tuple[str, str | None, str]] = []
    held = dict(holdings)

    # 1. Haltedauer abgelaufen → verkaufen
    for holding in sorted(held.values(), key=lambda h: h.ticker):
        if at - holding.opened_at >= rules.holding_period:
            orders.append(
                Order(
                    portfolio=portfolio,
                    ticker=holding.ticker,
                    side=Side.SELL,
                    quantity=holding.quantity,
                    created_at=at,
                    signal_ids=holding.signal_ids,
                    rationale=(
                        f"Haltedauer von {rules.holding_period.days} Tagen abgelaufen "
                        f"(gekauft am {holding.opened_at.date().isoformat()})."
                    ),
                )
            )
            del held[holding.ticker]

    # 2. Bündeln je Ticker
    groups: dict[str, list[Signal]] = defaultdict(list)
    for signal in signals:
        if signal.side is Side.SELL:
            outcomes.append((signal.id, None, "Verkaufssignale werden noch nicht gehandelt"))
        else:
            groups[signal.ticker].append(signal)

    # 3. Filtern
    candidates: list[tuple[str, list[Signal], Decimal]] = []
    for ticker, group in sorted(groups.items()):
        reason = _rejection(ticker, group, held, at, rules, market_cap)
        price = None
        if reason is None:
            try:
                price = prices.last_at_or_before(ticker, at)[1]
            except NoPriceError:
                reason = "kein aktueller Kurs"
        if reason is None and (rules.position_budget / price) < 1:
            reason = f"Kurs {price} USD zu hoch für das Budget je Position"
        if reason is not None:
            outcomes.extend((s.id, None, reason) for s in group)
        else:
            candidates.append((ticker, group, price))

    # 4. Reihen und kaufen, solange Plätze frei sind
    candidates.sort(
        key=lambda c: (
            -max(s.confidence for s in c[1]),
            -len(c[1]),
            min(s.observed_at for s in c[1]),
            c[0],
        )
    )
    free = rules.max_positions - len(held)
    for rank, (ticker, group, price) in enumerate(candidates, start=1):
        if free <= 0:
            outcomes.extend((s.id, None, f"kein freier Platz (Rang {rank})") for s in group)
            continue
        quantity = (rules.position_budget / price).to_integral_value(rounding=ROUND_DOWN)
        order = Order(
            portfolio=portfolio,
            ticker=ticker,
            side=Side.BUY,
            quantity=quantity,
            created_at=at,
            signal_ids=tuple(s.id for s in group),
            rationale=_buy_rationale(group, price, quantity, rank),
        )
        orders.append(order)
        outcomes.extend((s.id, order.id, f"gekauft (Rang {rank})") for s in group)
        free -= 1

    return Decision(portfolio, at, orders, outcomes, by_id)


def _rejection(ticker, group, held, at, rules, market_cap) -> str | None:
    if at - max(s.observed_at for s in group) > rules.max_signal_age:
        return f"Signal älter als {rules.max_signal_age.days} Tage"
    if max(s.confidence for s in group) < rules.min_confidence:
        return f"Konfidenz unter {rules.min_confidence}"
    if ticker in held:
        return "schon im Depot"
    if rules.max_market_cap is not None and market_cap is not None:
        cap = market_cap(ticker)
        if cap is None:
            return "Börsenwert unbekannt"
        if cap > rules.max_market_cap:
            return f"Börsenwert {_millions(cap)} über Grenze {_millions(rules.max_market_cap)}"
    return None


def _buy_rationale(group: list[Signal], price: Decimal, quantity: Decimal, rank: int) -> str:
    experts = sorted({s.expert for s in group})
    lines = [
        f"Kauf von {quantity} Stück zu etwa {price} USD, Rang {rank}. "
        f"{len(group)} Signal(e) von: {', '.join(experts)}."
    ]
    for s in sorted(group, key=lambda s: s.observed_at):
        lines.append(f"- [{s.expert}, Konfidenz {s.confidence}] {s.summary} Quelle: {s.source_url}")
    return "\n".join(lines)


def _millions(value: Decimal) -> str:
    return f"{(value / 1_000_000).quantize(Decimal('1'))} Mio. USD"


def write_briefing(decision: Decision) -> str:
    """Kurzer Bericht in Markdown: Orders mit Begründung, Ablehnungen nach Grund."""
    lines = [f"# Briefing {decision.portfolio}, {decision.at.isoformat(timespec='minutes')}", ""]
    if decision.orders:
        lines.append("## Orders")
        for order in decision.orders:
            side = "Kauf" if order.side is Side.BUY else "Verkauf"
            lines += ["", f"### {side} {order.ticker}", "", order.rationale]
    else:
        lines.append("Keine Orders.")
    rejected: dict[str, list[str]] = defaultdict(list)
    for signal_id, order_id, reason in decision.outcomes:
        if order_id is None:
            signal = decision.signals.get(signal_id)
            rejected[reason.split(" (")[0]].append(signal.ticker if signal else signal_id)
    if rejected:
        lines += ["", "## Nicht gekauft", ""]
        for reason, tickers in sorted(rejected.items()):
            lines.append(f"- {reason}: {', '.join(sorted(set(tickers)))}")
    return "\n".join(lines) + "\n"


def yahoo_market_cap(ticker: str) -> Decimal | None:
    """Aktueller Börsenwert laut Yahoo Finance (Netzwerkzugriff), None wenn unbekannt."""
    import yfinance as yf

    try:
        value = yf.Ticker(ticker).fast_info["marketCap"]
    except Exception:  # yfinance wirft je nach Fehler sehr verschiedene Ausnahmen
        return None
    if value is None or value != value or value <= 0:  # None, NaN, 0
        return None
    return Decimal(str(value))
