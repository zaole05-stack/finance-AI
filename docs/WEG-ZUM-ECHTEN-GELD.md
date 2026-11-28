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

**Verkürzte Haltedauer:** Mit 91 Tagen Haltedauer gäbe es in einem kurzen
Test keinen Verkauf. Der Test läuft deshalb in einem eigenen Testlauf mit
verkürzter Haltedauer (z. B. 2 Tage). Er prüft die Technik, nicht die
Strategie. Für das echte Geld wird danach ein neuer Testlauf mit dem
eingefrorenen Regelwerk angelegt. Die verkürzte Haltedauer darf dort nicht
landen.

**Notfall-Verkauf:** Ein Befehl schließt eine Position vorzeitig von Hand.
Er wird nach dem Abschalten ohnehin gebraucht und im Test einmal benutzt.

**Bestanden**, wenn alles eingetreten ist, frühestens nach 10 Handelstagen:

| Prüfung | Bestanden, wenn |
|---|---|
| Kauf | mindestens 5 Käufe aus echten Signalen, ausgeführt über die API |
| Verkauf | mindestens 5 Verkäufe nach Ablauf der verkürzten Haltedauer |
| Notfall-Verkauf | einmal eine Position mit dem Befehl von Hand geschlossen |
| Abschalten | in einem eigenen Testlauf mit künstlich enger Grenze (z. B. −0,5 %): Das System stoppt, schickt den Push und eröffnet danach nichts mehr |
| Regeln | keine Order bricht eine Regel (Plätze, Cash, Börsenwert, keine Margin) |
| Abgleich | Bestände bei Broker und Datenbank stimmen in jedem Lauf überein |
| Wächter | einmal absichtlich den Laptop aus: Der Push vom Wächter kommt |
| Mails | an jedem Tag des Tests kam die tägliche Mail |
| Fehler | kein Fehler, der nicht erklärt und behoben ist |

Bricht eine Order eine Regel oder weicht ein Bestand ab, beginnt der Test
nach der Behebung von vorn. Vorübergehende Ausfälle von SEC oder Yahoo zählen
nicht.

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

### 7. Broker

**Regel:** Am liebsten ein Broker, der die deutsche Steuer abführt. Geht das
nicht, sind die Funktionen wichtiger. Dann erzeugt das System jedes Jahr eine
Steuerliste aus der Datenbank (Gewinn und Verlust pro Verkauf in Euro), und
die erste Erklärung prüft ein Steuerberater.

**Kriterien:**

1. offizielle API für Orders, Kontostand und Bestände, ohne TAN bei jeder Order
2. Paper-Konto mit derselben API
3. Konto für Wohnsitz Deutschland, reines Cash-Konto möglich
4. Handel mit kleinen US-Werten (Nasdaq, NYSE American)
5. niedrige Kosten pro Order und beim Währungstausch
6. Einlagensicherung und Aufsicht in der EU oder den USA
7. Jahresbericht, mit dem sich die Steuerliste abgleichen lässt

**Prüfung vom 28.11.2026** (Quellen unten, Stand der Seiten an diesem Tag):

| | Trading 212 | Interactive Brokers (Irland) | Alpaca |
|---|---|---|---|
| 1. API | REST mit API-Schlüssel, **Beta**. Orders sind nicht idempotent: Doppelte Anfrage, doppelte Order | nur über ein laufendes Programm (TWS oder IB Gateway). **Einmal pro Woche Anmeldung mit zweitem Faktor**, in seltenen Fällen auch zwischendurch | REST |
| 2. Paper-Konto | ja, eigene Demo-Umgebung mit derselben API | erst nach Eröffnung und Einzahlung eines echten Kontos | ja |
| 3. Deutschland, Cash | Konto ja. Die API gilt für „Invest“-Konten (ohne Hebel). Ob sie bei deutschen Konten freigeschaltet ist, sagt die Doku nicht | ja | **nein, nicht direkt.** In Europa nur über Partnerfirmen, Konten werden dort zunächst als Margin-Konten eröffnet |
| 4. kleine US-Werte | Auswahl begrenzt, Abdeckung unserer Signale ungeprüft | breit | – |
| 5. Kosten | ungeprüft | 0,005 USD je Aktie, mindestens 1 USD. Währungstausch 0,03 % | – |
| 6. Sicherung | ungeprüft | irische Entschädigung: 90 % bis 20.000 € bei Pleite des Brokers | – |
| 7. Steuer | laut Vergleichsportalen **seit 05.01.2026 steuereinfach** für Konten über die deutsche Einheit (FXFlat). Offizielle Seite nicht lesbar | keine deutsche Steuer, Anlage KAP selbst | – |

Offene Widersprüche bei Trading 212: Eine Stelle der Doku nennt für echtes
Geld **nur Market-Orders**, die Liste der Endpunkte führt auch Limit-Orders.
Für kleine, wenig gehandelte Werte ist das entscheidend. Eine Market-Order
ohne Preisgrenze kann dort weit vom letzten Kurs ausgeführt werden.

**Stand:** Alpaca fällt weg. Trading 212 wäre der einzige Kandidat, der
Steuer und API verbindet, mit drei offenen Punkten: API bei deutschen
Konten, Limit-Orders im echten Handel, Abdeckung unserer Signale.
Interactive Brokers bleibt die Alternative mit breiter Abdeckung, kostet aber
eine Anmeldung pro Woche und die Steuer von Hand.

Quellen: [Trading 212 API-Doku](https://docs.trading212.com/api.md),
[Trading 212 API-Grenzen](https://docs.trading212.com/api/section/general-information/api-limitations),
[Rankia zu Trading 212 und Steuern](https://rankia.de/trading-212-steuern/),
[IBKR Neuanmeldung](https://www.interactivebrokers.com/docs/third-party-integrations/tws-settings/daily-weekly-reauthentication),
[IBKR Paper-Konto](https://www.interactivebrokers.com/campus/trading-lessons/so-verwenden-sie-das-paper-trading-konto-von-ibkr/),
[IBKR Irland Anlegerschutz](https://www.interactivebrokers.com/support/faq/content/126537062),
[IBKR Gebühren](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php),
[Alpaca Europe Kontoeröffnung](https://docs.alpaca.markets/eu/docs/account-opening),
[Business Wire zu Alpaca Europe](https://www.businesswire.com/news/home/20260421441080/en/Alpaca-Expands-into-Europe-with-WealthKernel-Acquisition-and-Launch-of-European-Equities-Trading)

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

- [ ] Broker: Trading 212 oder Interactive Brokers (Abschnitt 7). Offen sind
      die API bei deutschen Konten, Limit-Orders im echten Handel und die
      Abdeckung unserer Signale.
- [x] Dauer des Tests auf dem Paper-Konto und messbare Bestehenskriterien (Abschnitt 3)
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
- Befehl für den Notfall-Verkauf einer Position
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
