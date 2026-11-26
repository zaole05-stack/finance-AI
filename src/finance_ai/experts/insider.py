"""Insider-Experte: Käufe von Vorständen und Aufsichtsräten an der Börse (SEC Form 4).

Grundlage: Insider-Käufe sagen künftige Renditen voraus, deutlich stärker
als Verkäufe und stärker bei kleinen Firmen (Lakonishok & Lee 2001, Review of
Financial Studies). Planmäßige, sich jährlich wiederholende Geschäfte tragen
kaum Information (Cohen, Malloy & Pomorski 2012, Journal of Finance).

Regeln für ein Signal:
- Nur Transaktionscode P (Kauf an der Börse oder privat), nur Zugänge.
  Zuteilungen, Optionsausübungen und Verkäufe zählen nicht.
- Nur Officers und Directors. Reine 10%-Eigentümer sind meist Fonds und
  gehören zum Fonds-Experten.
- Keine Käufe aus einem vorab festgelegten 10b5-1-Plan.
- Mindestwert je Meldung (Standard 25.000 USD), damit symbolische Käufe
  nicht zählen.
- Keine Fonds, BDCs, REITs, Royalty Trusts oder SPACs. Erkannt am Branchencode
  (SIC) im Kopf der Meldung. Fehlt der Code, ist es fast immer ein Fonds oder
  eine BDC, deshalb fällt die Meldung dann ebenfalls weg.
- Ein Signal je Meldung. Mehrere Käufe derselben Meldung werden summiert.

Konfidenz als Rangfolge, nicht als Wahrscheinlichkeit: Käufe der obersten
Führung (CEO, CFO, President, Chair, COO) 0,6, übrige Officers und Directors
0,5. Grundlage ist die Informations-Hierarchie, nach der die oberste Führung
am besten informiert ist (Seyhun 1986, Journal of Financial Economics). Die
Werte sind gesetzt, nicht geschätzt. Die Schattenbewertung soll sie später
bestätigen oder verwerfen.

Zwei Wege zu den Meldungen: `scan_recent` liest den Atom-Feed und liefert
Signale Minuten nach der Meldung. `scan_day` liest den Tagesindex und holt
ganze vergangene Tage nach.

Noch nicht umgesetzt: Erkennung routinemäßiger Käufer nach Cohen et al.
(braucht mehrere Jahre Historie je Person). Der Filter auf kleine Firmen
sitzt im Entscheidungs-Agenten, weil er einen aktuellen Börsenwert braucht.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from decimal import Decimal

from finance_ai.core.models import Side, Signal
from finance_ai.data.form4 import Form4, parse_form4
from finance_ai.data.sec_edgar import (
    EdgarClient,
    Filing,
    fetch_filing,
    form4_filings,
    recent_form4_filings,
)

EXPERT = "insider"
DEFAULT_MIN_VALUE = Decimal("25000")
TOP_EXECUTIVE_CONFIDENCE = 0.6
DEFAULT_CONFIDENCE = 0.5
# Branchencodes ohne operatives Geschäft: Fonds, SPACs, Royalty Trusts, REITs.
EXCLUDED_SIC = frozenset({"6722", "6726", "6770", "6792", "6795", "6798", "6799"})
_TOP_TITLES = ("ceo", "chief executive", "cfo", "chief financial", "president",
               "chair", "coo", "chief operating")

log = logging.getLogger(__name__)
Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


def signal_from_filing(
    filing: Filing,
    created_at: datetime,
    min_value: Decimal = DEFAULT_MIN_VALUE,
) -> Signal | None:
    """Ein Kaufsignal, wenn die Meldung alle Regeln erfüllt, sonst None."""
    if filing.issuer_sic is None or filing.issuer_sic in EXCLUDED_SIC:
        return None  # vor dem Parsen, das spart Zeit bei Fonds
    return signal_from_form4(
        parse_form4(filing.xml),
        accession=filing.ref.accession,
        source_url=filing.ref.index_url,
        observed_at=filing.accepted_at,
        issuer_sic=filing.issuer_sic,
        created_at=created_at,
        min_value=min_value,
    )


def signal_from_form4(
    doc: Form4,
    *,
    accession: str,
    source_url: str,
    observed_at: datetime,
    issuer_sic: str | None,
    created_at: datetime,
    min_value: Decimal = DEFAULT_MIN_VALUE,
) -> Signal | None:
    """Die Regeln des Insider-Experten auf eine gelesene Meldung.

    Gilt für beide Wege: live (XML einer Einreichung) und im Backtest
    (Zeilen der Quartals-Datensätze der SEC). So kann der Backtest nicht
    still mit anderen Regeln rechnen als der Testlauf.
    """
    if issuer_sic is None or issuer_sic in EXCLUDED_SIC:
        return None
    insiders = [o for o in doc.owners if o.is_officer or o.is_director]
    if doc.ticker is None or doc.is_10b5_1_plan or not insiders:
        return None
    buys = [t for t in doc.transactions if t.code == "P" and t.acquired]
    if not buys:
        return None
    shares = sum((t.shares for t in buys), Decimal(0))
    value = sum((t.value for t in buys), Decimal(0))
    if value < min_value:
        return None
    return Signal(
        id=f"{EXPERT}:{accession}",
        expert=EXPERT,
        ticker=doc.ticker,
        side=Side.BUY,
        source_url=source_url,
        summary=_summary(doc, insiders[0], shares, value, min(t.day for t in buys),
                         max(t.day for t in buys)),
        observed_at=observed_at,
        created_at=created_at,
        confidence=_confidence(insiders),
    )


def _confidence(insiders) -> float:
    titles = " ".join(o.officer_title.lower() for o in insiders if o.is_officer)
    # "president" steckt auch in "Vice President". Das ist keine oberste Führung.
    titles = titles.replace("vice president", "")
    top = any(word in titles for word in _TOP_TITLES)
    return TOP_EXECUTIVE_CONFIDENCE if top else DEFAULT_CONFIDENCE


def scan_day(
    client: EdgarClient,
    day: date,
    min_value: Decimal = DEFAULT_MIN_VALUE,
    clock: Clock = _now,
) -> list[Signal]:
    """Prüft alle Form-4-Meldungen eines Tages. Bei ~600 Meldungen dauert das gut eine Minute."""
    return list(_scan(client, form4_filings(client, day), min_value, clock))


def scan_recent(
    client: EdgarClient,
    since: datetime,
    min_value: Decimal = DEFAULT_MIN_VALUE,
    clock: Clock = _now,
) -> list[Signal]:
    """Prüft die Form-4-Meldungen seit `since` aus dem Atom-Feed der SEC.

    Für regelmäßige Abrufe im Abstand von Minuten. Signale kommen so wenige
    Minuten nach der Meldung statt erst am nächsten Tag. Überschneidende
    Zeiträume sind unschädlich, weil gespeicherte Signale nicht doppelt
    angelegt werden. Lücken über mehr als einen Geschäftstag holt `scan_day` nach.
    """
    return list(_scan(client, recent_form4_filings(client, since), min_value, clock))


def _scan(client, refs, min_value, clock) -> Iterable[Signal]:
    for ref in refs:
        try:
            filing = fetch_filing(client, ref)
            signal = signal_from_filing(filing, clock(), min_value) if filing else None
        except (ValueError, OSError) as error:
            # Kaputte Meldung oder Netzfehler trotz Wiederholung: Rest des Tages
            # trotzdem prüfen. Ein erneuter Lauf holt Fehlendes nach, ohne Duplikate.
            log.warning("Meldung %s übersprungen: %s", ref.accession, error)
            continue
        if signal is not None:
            yield signal


def _summary(doc: Form4, owner, shares: Decimal, value: Decimal, first: date, last: date) -> str:
    average = (value / shares).quantize(Decimal("0.0001"))
    days = first.isoformat() if first == last else f"{first.isoformat()} bis {last.isoformat()}"
    others = len([o for o in doc.owners if o is not owner])
    joint = f" (gemeinsame Meldung mit {others} weiteren)" if others else ""
    return (
        f"{owner.name} ({owner.role}){joint} kaufte {shares.normalize():f} Aktien von "
        f"{doc.issuer_name} ({doc.ticker}) zu durchschnittlich {average:f} USD, "
        f"zusammen {value.quantize(Decimal('1')):f} USD, am {days}."
    )
