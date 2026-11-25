# finance-AI

Spezialisierte KI-Agenten recherchieren Insider-Käufe, Fonds-Positionen,
Politiker-Trades und Social Media. Ein Entscheidungs-Agent handelt daraus auf
einem Portfolio, zunächst nur im Paper Trading gegen einen Small-Cap-ETF.

- [Konzept](docs/KONZEPT.md): was festgelegt ist und was offen ist
- [Plan](docs/PLAN.md): Struktur, Datenquellen, Meilensteine

Status: M0 (Fundament) und M1 (Paper-Trading-Engine, noch ohne echte Kursquelle) fertig.

## Entwicklung

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```
