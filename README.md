# finance-AI

Spezialisierte KI-Agenten recherchieren Insider-Käufe, Fonds-Positionen,
Politiker-Trades und Social Media. Ein Entscheidungs-Agent handelt daraus auf
einem Portfolio, zunächst nur im Paper Trading gegen einen Small-Cap-ETF.

- [Konzept](docs/KONZEPT.md): was festgelegt ist und was offen ist
- [Plan](docs/PLAN.md): Struktur, Datenquellen, Meilensteine

Status: M0 (Fundament), M1 (Paper-Trading-Engine mit echten Stundenkursen), M2 (Insider-Experte auf SEC Form 4), M3 (Entscheidungs-Agent mit Schattenbewertung) und M4 (Dashboard) fertig.

## Entwicklung

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

Für Abrufe bei der SEC wird ein User-Agent mit Name und E-Mail-Adresse
gebraucht (Vorgabe der SEC). Dazu `.env.example` nach `.env` kopieren und
`SEC_USER_AGENT` ausfüllen. Die `.env` wird nicht committet.

## Dashboard

```powershell
.venv\Scripts\streamlit run src/finance_ai/dashboard/app.py
```

Die Datenbank liegt unter `data/finance_ai.sqlite`, ein anderer Pfad geht über
die Umgebungsvariable `FINANCE_AI_DB`. Tabs: Übersicht (Rendite je Portfolio
sofort und verzögert gegen den ETF, Warnungen), Briefings, Signale und
Einstellungen. Der Knopf „Kurse aktualisieren“ lädt Stundenkurse von Yahoo,
sonst greift das Dashboard nicht aufs Netz zu.

Tests mit Internetzugriff (Yahoo Finance, SEC EDGAR) laufen nur auf Wunsch:

```powershell
.venv\Scripts\python -m pytest -m network
```
