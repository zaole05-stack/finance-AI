# finance-AI – Konzept

Stand: 2026-11-21 · Ergebnis einer Grill-Session zur Idee

## Idee

KI-Agenten unterstützen beim Investieren. Ein Dashboard bündelt Briefings, Tipps
und Order-Vorschläge. Das Geld ist auf zwei Bereiche aufgeteilt:

- **Sicher:** baut wie ein Sparplan kontinuierlich Vermögen auf. Das Risiko ist
  gering, die Rendite eher niedrig.
- **Riskant:** junge Unternehmen und Nischenwerte mit hohem Potenzial und
  entsprechend hohem Verlustrisiko.

## Festgelegt

### Befugnisse der Agenten

| Phase | Was die Agenten dürfen |
|---|---|
| 1 (jetzt) | Sie schlagen konkrete Orders vor. Ausgeführt wird erst, wenn ich im Dashboard freigebe. |
| später (vorgemerkt) | Sie handeln autonom innerhalb fester Regeln und Budgets. |

### Sicherer Bereich

- Ein Sparplan läuft fest beim Broker. Der Agent trifft dort **keine** Kauf- oder
  Verkaufsentscheidungen.
- Der Agent übernimmt nur zwei Aufgaben:
  - **Rebalancing:** Er prüft regelmäßig die Aufteilung zwischen sicher und
    riskant und schlägt bei Abweichung eine Korrektur vor.
  - **Warnungen:** Er meldet sich, wenn ich vom Plan abweiche, etwa wenn ich in
    einem Crash verkaufen will.

### Riskanter Bereich

- Ein Entscheidungs-Agent erhält Input von spezialisierten Recherche-Agenten zu
  Politik, aktuellen Trends und Nischen.
- Sein erhoffter Vorteil: Er verarbeitet mehr Input, als ein Mensch schafft,
  deckt Nischen ab und entscheidet diszipliniert statt emotional.

### Validierung vor dem ersten echten Euro

- **Paper Trading über 6 Monate** gegen einen **Small-Cap-ETF** als
  Vergleichsmaßstab.
- **Abbruch**, wenn der Agent schlechter abschneidet als der ETF oder mehr als
  20 % Verlust macht.
- **Entscheidungsregel nach 6 Monaten.** Gebühren, Steuern und Slippage werden
  simuliert eingerechnet.

| Ergebnis gegenüber ETF (nach Kosten) | Konsequenz |
|---|---|
| ≥ 5 % besser | Start mit echtem Geld, zunächst nur mit kleinem Betrag |
| 0–5 % besser | Paper Trading um 6 Monate verlängern |
| schlechter | Agent einstellen |

## Kritische Punkte aus der Diskussion

- **Kein Geschwindigkeitsvorteil.** Nachrichten zu großen Werten sind in Sekunden
  eingepreist. Mit manueller Freigabe (Phase 1) liegen zwischen Nachricht und
  Order Stunden.
- **Mehr Input heißt nicht bessere Entscheidungen.** LLMs können Quellen falsch
  verstehen oder Fakten erfinden und klingen dabei überzeugt.
- **Disziplin entsteht durch feste Regeln** (Positionsgröße, Stop-Loss), nicht
  durch die KI an sich.
- **6 Monate sind statistisch wenig.** Ein einziger Glückstreffer kann das
  Ergebnis bestimmen. Deshalb zusätzlich die Anzahl der Entscheidungen und die
  Trefferquote auswerten, nicht nur die Gesamtrendite.
- **Survivorship Bias.** Die meisten jungen Unternehmen steigen nicht stark,
  viele verschwinden. Sichtbar sind vor allem die Gewinner.

## Offen

### Pflicht vor dem ersten echten Euro

- [ ] Standard-Aufteilung zwischen sicher und riskant (Vorschlag: 90 / 10)
- [ ] Harte Obergrenze für den riskanten Anteil (Vorschlag: 20 %). Eine Erhöhung
      wird erst nach 7 Tagen Wartezeit wirksam, eine Senkung sofort.
- [ ] Notgroschen von 3–6 Monatsausgaben separat angelegt, außerhalb des Systems
- [ ] Verlustgrenze relativ fassen? Vorschlag: Abbruch bei 20 % *mehr* Verlust
      als der ETF im selben Zeitraum. Grund: Ein Small-Cap-ETF kann selbst über
      20 % fallen, die absolute Grenze würde dann auch einen guten Agenten
      abschalten. Noch nicht bestätigt.

### Technik (noch nicht besprochen)

- [ ] Datenquellen für Kurse, News und Politik
- [ ] Orchestrierung der Recherche-Agenten
- [ ] Broker mit API, damit Phase 1 (Freigabe) und später autonomes Handeln
      möglich sind
- [ ] Schutz vor Halluzinationen: Quellenpflicht und Prüfung von Fakten
- [ ] Aufbau des Dashboards
