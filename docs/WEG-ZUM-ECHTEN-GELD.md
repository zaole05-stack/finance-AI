# Weg zum echten Geld

Stand: 2026-11-28 · Ergebnis einer Grill-Session von Bereich A

**An B, C und D:** Das ist ein Vorschlag, der das [KONZEPT](KONZEPT.md) an
mehreren Stellen ändert. Wer etwas anders haben will, schreibt es bis
**2026-12-05** als Kommentar in diesen PR. Kommt bis dahin kein Einwand, gilt
er als beschlossen. Danach wird das KONZEPT angepasst.

## Kurzfassung

> Backtest 2011–2022 „bestanden“ → Prüfung 2023–2026 im Mittel vor dem ETF →
> kurzer Test auf einem Paper-Konto des Brokers → echtes Geld, autonom,
> eigenes Cash-Konto, Abschalten bei −25 %

Die Leistung der Strategie wird **nur im Backtest** gemessen. Der Test auf dem
Paper-Konto prüft die **Technik**, nicht die Rendite.

## Beschlossen (Vorschlag)

### 1. Kein Paper Trading über 6 Monate

Statt 6 Monaten Paper Trading gibt es zwei Prüfungen:

1. den Backtest auf historischen Daten (`docs/BACKTEST.md` auf
   `feat/insider-backtest`);
2. einen kurzen Test auf einem Paper-Konto des Brokers.

Grund: 6 Monate sind zu lang bis zum ersten echten Euro. Außerdem liefert ein
halbes Jahr nur wenige Trades. Der Backtest deckt mehr als zehn Jahre ab.

### 2. Backtest mit zurückgehaltenem Zeitraum

- **Prüfabschnitt:** 2011-07 bis 2022-12. Dort muss der Backtest das Urteil
  „bestanden“ bekommen. Bei „knapp“ oder „durchgefallen“ wird
  weiterentwickelt, nicht investiert.
- **Zurückgehalten:** 2023-01-01 bis 2026. Diese Jahre sieht niemand an, bevor
  das Regelwerk eingefroren ist. Danach werden sie **genau einmal**
  ausgewertet.
- **Bedingung für den zurückgehaltenen Zeitraum:** Die Strategie liegt dort
  **im Mittel vor dem ETF**. Sonst wird sie eingestellt, nicht nachgebessert.
- **Neue Regeln nur mit Studienbeleg.** Eine Regel kommt nur ins Regelwerk,
  wenn eine veröffentlichte Studie sie begründet, nicht weil sie im Backtest
  besser aussieht.

Grund: Wer Regeln so lange ändert, bis der Backtest gut aussieht, misst am
Ende den Zufall (Data Snooping). Der zurückgehaltene Zeitraum ist die einzige
Prüfung, an die man sich nicht angepasst haben kann. Deshalb darf er nur
einmal angesehen werden.

### 3. Kurzer Test auf dem Paper-Konto

Das System handelt selbst über die API des Brokers auf dessen Paper-Konto.
Geprüft wird:

- Kaufen und Verkaufen funktionieren.
- Die Regeln werden eingehalten (Plätze, Haltedauer, Börsenwert, Cash-Grenzen).
- Der Ablauf läuft wie geplant: stündlicher Lauf, Protokoll, Backup,
  Benachrichtigungen.

Dauer und messbare Bestehenskriterien sind noch offen (siehe unten).

### 4. Echtes Geld: autonom ab dem ersten Tag

- Das System kauft und verkauft **selbst**, ohne Freigabe im Dashboard.
  Die Phase „1 (echtes Geld) mit Freigabe“ aus dem KONZEPT entfällt.
- Es arbeitet auf einem **eigenen Handelskonto**. Es bekommt keinen Zugriff
  auf andere Konten. Es arbeitet frei mit dem Geld, das dort eingezahlt wird.
- **Nur Cash-Konto:** keine Margin, keine Leerverkäufe, keine Optionen.

### 5. Abschalten bei −25 %

- Liegt der Kontowert beim Broker **25 % unter der Einzahlung**, stoppt das
  System. Es eröffnet und schließt keine Positionen mehr.
- Was dann passiert, entscheidet der Kontoinhaber von Hand.
- Gemessen wird am Kontowert, den der Broker meldet, nicht an der eigenen
  Rechnung des Systems.

Das ersetzt für das echte Geld die Grenze von 20 % aus dem KONZEPT.

### 6. Tägliches Update und gestufte Warnungen

Die Benachrichtigungen baut Bereich A, weil sie aus dem stündlichen Lauf
kommen. Das Dashboard (B) kann dieselben Kennzahlen später anzeigen.

**Kanäle:** Das tägliche Update kommt per Mail. Alles Dringende kommt
zusätzlich als Push aufs Handy.

**Stufen beim Kontowert:**

| Stufe | Gemessen an | Kanal |
|---|---|---|
| −10 % | Höchststand des Kontos | Mail und Push |
| −20 % | Höchststand des Kontos | Mail und Push |
| −25 %: Abschalten | Einzahlung | Mail und Push |

Die Warnungen messen am Höchststand, damit auch schmelzende Gewinne auffallen.
Das Abschalten misst an der Einzahlung, damit normale Schwankungen das System
nicht stoppen.

**Programmfehler:**

| Fehler | Kanal |
|---|---|
| Order beim Broker abgelehnt oder fehlgeschlagen | sofort Push |
| Bestand beim Broker weicht von der Datenbank ab | sofort Push, das System hält an, bis es geklärt ist |
| Regeln im Code geändert (Testlauf passt nicht mehr) | sofort Push |
| Scan oder Kursabruf fehlgeschlagen, einmalig | nur in der täglichen Mail |
| Scan oder Kursabruf fehlgeschlagen, 3 Läufe in Folge | Push |
| Programm läuft gar nicht | Push vom Wächter |

**Wächter:** Jeder Lauf schickt ein Lebenszeichen an einen Dienst außerhalb
des Laptops (z. B. healthchecks.io). Bleibt es 3 Stunden aus, meldet sich der
Dienst per Push. Ein Programm kann nicht selbst melden, dass es nicht läuft.
Später soll das System auf einem Rechner laufen, der immer an ist (kleiner
Server oder Raspberry Pi), statt auf dem Laptop.

**Tägliche Mail:** nach Börsenschluss in New York, gegen 22:30 Uhr deutscher
Zeit. An Tagen ohne Handel kommt eine kurze Mail mit „kein Handel“, damit
eine fehlende Mail weiterhin auffällt. Inhalt, das Wichtigste oben:

1. Kontowert, Veränderung zum Vortag und seit der Einzahlung, Abstand zum
   Höchststand und zur Abschaltgrenze
2. Vergleich mit dem ETF seit dem Start
3. Käufe und Verkäufe des Tages mit dem auslösenden Signal (Insider, Betrag,
   Link zur Form-4-Meldung)
4. Offene Positionen mit Einstieg, aktuellem Stand und Ende der Haltedauer
5. Fehler des Tages, die keinen Push ausgelöst haben

Bei einem autonomen System ist die Mail die einzige Stelle, an der jede
Entscheidung nachgeprüft werden kann.

## Was sich im KONZEPT ändert

| KONZEPT heute | Neu |
|---|---|
| Paper Trading über 6 Monate | Backtest plus kurzer technischer Test auf dem Paper-Konto |
| Entscheidungstabelle nach 6 Monaten (≥ 5 % / 0–5 % / schlechter) | Backtest „bestanden“ und zurückgehaltener Zeitraum im Mittel vor dem ETF |
| Phase 1: Orders nur nach Freigabe | Autonom ab dem ersten Tag |
| Abbruch bei 20 % Verlust | Abschalten bei 25 % unter der Einzahlung |
| Doppelte Bewertung mit 1 Stunde Freigabe-Verzögerung | Entfällt, weil es keine Freigabe gibt |

## Noch offen

### Vor dem Paper-Konto

- [ ] Welcher Broker, mit welcher API? Geht ein eigenes Konto mit API-Handel
      von Deutschland aus, und wie werden die Steuern abgeführt?
- [ ] Dauer des Tests auf dem Paper-Konto und messbare Bestehenskriterien
- [x] Benachrichtigung: Kanal, Stufen, Inhalt des täglichen Updates (Abschnitt 6)

### Vor dem Einfrieren des Regelwerks

- [ ] Routine-Regel: nur Käufer mit Vorgeschichte (wie in der Studie von
      Cohen, Malloy & Pomorski) oder nur Routinekäufer ausschließen?
      Der Backtest kennt die Routine-Regel noch nicht.
- [ ] Fenster-Regel: „vor dem ETF“ oder „5 Prozentpunkte vor dem ETF“?
- [ ] Haltedauer und Zahl der Plätze (heute 91 Tage, 10 Plätze)
- [ ] Börsenwert: Backtest und Live-Betrieb nutzen verschiedene Quellen
- [ ] Wie der Backtest Käufe in wenig gehandelten kleinen Werten abrechnet

### Vor dem ersten echten Euro

- [ ] Höhe der Einzahlung
- [ ] Obergrenze pro Position
- [ ] Notgroschen außerhalb des Systems

## Arbeit, die daraus folgt

Bereich A, sobald der Vorschlag gilt:

- Anbindung an die API des Brokers (Paper- und echtes Konto)
- Abschalten bei −25 % am Kontowert des Brokers
- Tägliche Mail, Push-Warnungen und Lebenszeichen an den Wächter
- Abgleich der Bestände zwischen Broker und Datenbank in jedem Lauf
- Zurückgehaltener Zeitraum im Backtest: Prüfabschnitt endet 2022-12-31, die
  Auswertung 2023–2026 läuft nur einmal und wird gesperrt (wie die
  Neulauf-Sperre)

Bereich B: Routine-Regel im Backtest und im Insider-Experten, sobald die
Variante entschieden ist.

## Risiken, die wir bewusst eingehen

- **Keine Messung mit echten Kursen der Zukunft.** Die einzige Prüfung, die
  nicht angepasst sein kann, ist der zurückgehaltene Zeitraum. Ein
  Backtest unterschätzt Kosten und Ausführungsprobleme bei kleinen Werten
  meistens.
- **Keine menschliche Kontrolle vor einer Order.** Ein Fehler im Code handelt
  sofort mit echtem Geld. Schutz sind nur das Cash-Konto, die Grenze von
  −25 % und die Warnungen.
- **Bis zu 25 % der Einzahlung können verloren gehen**, bevor das System
  stoppt. Kurssprünge über Nacht können den Verlust darüber hinaus treiben.
