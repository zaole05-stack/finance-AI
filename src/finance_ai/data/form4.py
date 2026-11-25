"""Parser für das XML von SEC Form 4 (Änderung des Aktienbesitzes von Insidern).

Gelesen wird nur die Tabelle der direkten Aktiengeschäfte (`nonDerivativeTable`).
Optionen und andere Derivate bleiben außen vor. Transaktionen ohne
Kurs oder Stückzahl werden übersprungen, weil sich ihr Wert nicht bestimmen lässt.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

_TRUE = {"1", "true"}


@dataclass(frozen=True, slots=True)
class Owner:
    name: str
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    officer_title: str

    @property
    def role(self) -> str:
        roles = []
        if self.is_officer:
            roles.append(self.officer_title or "Officer")
        # Manche Titel enthalten schon "Director", z. B. "Director, CEO".
        if self.is_director and "director" not in self.officer_title.lower():
            roles.append("Director")
        if self.is_ten_percent_owner:
            roles.append("10%-Eigentümer")
        return ", ".join(roles) or "Sonstige"


@dataclass(frozen=True, slots=True)
class Transaction:
    code: str
    acquired: bool
    shares: Decimal
    price: Decimal
    day: date

    @property
    def value(self) -> Decimal:
        return self.shares * self.price


@dataclass(frozen=True, slots=True)
class Form4:
    issuer_cik: str
    issuer_name: str
    ticker: str | None
    owners: tuple[Owner, ...]
    transactions: tuple[Transaction, ...]
    is_10b5_1_plan: bool


def parse_form4(xml: str) -> Form4:
    try:
        root = ET.fromstring(xml.strip())
    except ET.ParseError as error:
        raise ValueError(f"Ungültiges XML: {error}") from error
    if root.tag != "ownershipDocument":
        raise ValueError(f"Kein Form-4-Dokument: <{root.tag}>")
    ticker = _text(root, "issuer/issuerTradingSymbol").upper()
    return Form4(
        issuer_cik=_text(root, "issuer/issuerCik"),
        issuer_name=_text(root, "issuer/issuerName"),
        ticker=ticker if ticker and ticker not in {"NONE", "N/A", "NA"} else None,
        owners=tuple(_owner(node) for node in root.findall("reportingOwner")),
        transactions=tuple(
            tx
            for node in root.findall("nonDerivativeTable/nonDerivativeTransaction")
            if (tx := _transaction(node)) is not None
        ),
        is_10b5_1_plan=_flag(root, "aff10b5One"),
    )


def _owner(node: ET.Element) -> Owner:
    rel = "reportingOwnerRelationship/"
    return Owner(
        name=_text(node, "reportingOwnerId/rptOwnerName"),
        is_director=_flag(node, rel + "isDirector"),
        is_officer=_flag(node, rel + "isOfficer"),
        is_ten_percent_owner=_flag(node, rel + "isTenPercentOwner"),
        officer_title=_text(node, rel + "officerTitle"),
    )


def _transaction(node: ET.Element) -> Transaction | None:
    amounts = "transactionAmounts/"
    shares = _decimal(_text(node, amounts + "transactionShares/value"))
    price = _decimal(_text(node, amounts + "transactionPricePerShare/value"))
    raw_day = _text(node, "transactionDate/value")
    if shares is None or price is None or shares <= 0 or price <= 0 or not raw_day:
        return None
    return Transaction(
        code=_text(node, "transactionCoding/transactionCode").upper(),
        acquired=_text(node, amounts + "transactionAcquiredDisposedCode/value").upper() == "A",
        shares=shares,
        price=price,
        # Manche Meldungen hängen eine Zeitzone an, z. B. "2026-11-24-05:00".
        day=date.fromisoformat(raw_day[:10]),
    )


def _text(node: ET.Element, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _flag(node: ET.Element, path: str) -> bool:
    return _text(node, path).lower() in _TRUE


def _decimal(value: str) -> Decimal | None:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None
