# finance-AI – Konzept

Stand: 2026-11-25 · Ergebnis von zwei Grill-Sessions (21. und 25.11.2026)

## Idee

Spezialisierte KI-Agenten recherchieren Quellen, für die eine einzelne Person
keine Zeit hat: Insider-Käufe, Fonds-Positionen, Trades von Politikern und Posts
einflussreicher Personen. Ein Entscheidungs-Agent führt die Infos zusammen und
handelt auf **einem** Portfolio. Ein Dashboard zeigt Briefings, Vorschläge und
Kennzahlen.

Der Fokus liegt auf **risikoreichen Investments mit hohem Potenzial**, also jungen
Unternehmen und Nischenwerten.

## Festgelegt

### Umfang

- Der sichere Bereich (Sparplan, Rebalancing) ist **nicht** Teil des Projekts.
  Ein Sparplan läuft beim Broker ohne Software.
- Volle Konzentration auf den riskanten Bereich.

### Agenten

| Agent | Aufgabe |
|---|---|
| Insider-Experte | Käufe von Vorständen, Aufsichtsräten und Großaktionären über 10 % (SEC Form 4, Directors' Dealings) |
| Fonds-Experte | Positionen großer Fonds (SEC 13F). Die Daten kommen bis zu 45 Tage verzögert. |
| Politik-Experte | Trades von US-Kongressmitgliedern (STOCK Act). Die Daten kommen bis zu 45 Tage verzögert. |
| Social-Media-Experte | Posts einflussreicher Personen. Aufgeteilt in einen **Signal-Agenten** (handelt) und einen **Kontext-Agenten** (liefert nur Briefings). |
| Entscheidungs-Agent | Führt alle Experten-Infos zusammen und handelt auf dem Haupt-Portfolio |

### Befugnisse

| Phase | Was die Agenten dürfen |
|---|---|
| Paper Trading | Sie handeln **automatisch** auf dem Papier. |
| 1 (echtes Geld) | Sie schlagen Orders vor. Ausgeführt wird erst nach Freigabe im Dashboard. |
| später (vorgemerkt) | Sie handeln autonom innerhalb fester Regeln und Budgets. |

### Messung

- **Ein Haupt-Portfolio:** Der Entscheidungs-Agent handelt auf kombinierten
  Signalen.
- **Schatten-Bewertung pro Experte:** Jedes Signal wird protokolliert und so
  bewertet, als hätte man nur darauf gehandelt. Daran zeigt sich, ob die
  Kombination besser ist als jeder Experte allein und welcher Experte nur
  Rauschen liefert.
- **Doppelte Bewertung jeder Order:** einmal bei sofortiger Ausführung und
  einmal mit simulierter Freigabe-Verzögerung (1 Stunde). Daran zeigt sich, ob
  Phase 1 mit manueller Freigabe überhaupt funktionieren kann.
- **Vergleichsmaßstab:** ein Small-Cap-ETF.

### Regeln

- **Gleiche Regel für jeden Experten und für das Haupt-Portfolio.** Was im Paper
  Trading keinen Vorteil gegenüber dem ETF bringt, wird abgeschaltet.
- **Paper Trading über 6 Monate.** Abbruch, wenn ein Agent schlechter
  abschneidet als der ETF oder mehr als 20 % Verlust macht.
- **Entscheidungsregel nach 6 Monaten.** Gebühren, Steuern und Slippage werden
  simuliert eingerechnet.

| Ergebnis gegenüber ETF (nach Kosten) | Konsequenz |
|---|---|
| ≥ 5 % besser | Start mit echtem Geld, zunächst nur mit kleinem Betrag |
| 0–5 % besser | Paper Trading um 6 Monate verlängern |
| schlechter | Agent einstellen |

### Datenzugang

- **Zunächst keine kostenpflichtigen Daten-APIs.** Es werden nur frei zugängliche
  Quellen genutzt (siehe [PLAN.md](PLAN.md)).

## Kritische Punkte aus der Diskussion

- **Kein Geschwindigkeitsvorteil bei großen Werten.** Trump-Posts und ähnliche
  Nachrichten werden von Algorithmen in Sekunden eingepreist. Die doppelte
  Bewertung soll zeigen, ob davon nach einer Stunde noch etwas übrig ist.
- **Falsche Zielgruppe bei Social Media.** Posts von Politikern bewegen vor allem
  Indizes, Sektoren und Großkonzerne, selten junge Unternehmen.
- **Insider-Käufe sind die am besten belegte Quelle.** Sie sagen Renditen voraus,
  besonders bei kleinen Firmen (Lakonishok & Lee 2001, *Review of Financial
  Studies*). Verkäufe sagen wenig aus.
- **Fonds- und Politiker-Daten sind veraltet,** wenn sie öffentlich werden. Die
  Belege zu Politikern sind widersprüchlich (Ziobrowski et al. 2004; Eggers &
  Hainmueller 2013, *Journal of Politics*).
- **Mehr Experten heißt weniger Aussagekraft pro Experte.** In 6 Monaten gibt es
  nur begrenzt viele Trades.
- **LLMs können Quellen falsch verstehen oder Fakten erfinden.** Jedes Signal
  braucht deshalb einen Quellenlink.
- **Survivorship Bias.** Die meisten jungen Unternehmen steigen nicht stark.

## Offen

### Pflicht vor dem ersten echten Euro

- [ ] Wie viel Kapital insgesamt eingesetzt wird
- [ ] Harte Obergrenze pro Position und für das Gesamtrisiko
- [ ] Notgroschen separat angelegt, außerhalb des Systems
- [ ] Verlustgrenze relativ fassen? Vorschlag: Abbruch bei 20 % *mehr* Verlust
      als der ETF im selben Zeitraum. Noch nicht bestätigt.

### Noch zu klären

- [ ] Monatliches Kostenbudget für LLM-Aufrufe. Das ist die einzige API, die sich
      nicht vermeiden lässt, wenn die Agenten KI-gestützt arbeiten sollen.
- [ ] Beobachtungsliste für Social Media: Wer kommt drauf, und mit welcher
      Begründung? Marktrelevanz von Barron Trump ist unbelegt.
- [ ] Zugang zu Social Media ohne API (X und Truth Social)
- [ ] Welcher Small-Cap-ETF konkret der Vergleichsmaßstab ist
- [ ] Standardwerte des Entscheidungs-Agenten bestätigen: 10 Plätze,
      91 Tage Haltedauer, Börsenwert bis 2 Mrd. USD (siehe PLAN.md, M3)
- [ ] Abbruchregel während des Testlaufs: Umgesetzt ist nur die harte Grenze
      (mehr als 20 % Verlust). Ein Rückstand zum ETF wird gemeldet, beendet den
      Lauf aber erst bei der Auswertung nach 6 Monaten.
