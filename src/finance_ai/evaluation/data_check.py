"""Datencheck vor dem Backtest (Plan-Schritt 4b): Taugen die Daten?

Gemessen wird nur die Datenqualität, **keine Renditen**. Für die Signale nach
den Insider-Grundregeln eines Jahres wird gezählt, wie viele Kurse haben, wie
viele erst über das heutige Kürzel gefunden werden und was mit den übrigen
geschah (fünf Fälle aus `MissingPrice`).

Entscheidend ist der Anteil, der in der mittleren Stufe mit −55 % eingeht
(Pleite, Grund unbekannt, keine Meldung). Er verschiebt den mittleren Vorsprung
um etwa 0,55 × Anteil. Es zählt das schlechtere der geprüften Jahre:
bis 10 % weiter, bis 20 % weiter mit Warnung, darüber Stopp.

Aufruf (lädt Daten von SEC und Yahoo, das dauert):
    python -m finance_ai.evaluation.data_check 2008 2015
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Protocol

from finance_ai.data.sec_company import CompanyInfo, MissingPrice
from finance_ai.data.sec_insider_datasets import DatasetFiling
from finance_ai.evaluation.backtest import (
    ANY_OPERATING_SIC,
    StorePrices,
    insider_signal,
    price_outcome,
)
from finance_ai.paper_trading.daily_prices import PriceCheck, PriceStatus

WARN_SHARE = 0.10
STOP_SHARE = 0.20
AT_MINUS_55 = frozenset({MissingPrice.BANKRUPTCY, MissingPrice.UNKNOWN, MissingPrice.NO_EVENT})

log = logging.getLogger(__name__)


class Prices(Protocol):
    def check(self, ticker: str, info: CompanyInfo, day: date, price) -> PriceCheck: ...

    def last_bar_day(self, ticker: str) -> date | None: ...


class Verdict(Enum):
    CONTINUE = "weiter mit Schritt 5–9"
    WARN = "weiter, mit Warnung im Bericht"
    STOP = "Stopp, im Team andere Wege besprechen"


@dataclass
class YearReport:
    year: int | None = None
    signals: int = 0
    with_price: int = 0
    via_current_ticker: int = 0
    mismatch: int = 0
    no_company: int = 0
    at_minus_55: int = 0
    cases: dict[MissingPrice, int] = field(default_factory=dict)

    @property
    def share_at_minus_55(self) -> float:
        return self.at_minus_55 / self.signals if self.signals else 0.0

    @property
    def share_with_price(self) -> float:
        return self.with_price / self.signals if self.signals else 0.0

    @property
    def per_week(self) -> float:
        return self.signals / 52


def check_filings(
    filings: Iterable[DatasetFiling],
    company_for: Callable[[str], CompanyInfo | None],
    prices: Prices,
    holding: timedelta,
    year: int | None = None,
) -> YearReport:
    report = YearReport(year=year)
    cases: Counter[MissingPrice] = Counter()
    now = datetime.now(UTC)
    for filing in filings:
        if insider_signal(filing, ANY_OPERATING_SIC, now) is None:
            continue  # Regeln ohne Branchencode schon nicht erfüllt, Firma nicht laden
        info = company_for(filing.issuer_cik)
        if info is None:
            report.no_company += 1
            continue
        if insider_signal(filing, info.sic, now) is None:
            continue
        report.signals += 1
        outcome = price_outcome(filing, info, prices, holding)
        if outcome.with_price:
            report.with_price += 1
            report.via_current_ticker += outcome.check.via_current_ticker
            continue
        report.mismatch += outcome.check.status is PriceStatus.MISMATCH
        cases[outcome.missing_case] += 1
    report.cases = dict(cases)
    report.at_minus_55 = sum(n for case, n in cases.items() if case in AT_MINUS_55)
    if log.isEnabledFor(logging.INFO):
        log.info("Jahr %s: %d Signale, %.1f %% mit −55 %%", year, report.signals,
                 100 * report.share_at_minus_55)
    return report


def verdict(share_at_minus_55: float) -> Verdict:
    if share_at_minus_55 <= WARN_SHARE:
        return Verdict.CONTINUE
    if share_at_minus_55 <= STOP_SHARE:
        return Verdict.WARN
    return Verdict.STOP


def overall_verdict(reports: Iterable[YearReport]) -> Verdict:
    """Es zählt das schlechtere Jahr."""
    return verdict(max(r.share_at_minus_55 for r in reports))


def markdown(reports: list[YearReport], holding: timedelta) -> str:
    def pct(part: int, whole: int) -> str:
        return f"{100 * part / whole:.1f} %" if whole else "–"

    lines = [
        f"Haltedauer für „verschwand in der Haltedauer“: {holding.days} Tage.",
        "",
        "| Jahr | Signale | pro Woche | mit Kurs | davon über heutiges Kürzel "
        "| Kurs passt nicht | ohne Firmendaten | mit −55 % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| {r.year} | {r.signals} | {r.per_week:.1f} | {pct(r.with_price, r.signals)} "
            f"| {r.via_current_ticker} | {r.mismatch} | {r.no_company} "
            f"| **{pct(r.at_minus_55, r.signals)}** |"
        )
    lines += ["", "| Jahr | " + " | ".join(c.value for c in MissingPrice) + " |",
              "|---" * (len(MissingPrice) + 1) + "|"]
    for r in reports:
        lines.append(f"| {r.year} | " + " | ".join(
            f"{r.cases.get(c, 0)} ({pct(r.cases.get(c, 0), r.signals)})" for c in MissingPrice
        ) + " |")
    lines += ["", f"**Ergebnis:** {overall_verdict(reports).value} "
                  "(maßgeblich ist das schlechtere Jahr)."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    from finance_ai.config import sec_user_agent
    from finance_ai.data.sec_company import load_company
    from finance_ai.data.sec_edgar import EdgarClient
    from finance_ai.data.sec_insider_datasets import download_quarters, read_quarter
    from finance_ai.decision.agent import DecisionRules
    from finance_ai.paper_trading.daily_prices import DailyPriceStore

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("years", nargs="+", type=int)
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    client = EdgarClient(sec_user_agent())
    holding = DecisionRules().holding_period
    companies: dict[str, CompanyInfo | None] = {}

    def company_for(cik: str) -> CompanyInfo | None:
        if cik not in companies:
            companies[cik] = load_company(client, cik, args.data / "raw" / "companies")
            if len(companies) % 100 == 0:
                log.info("%d Firmen geladen", len(companies))
        return companies[cik]

    reports = []
    with DailyPriceStore(args.data / "prices_daily.sqlite") as store:
        for year in args.years:
            quarters = {f"{year}q{q}" for q in range(1, 5)}
            paths = download_quarters(client, args.data / "raw", only=quarters)
            filings = (f for path in paths for f in read_quarter(path))
            reports.append(check_filings(filings, company_for, StorePrices(store), holding, year))

    text = markdown(reports, holding)
    (args.data / "data_check.md").write_text(text, encoding="utf-8")
    (args.data / "data_check.json").write_text(
        json.dumps([{**asdict(r), "cases": {c.name: n for c, n in r.cases.items()}}
                    for r in reports], indent=1),
        encoding="utf-8",
    )
    print(text)


if __name__ == "__main__":
    main()
