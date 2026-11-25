# finance-AI

Spezialisierte KI-Agenten recherchieren Insider-Käufe, Fonds-Positionen,
Politiker-Trades und Social Media. Ein Entscheidungs-Agent handelt daraus auf
einem Portfolio, zunächst nur im Paper Trading gegen einen Small-Cap-ETF.

- [Konzept](docs/KONZEPT.md): was festgelegt ist und was offen ist
- [Plan](docs/PLAN.md): Struktur, Datenquellen, Meilensteine

Status: M0 (Fundament), M1 (Paper-Trading-Engine mit echten Stundenkursen) und M2 (Insider-Experte auf SEC Form 4) fertig.

## Entwicklung

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

Für Abrufe bei der SEC wird ein User-Agent mit Name und E-Mail-Adresse
gebraucht (Vorgabe der SEC). Dazu `.env.example` nach `.env` kopieren und
`SEC_USER_AGENT` ausfüllen. Die `.env` wird nicht committet.

Tests mit Internetzugriff (Yahoo Finance, SEC EDGAR) laufen nur auf Wunsch:

```powershell
.venv\Scripts\python -m pytest -m network
```
