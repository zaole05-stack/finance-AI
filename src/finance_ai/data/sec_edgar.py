"""Abruf von Form-4-Meldungen aus SEC EDGAR (kostenlos, öffentlich).

Ablauf: Der tägliche Index `form.YYYYMMDD.idx` listet alle Meldungen eines
Tages. Für jede Form-4-Meldung wird die vollständige Einreichung (`.txt`)
geladen. Sie enthält die Annahmezeit (`ACCEPTANCE-DATETIME`, US-Ostküstenzeit)
und das XML der Meldung.

Die SEC verlangt einen User-Agent mit Kontaktangabe und höchstens
10 Anfragen pro Sekunde. Der Client hält 8 pro Sekunde ein.

Der Tagesindex erscheint erst nach Tagesende. Signale kommen damit bis zu einen
Tag nach der Veröffentlichung. Das zeigt sich ehrlich im Abstand zwischen
`observed_at` und `created_at` jedes Signals.

Schneller geht es über den Atom-Feed der neuesten Meldungen (`getcurrent`).
Er zeigt eine Meldung Minuten nach der Annahme. Zwei Eigenheiten des Feeds:
- `type=4` filtert nur nach Präfix. Der Feed enthält deshalb auch 424B2, 425,
  40-F/A usw. Gezählt wird nur der Formtyp genau `4`.
- Jede Meldung steht mehrfach im Feed, einmal als Emittent (Issuer) und einmal
  je meldender Person (Reporting). Verwendet wird die CIK des Emittenten.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

ARCHIVES = "https://www.sec.gov/Archives/"
CURRENT_FEED = "https://www.sec.gov/cgi-bin/browse-edgar"
EASTERN = ZoneInfo("America/New_York")
MIN_INTERVAL_SECONDS = 0.125
FEED_PAGE_SIZE = 100
FEED_MAX_PAGES = 30

_ATOM = {"a": "http://www.w3.org/2005/Atom"}
_FEED_TITLE = re.compile(r"\((\d{10})\) \((\w+)\)\s*$")
_FEED_ID = re.compile(r"accession-number=(\d{10}-\d{2}-\d{6})")

log = logging.getLogger(__name__)

_ACCEPTANCE = re.compile(r"<ACCEPTANCE-DATETIME>(\d{14})")
_XML = re.compile(r"<XML>\s*(.*?)\s*</XML>", re.DOTALL)
_ACCESSION = re.compile(r"(\d{10}-\d{2}-\d{6})\.txt$")
_ISSUER_BLOCK = re.compile(r"^ISSUER:(.*?)(?=^\S|\Z)", re.MULTILINE | re.DOTALL)
_SIC = re.compile(r"STANDARD INDUSTRIAL CLASSIFICATION:[^\[\n]*\[(\d{4})\]")


class EdgarClient:
    """HTTP-Zugriff auf EDGAR mit Pflicht-User-Agent und Ratenbegrenzung."""

    def __init__(
        self,
        user_agent: str,
        min_interval: float = MIN_INTERVAL_SECONDS,
        retries: int = 3,
        backoff: float = 2.0,
    ):
        if "@" not in user_agent:
            raise ValueError("Der User-Agent braucht eine Kontaktadresse")
        self._user_agent = user_agent
        self._min_interval = min_interval
        self._retries = retries
        self._backoff = backoff
        self._last_request = 0.0

    def get(self, url: str) -> str | None:
        """Text der Seite, oder None bei 404 (z. B. kein Index an Feiertagen).

        Abgebrochene Verbindungen sowie HTTP 429 und 5xx werden mit wachsender
        Wartezeit wiederholt. Bleibt der Fehler, wird er weitergereicht.
        """
        for attempt in range(self._retries + 1):
            try:
                return self._get_once(url)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                if (error.code != 429 and error.code < 500) or attempt == self._retries:
                    raise
            except OSError:  # Verbindungsabbruch, Zeitüberschreitung
                if attempt == self._retries:
                    raise
            time.sleep(self._backoff * 2**attempt)
        raise AssertionError("unerreichbar")

    def _get_once(self, url: str) -> str:
        wait = self._last_request + self._min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(
            url, headers={"User-Agent": self._user_agent, "Accept-Encoding": "identity"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        finally:
            self._last_request = time.monotonic()


@dataclass(frozen=True, slots=True)
class FilingRef:
    """Verweis auf eine Meldung aus dem Tagesindex."""

    accession: str
    cik: str
    path: str

    @property
    def txt_url(self) -> str:
        return ARCHIVES + self.path

    @property
    def index_url(self) -> str:
        """Übersichtsseite der Meldung: der Quellenlink für Signale."""
        folder = self.accession.replace("-", "")
        return f"{ARCHIVES}edgar/data/{int(self.cik)}/{folder}/{self.accession}-index.htm"


@dataclass(frozen=True, slots=True)
class Filing:
    ref: FilingRef
    accepted_at: datetime
    xml: str
    # Branchencode des Emittenten. Fehlt meist bei Fonds und BDCs.
    issuer_sic: str | None = None


def daily_index_url(day: date) -> str:
    quarter = (day.month - 1) // 3 + 1
    return f"{ARCHIVES}edgar/daily-index/{day.year}/QTR{quarter}/form.{day:%Y%m%d}.idx"


def parse_form4_index(text: str) -> list[FilingRef]:
    """Form-4-Einträge aus einem Tagesindex, je Meldung nur einmal.

    Eine Meldung steht oft mehrfach im Index (einmal je beteiligter Person oder
    Firma). Amendments (4/A) werden ignoriert.
    """
    refs: dict[str, FilingRef] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] != "4":
            continue
        path, cik = parts[-1], parts[-3]
        match = _ACCESSION.search(path)
        if match and cik.isdigit():
            refs.setdefault(match.group(1), FilingRef(match.group(1), cik, path))
    return list(refs.values())


def parse_submission(ref: FilingRef, text: str) -> Filing:
    """Annahmezeit und XML aus der vollständigen Einreichung."""
    accepted = _ACCEPTANCE.search(text)
    xml = _XML.search(text)
    if accepted is None or xml is None:
        raise ValueError(f"Meldung {ref.accession} hat keine Annahmezeit oder kein XML")
    accepted_at = datetime.strptime(accepted.group(1), "%Y%m%d%H%M%S").replace(tzinfo=EASTERN)
    return Filing(ref, accepted_at, xml.group(1), _issuer_sic(text))


def _issuer_sic(text: str) -> str | None:
    header = text.split("</SEC-HEADER>", 1)[0]
    block = _ISSUER_BLOCK.search(header)
    sic = _SIC.search(block.group(1)) if block else None
    return sic.group(1) if sic else None


def form4_filings(client: EdgarClient, day: date) -> list[FilingRef]:
    text = client.get(daily_index_url(day))
    return parse_form4_index(text) if text else []


def fetch_filing(client: EdgarClient, ref: FilingRef) -> Filing | None:
    text = client.get(ref.txt_url)
    return parse_submission(ref, text) if text else None


@dataclass(frozen=True, slots=True)
class FeedEntry:
    """Eine Form-4-Meldung aus dem Atom-Feed, mit dem Zeitpunkt des Eintrags."""

    ref: FilingRef
    updated: datetime


def current_feed_url(start: int = 0, count: int = FEED_PAGE_SIZE) -> str:
    return (
        f"{CURRENT_FEED}?action=getcurrent&type=4&owner=include"
        f"&count={count}&start={start}&output=atom"
    )


@dataclass(frozen=True, slots=True)
class FeedPage:
    """Eine Seite des Atom-Feeds."""

    entries: list[FeedEntry]  # nur Form 4, je Meldung einmal, neueste zuerst
    size: int  # alle Einträge der Seite, auch andere Formtypen
    oldest: datetime | None  # ältester Eintrag der Seite, gleich welcher Formtyp


def parse_current_feed(text: str) -> FeedPage:
    """Liest eine Seite des Atom-Feeds der neuesten Meldungen."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError(f"Atom-Feed nicht lesbar: {error}") from error
    raw = root.findall("a:entry", _ATOM)
    entries: dict[str, FeedEntry] = {}
    issuer_seen: set[str] = set()
    oldest: datetime | None = None
    for entry in raw:
        stamp = entry.findtext("a:updated", "", _ATOM)
        if not stamp:
            continue
        updated = datetime.fromisoformat(stamp)
        oldest = updated if oldest is None else min(oldest, updated)
        category = entry.find("a:category", _ATOM)
        if category is None or category.get("term") != "4":
            continue
        title = _FEED_TITLE.search(entry.findtext("a:title", "", _ATOM))
        accession = _FEED_ID.search(entry.findtext("a:id", "", _ATOM))
        if title is None or accession is None:
            continue
        cik, role = title.group(1), title.group(2)
        number = accession.group(1)
        # Erster Eintrag gewinnt, ein späterer Issuer-Eintrag ersetzt aber eine Person.
        if number in entries and (role != "Issuer" or number in issuer_seen):
            continue
        if role == "Issuer":
            issuer_seen.add(number)
        ref = FilingRef(number, cik, f"edgar/data/{int(cik)}/{number}.txt")
        entries[number] = FeedEntry(ref, updated)
    return FeedPage(list(entries.values()), len(raw), oldest)


def recent_form4_filings(
    client: EdgarClient,
    since: datetime,
    max_pages: int = FEED_MAX_PAGES,
    page_size: int = FEED_PAGE_SIZE,
) -> list[FilingRef]:
    """Form-4-Meldungen aus dem Atom-Feed, die seit `since` eingegangen sind.

    Blättert, bis ein Eintrag älter als `since` ist oder der Feed endet. Der
    Feed reicht nur etwa einen Geschäftstag zurück. Für ältere Tage bleibt der
    Tagesindex (`form4_filings`).
    """
    refs: dict[str, FilingRef] = {}
    for page in range(max_pages):
        text = client.get(current_feed_url(start=page * page_size, count=page_size))
        if not text:
            break
        feed = parse_current_feed(text)
        for entry in feed.entries:
            if entry.updated >= since:
                refs.setdefault(entry.ref.accession, entry.ref)
        if feed.size < page_size or (feed.oldest is not None and feed.oldest < since):
            break
    else:
        log.warning("Atom-Feed nach %d Seiten nicht bis %s gelesen", max_pages, since)
    return list(refs.values())
