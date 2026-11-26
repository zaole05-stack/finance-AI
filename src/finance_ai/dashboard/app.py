"""Streamlit-Dashboard. Start: `streamlit run src/finance_ai/dashboard/app.py`.

Die Seite liest nur aus der Datenbank (Pfad aus `FINANCE_AI_DB`). Netzwerk gibt
es nur über den Knopf "Kurse aktualisieren". Alle Kennzahlen kommen aus
`finance_ai.dashboard.data`, das wiederum nur `evaluate` aufruft.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import streamlit as st

from finance_ai.core import storage
from finance_ai.core.models import Side
from finance_ai.core.settings import Settings, load_settings, save_settings
from finance_ai.dashboard import data
from finance_ai.decision.agent import DecisionRules
from finance_ai.evaluation.report import TEST_DURATION
from finance_ai.paper_trading.costs import CostModel
from finance_ai.paper_trading.market_data import CachedPriceSource


def pct(value: Decimal) -> str:
    return f"{float(value) * 100:+.2f} %"


def when(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")


def page_overview(view: data.Overview) -> None:
    if view.error:
        st.warning(view.error)
    if view.test_start is None:
        st.info("Noch keine Orders. Der Test beginnt mit der ersten Order.")
        return
    elapsed = (view.at - view.test_start).days
    st.caption(
        f"Teststart {when(view.test_start)} · Tag {elapsed} von {TEST_DURATION.days} · "
        f"Stand {when(view.at)}"
    )
    st.progress(min(elapsed / TEST_DURATION.days, 1.0))
    for w in view.warnings:
        (st.error if w.level == "error" else st.info)(w.text)
    if not view.reports:
        return
    st.dataframe(
        [
            {
                "Portfolio": r.portfolio,
                "Orders": r.orders,
                "Offen (verzögert)": r.pending_delayed,
                "Rendite sofort": pct(r.return_immediate),
                "Rendite verzögert": pct(r.return_delayed),
                "ETF": pct(r.benchmark_return),
                "Vorsprung (verzögert)": pct(r.excess_delayed),
                "Kosten der Freigabe": pct(r.approval_cost),
                "Urteil": str(r.verdict),
            }
            for r in view.reports
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "Renditen nach Gebühren, Slippage und Steuern (Liquidationswert). Maßgeblich "
        "für das Urteil ist die verzögerte Ausführung (1 Stunde Freigabe)."
    )


def page_briefings(conn) -> None:
    names = data.portfolios(conn)
    if not names:
        st.info("Noch keine Entscheidungen.")
        return
    portfolio = st.selectbox("Portfolio", names)
    for i, run in enumerate(data.runs(conn, portfolio)):
        title = f"{when(run.decided_at)} · {len(run.orders)} Orders"
        with st.expander(title, expanded=i == 0):
            for order in run.orders:
                verb = "Kauf" if order.side is Side.BUY else "Verkauf"
                st.markdown(f"#### {verb} {order.quantity.normalize():f} {order.ticker}")
                st.markdown(order.rationale)
            if run.rejected:
                st.markdown("#### Nicht gekauft")
                for reason, rows in sorted(run.rejected.items()):
                    by_ticker: dict[str, list] = {}
                    for r in rows:
                        by_ticker.setdefault(r["ticker"], []).append(r)
                    links = ", ".join(
                        f"[{t}]({rs[0]['source_url']})" + (f" ({len(rs)} Signale)" if len(rs) > 1 else "")
                        for t, rs in by_ticker.items()
                    )
                    st.markdown(f"- **{reason}:** {links}")


def page_signals(conn) -> None:
    signals = storage.list_signals(conn)
    if not signals:
        st.info("Noch keine Signale.")
        return
    st.dataframe(
        [
            {
                "Beobachtet": when(s.observed_at),
                "Experte": s.expert,
                "Ticker": s.ticker,
                "Richtung": str(s.side),
                "Konfidenz": s.confidence,
                "Zusammenfassung": s.summary,
                "Quelle": s.source_url,
            }
            for s in sorted(signals, key=lambda s: s.observed_at, reverse=True)
        ],
        hide_index=True,
        use_container_width=True,
        column_config={"Quelle": st.column_config.LinkColumn("Quelle", display_text="öffnen")},
    )


def page_settings(conn, settings: Settings) -> None:
    rules, costs = settings.rules, settings.costs
    st.caption(
        "Regeln wirken auf künftige Entscheidungen. Startkapital, Kosten, ETF und "
        "Teststart ändern auch die Auswertung rückwirkend."
    )
    with st.form("settings"):
        st.markdown("#### Vergleich")
        benchmark = st.text_input("Vergleichs-ETF (Ticker)", settings.benchmark_ticker)
        fixed_start = st.checkbox("Teststart festlegen (sonst: erste Order)", settings.test_start is not None)
        start_day = st.date_input(
            "Teststart (UTC, 00:00)", (settings.test_start or datetime.now(UTC)).date()
        )

        st.markdown("#### Entscheidungs-Agent")
        c1, c2 = st.columns(2)
        start_cash = c1.number_input("Startkapital (USD)", min_value=100, value=int(rules.start_cash), step=1000)
        max_positions = c2.number_input("Positionen höchstens", min_value=1, max_value=100, value=rules.max_positions)
        holding = c1.number_input("Haltedauer (Tage)", min_value=1, value=rules.holding_period.days)
        max_age = c2.number_input("Signal höchstens so alt (Tage)", min_value=0, value=rules.max_signal_age.days)
        min_conf = c1.slider("Mindest-Konfidenz", 0.0, 1.0, rules.min_confidence, 0.05)
        cap_limit = c2.checkbox("Börsenwert begrenzen", rules.max_market_cap is not None)
        cap_mio = c2.number_input(
            "Börsenwert höchstens (Mio. USD)",
            min_value=1,
            value=int((rules.max_market_cap or Decimal("2e9")) / 1_000_000),
            step=100,
        )

        st.markdown("#### Kosten")
        c3, c4 = st.columns(2)
        fee_fixed = c3.text_input("Gebühr je Order (USD)", f"{costs.fee_fixed}")
        fee_rate = c4.text_input("Gebühr in % des Volumens", f"{costs.fee_rate * 100}")
        slippage = c3.text_input("Slippage in %", f"{costs.slippage_rate * 100}")
        tax = c4.text_input("Steuer auf Gewinne in %", f"{costs.tax_rate * 100}")

        if not st.form_submit_button("Speichern", type="primary"):
            return
    try:
        new = Settings(
            benchmark_ticker=benchmark,
            test_start=datetime.combine(start_day, time(), UTC) if fixed_start else None,
            rules=DecisionRules(
                start_cash=Decimal(int(start_cash)),
                max_positions=int(max_positions),
                holding_period=timedelta(days=int(holding)),
                max_signal_age=timedelta(days=int(max_age)),
                min_confidence=float(min_conf),
                max_market_cap=Decimal(int(cap_mio)) * 1_000_000 if cap_limit else None,
            ),
            costs=CostModel(
                fee_fixed=Decimal(fee_fixed.replace(",", ".")),
                fee_rate=Decimal(fee_rate.replace(",", ".")) / 100,
                slippage_rate=Decimal(slippage.replace(",", ".")) / 100,
                tax_rate=Decimal(tax.replace(",", ".")) / 100,
            ),
        )
    except (ValueError, ArithmeticError) as error:
        st.error(f"Nicht gespeichert: {error}")
        return
    save_settings(conn, new)
    st.success("Gespeichert.")
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="finance-AI", layout="wide")
    path = data.database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = storage.connect(path)
    settings = load_settings(conn)
    prices = CachedPriceSource(conn)

    with st.sidebar:
        st.markdown("### finance-AI")
        st.caption(f"Datenbank: `{path}`")
        st.caption(f"Vergleich: {settings.benchmark_ticker}")
        if st.button("Kurse aktualisieren", help="Lädt Stundenkurse von Yahoo ab Teststart."):
            with st.spinner("Lade Kurse …"):
                missing = data.refresh_prices(conn, settings, prices, datetime.now(UTC))
            if missing:
                st.warning("Keine Kurse für: " + ", ".join(missing))
            else:
                st.success("Kurse aktuell.")

    overview, briefings, signals, config = st.tabs(["Übersicht", "Briefings", "Signale", "Einstellungen"])
    with overview:
        page_overview(data.overview(conn, settings, prices))
    with briefings:
        page_briefings(conn)
    with signals:
        page_signals(conn)
    with config:
        page_settings(conn, settings)


main()
