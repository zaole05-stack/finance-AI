"""Firmendaten von der SEC je CIK: Branchencode, Kürzel, Aktienzahl, Ereignisse.

Zwei kostenlose Schnittstellen der SEC (gleicher User-Agent wie bei EDGAR):
- `submissions`: Stammdaten (SIC, heutige Kürzel) und die Liste aller Meldungen.
  Ältere Meldungen stehen in weiteren Dateien, die mitgeladen werden.
- `companyfacts`: XBRL-Angaben aus den Berichten. Gebraucht wird nur die
  Aktienzahl, für den damaligen Börsenwert im Backtest.

Grenzen:
- XBRL gibt es erst ab 2009/2010 für große und ab Mitte 2011 für kleine Firmen.
  Davor ist die Aktienzahl unbekannt.
- Die Aktienzahl gilt vor späteren Splits. Der Börsenwert braucht deshalb den
  damaligen, nicht split-bereinigten Kurs.
- Der Branchencode ist der heutige, nicht der damalige.

Zwischengespeichert wird nur der Auszug je Firma (wenige KB) als JSON, nicht die
vollständigen Antworten. Diese sind bei großen Firmen mehrere MB groß.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Protocol

SUBMISSIONS = "https://data.sec.gov/submissions/"
COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/"
# Ältere Aktienzahlen gelten als unbekannt (Quartalsberichte plus Verspätung).
MAX_SHARES_AGE = timedelta(days=400)
# Meldungen, an denen sich später ablesen lässt, warum eine Aktie verschwand.
# S-4 und 425 fehlen bewusst: Sie reicht oft der Käufer ein, nicht das Ziel.
EVENT_FORMS = frozenset({
    "25", "25-NSE", "15-12B", "15-12G", "15-15D",  # Delisting, Abmeldung
    "DEFM14A", "DEFM14C", "PREM14A", "SC TO-T", "SC 14D9", "SC 13E3",  # Übernahme
})
BANKRUPTCY_ITEM = "1.03"  # 8-K Punkt 1.03: Insolvenz oder Zwangsverwaltung
BANKRUPTCY_FORM = f"8-K {BANKRUPTCY_ITEM}"
TAKEOVER_FORMS = frozenset({"DEFM14A", "DEFM14C", "PREM14A", "SC TO-T", "SC 14D9", "SC 13E3"})


class VanishReason(Enum):
    """Warum es für eine Aktie keine Kurse mehr gibt (für die drei Stufen im Backtest)."""

    TAKEOVER = "Übernahme"
    BANKRUPTCY = "Pleite"
    UNKNOWN = "unbekannt"


class Client(Protocol):
    def get(self, url: str) -> str | None: ...


@dataclass(frozen=True, slots=True, order=True)
class Event:
    day: date
    form: str  # Formtyp, bei Insolvenz "8-K 1.03"


@dataclass(frozen=True, slots=True)
class ShareCount:
    filed: date  # eingereicht am
    end: date  # Stichtag der Angabe
    shares: int
    cover_page: bool  # dei (Deckblatt) statt us-gaap (Bilanz)


@dataclass(frozen=True, slots=True)
class CompanyInfo:
    cik: str
    sic: str | None
    tickers: tuple[str, ...]
    shares: tuple[ShareCount, ...]
    events: tuple[Event, ...]

    def shares_at(self, day: date) -> int | None:
        """Aktienzahl laut dem jüngsten Bericht, der vor `day` eingereicht war.

        Vorrang hat die Angabe vom Deckblatt (dei). Unter mehreren Angaben gilt
        die mit dem jüngsten Stichtag, denn Berichte enthalten auch Vorjahreswerte.
        Ist der Stichtag älter als `MAX_SHARES_AGE`, gilt die Zahl als unbekannt.
        """
        for cover_page in (True, False):
            known = [s for s in self.shares if s.cover_page is cover_page and s.filed < day]
            if known:
                best = max(known, key=lambda s: (s.end, s.filed))
                if day - best.end <= MAX_SHARES_AGE:
                    return best.shares
        return None

    def vanish_reason(self, after: date) -> VanishReason:
        """Grund nach den Meldungen nach `after`. Insolvenz hat Vorrang vor Übernahme,
        denn auch wer nach der Pleite verkauft wird, war für Aktionäre pleite."""
        later = {e.form for e in self.events if e.day > after}
        if BANKRUPTCY_FORM in later:
            return VanishReason.BANKRUPTCY
        if later & TAKEOVER_FORMS:
            return VanishReason.TAKEOVER
        return VanishReason.UNKNOWN


def company_from_json(
    submissions: dict, facts: dict | None, older: list[dict]
) -> CompanyInfo:
    """Auszug aus den Antworten der SEC. `older` sind die weiteren Meldungslisten."""
    events: set[Event] = set()
    for block in [submissions["filings"]["recent"], *older]:
        items = block.get("items") or [""] * len(block["form"])
        for form, day, item in zip(block["form"], block["filingDate"], items):
            if form in EVENT_FORMS:
                events.add(Event(date.fromisoformat(day), form))
            elif form == "8-K" and BANKRUPTCY_ITEM in (item or "").split(","):
                events.add(Event(date.fromisoformat(day), BANKRUPTCY_FORM))
    return CompanyInfo(
        cik=f"{int(submissions['cik']):010d}",
        sic=str(submissions.get("sic") or "").strip() or None,
        tickers=tuple(submissions.get("tickers") or ()),
        shares=_shares(facts),
        events=tuple(sorted(events)),
    )


def _shares(facts: dict | None) -> tuple[ShareCount, ...]:
    if not facts:
        return ()
    counts = set()
    for namespace, tag, cover_page in (
        ("dei", "EntityCommonStockSharesOutstanding", True),
        ("us-gaap", "CommonStockSharesOutstanding", False),
    ):
        entries = facts.get("facts", {}).get(namespace, {}).get(tag, {})
        for entry in entries.get("units", {}).get("shares", []):
            if entry.get("val") and entry["val"] > 0:
                counts.add(ShareCount(
                    date.fromisoformat(entry["filed"]),
                    date.fromisoformat(entry["end"]),
                    int(entry["val"]),
                    cover_page,
                ))
    return tuple(sorted(counts, key=lambda s: (s.filed, s.end, s.cover_page)))


def load_company(client: Client, cik: str, cache_dir: Path) -> CompanyInfo | None:
    """Firmendaten aus dem Zwischenspeicher oder von der SEC. None, wenn unbekannt."""
    padded = f"{int(cik):010d}"
    cache = cache_dir / f"CIK{padded}.json"
    if cache.exists():
        return _from_cache(json.loads(cache.read_text(encoding="utf-8")))
    raw = client.get(f"{SUBMISSIONS}CIK{padded}.json")
    if not raw:
        return None
    submissions = json.loads(raw)
    older = []
    for file in submissions["filings"].get("files", []):
        text = client.get(SUBMISSIONS + file["name"])
        if text:
            older.append(json.loads(text))
    facts_raw = client.get(f"{COMPANY_FACTS}CIK{padded}.json")
    info = company_from_json(submissions, json.loads(facts_raw) if facts_raw else None, older)
    cache_dir.mkdir(parents=True, exist_ok=True)
    partial = cache.with_suffix(".part")
    partial.write_text(json.dumps(asdict(info), default=str), encoding="utf-8")
    partial.replace(cache)
    return info


def _from_cache(data: dict) -> CompanyInfo:
    return CompanyInfo(
        cik=data["cik"],
        sic=data["sic"],
        tickers=tuple(data["tickers"]),
        shares=tuple(
            ShareCount(date.fromisoformat(s["filed"]), date.fromisoformat(s["end"]),
                       s["shares"], s["cover_page"])
            for s in data["shares"]
        ),
        events=tuple(Event(date.fromisoformat(e["day"]), e["form"]) for e in data["events"]),
    )
