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

- [x] Python-Projekt, Abhängigkeiten, SQLite-Schema
- [x] Datentypen `Signal` (immer mit Quellenlink), `Order`, `Position`
- **Prüfung:** Tests für die Datentypen laufen grün.

### M1 – Paper-Trading-Engine

- [x] Papier-Depot mit Startkapital
- [x] Ausführung jeder Order zweimal: sofort und mit 1 Stunde Verzögerung
- [x] Simulierte Gebühren, Steuern und Slippage
- [x] ETF-Vergleich über denselben Zeitraum
- [x] Echte Kursquelle: Stundenkurse von Yahoo Finance, zwischengespeichert in SQLite (`CachedPriceSource`)
- **Prüfung:** Ein Test mit festen historischen Kursen ergibt die von Hand
  berechnete Rendite.

### M2 – Insider-Experte (erster Experte)

- [x] Form-4-Meldungen von EDGAR abrufen und nur **Käufe** herausfiltern
  (Tagesindex, Code P, nur Officers/Directors, ohne 10b5-1-Pläne, ab 25.000 USD)
- [x] Daraus Signale mit Quellenlink erzeugen (ein Signal je Meldung)
- [x] **Prüfung:** Für einen bekannten vergangenen Insider-Kauf entsteht das
  richtige Signal (Aldeyra Therapeutics, CEO, 24.11.2026, Test mit der
  echten Meldung).

Der Insider-Experte kommt zuerst, weil seine Quelle die am besten belegte und
kostenlos ist.

Offen für später:
- Der Tagesindex erscheint erst nach Tagesende. Signale kommen also bis zu
  einen Tag nach der Meldung. Schneller ginge es über den Atom-Feed der SEC.
- Routinemäßige Käufer erkennen (Cohen, Malloy & Pomorski 2012). Das braucht
  mehrere Jahre Historie je Person.
- Filter auf kleine Firmen nach Börsenwert.

### M3 – Entscheidungs-Agent und Schatten-Bewertung

- [x] Der Entscheidungs-Agent erzeugt aus den Signalen Orders für das
      Haupt-Portfolio, mit begründetem Briefing (vorerst feste Regeln ohne LLM)
- [x] Jedes Expertensignal wird zusätzlich einzeln im Schatten bewertet
- [x] Vorfilter: keine Fonds, BDCs, REITs, SPACs; Börsenwert bis 2 Mrd. USD;
      oberste Führung (CEO, CFO …) mit höherem Rang
- [x] Auswertung je Portfolio gegen den ETF mit Urteil nach den Konzept-Regeln
- [x] **Prüfung:** Für jede Order lässt sich nachvollziehen, welche Signale dazu
  geführt haben. Auch jedes abgelehnte Signal ist mit Grund gespeichert.

Gesetzte Standardwerte (in `DecisionRules`, noch nicht bestätigt):
10 Plätze zu je 10 % des Startkapitals, Haltedauer 91 Tage, Signale höchstens
3 Tage alt. Für das Urteil zählt die Ausführung mit 1 Stunde Verzögerung.
Ein LLM kann später die übrig gebliebenen Kandidaten zusätzlich prüfen,
sobald das Budget feststeht.

### M4 – Dashboard

- [x] Briefings und Begründungen der Orders
- [x] Kennzahlen: Haupt-Portfolio und jeder Experte gegen den ETF, sofort und
      verzögert
- [x] Warnung, sobald eine Abbruchregel greift
- [x] Einstellungen im Dashboard änderbar (ETF, Teststart, Regeln, Kosten),
      gespeichert in der Datenbank
- **Prüfung:** Alle Zahlen im Dashboard stimmen mit der Auswertung überein.
  Erfüllt: Das Dashboard rechnet nicht selbst, es zeigt das Ergebnis von
  `evaluate` (Test `test_overview_numbers_equal_evaluation`).
- Nebenbei behoben: Die Auswertung nutzt nur Kurse bis zum Stichtag. Orders
  ohne Kurs (direkt nach der Entscheidung, nachts, am Wochenende) gelten als
  offen statt abgelehnt. Vorher brach die Auswertung dann ab oder nahm spätere
  Kurse.
- Offen: Die gespeicherten Regeln wirken erst, wenn der Dauerbetrieb (M6) sie
  beim Entscheidungslauf lädt. Scan und Entscheidung starten noch nicht aus dem
  Dashboard.

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
