# finance-AI – Umsetzungsplan

Stand: 2026-11-25 · Grundlage: [KONZEPT.md](KONZEPT.md)

## Ziel der ersten Ausbaustufe

Ein System, das **6 Monate Paper Trading** fährt und am Ende die Entscheidungsregel
aus dem Konzept beantworten kann: Schlägt das Haupt-Portfolio oder ein einzelner
Experte den Small-Cap-ETF, nach Kosten, sofort ausgeführt und mit 1 Stunde
Verzögerung?

Echtes Geld, eine Broker-Anbindung und kostenpflichtige Daten-APIs gehören
**nicht** zu dieser Stufe.

## Technische Entscheidungen (Vorschlag, noch änderbar)

| Thema | Wahl | Grund |
|---|---|---|
| Sprache | Python 3.12 | Die besten Bibliotheken für Daten, LLMs und Finanzen |
| Speicher | SQLite | Eine Datei, kein Server. Reicht für eine Person völlig. |
| Dashboard | Streamlit | Lokal, schnell gebaut, ohne Frontend-Code |
| LLM | Claude über die Anthropic-API | Die einzige unvermeidbare API, Budget noch offen |
| Zeitsteuerung | Einfacher Scheduler (z. B. `APScheduler`) | Kein Cloud-Dienst nötig |

## Freie Datenquellen

| Experte | Quelle | Hinweis |
|---|---|---|
| Insider (USA) | SEC EDGAR, Form 4 | Kostenlos. Die SEC verlangt einen User-Agent mit Kontaktangabe und begrenzt die Abfragerate. |
| Insider (DE) | BaFin-Datenbank für Eigengeschäfte von Führungskräften | Kostenlos, Abruf über die Webseite |
| Fonds | SEC EDGAR, 13F | Kostenlos, bis zu 45 Tage verzögert |
| Politiker | Offenlegungsseiten von US-Repräsentantenhaus und Senat | Kostenlos, teils als PDF, bis zu 45 Tage verzögert |
| Social Media | – | **Offen.** Ohne API ist kein sauberer Zugang möglich, Scraping verstößt meist gegen die Nutzungsbedingungen. |
| Kurse | Zunächst `yfinance` oder Stooq | Kostenlos, aber inoffiziell. Für 6 Monate Test vertretbar, später prüfen. |

## Projektstruktur

```text
finance-AI/
├── docs/                 Konzept und Plan
├── config/               Einstellungen (Beobachtungslisten, Kosten, Regeln)
├── src/finance_ai/
│   ├── core/             Gemeinsame Datentypen: Signal, Order, Position
│   ├── data/             Abruf der freien Quellen (EDGAR, BaFin, Kongress, Kurse)
│   ├── experts/          Ein Modul pro Experte
│   │   ├── insider.py
│   │   ├── funds.py
│   │   ├── politics.py
│   │   └── social.py
│   ├── decision/         Entscheidungs-Agent: kombiniert die Signale
│   ├── paper_trading/    Papier-Depot, Ausführung (sofort und verzögert), Kosten
│   ├── evaluation/       Schatten-Bewertung, Vergleich mit ETF, Abbruchregeln
│   └── dashboard/        Streamlit-Oberfläche
└── tests/
```

## Meilensteine

Jeder Meilenstein ist erst fertig, wenn sein Prüfkriterium erfüllt ist.

### M0 – Fundament

- [ ] Python-Projekt, Abhängigkeiten, SQLite-Schema
- [ ] Datentypen `Signal` (immer mit Quellenlink), `Order`, `Position`
- **Prüfung:** Tests für die Datentypen laufen grün.

### M1 – Paper-Trading-Engine

- [ ] Papier-Depot mit Startkapital
- [ ] Ausführung jeder Order zweimal: sofort und mit 1 Stunde Verzögerung
- [ ] Simulierte Gebühren, Steuern und Slippage
- [ ] ETF-Vergleich über denselben Zeitraum
- **Prüfung:** Ein Test mit festen historischen Kursen ergibt die von Hand
  berechnete Rendite.

### M2 – Insider-Experte (erster Experte)

- [ ] Form-4-Meldungen von EDGAR abrufen und nur **Käufe** herausfiltern
- [ ] Daraus Signale mit Quellenlink erzeugen
- **Prüfung:** Für einen bekannten vergangenen Insider-Kauf entsteht das
  richtige Signal.

Der Insider-Experte kommt zuerst, weil seine Quelle die am besten belegte ist,
die geringste Verzögerung hat und kostenlos ist.

### M3 – Entscheidungs-Agent und Schatten-Bewertung

- [ ] Der Entscheidungs-Agent erzeugt aus den Signalen Orders für das
      Haupt-Portfolio, mit begründetem Briefing
- [ ] Jedes Expertensignal wird zusätzlich einzeln im Schatten bewertet
- **Prüfung:** Für jede Order lässt sich nachvollziehen, welche Signale dazu
  geführt haben.

### M4 – Dashboard

- [ ] Briefings und Begründungen der Orders
- [ ] Kennzahlen: Haupt-Portfolio und jeder Experte gegen den ETF, sofort und
      verzögert
- [ ] Warnung, sobald eine Abbruchregel greift
- **Prüfung:** Alle Zahlen im Dashboard stimmen mit der Auswertung überein.

### M5 – Weitere Experten

- [ ] Fonds-Experte (13F)
- [ ] Politik-Experte (Kongress-Offenlegungen)
- [ ] Social-Media-Experte, erst wenn der Datenzugang geklärt ist
- **Prüfung:** wie bei M2, für jeden Experten.

### M6 – Testlauf

- [ ] 6 Monate Paper Trading im Dauerbetrieb
- [ ] Auswertung nach der Entscheidungsregel aus dem Konzept

## Risiken

- **Zu wenige Insider-Käufe bei kleinen Werten:** Dann gibt es zu wenige Trades
  für eine aussagekräftige Messung. Deshalb ab M2 die Anzahl der Signale pro
  Woche beobachten.
- **LLM-Kosten laufen davon.** Deshalb ab M3 die Kosten pro Tag protokollieren.
- **Inoffizielle Kursquellen fallen aus.** Deshalb den Kursabruf hinter einer
  Schnittstelle kapseln, damit die Quelle austauschbar bleibt.
