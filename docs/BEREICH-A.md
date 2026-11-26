# Bereich A – Zwischenstand Betrieb und Datenmodell

Stand: 2026-11-26 · Verantwortlich: @zaole05-stack · Grundlage: [PLAN.md](PLAN.md)

Dieses Dokument hält fest, was für Bereich A (`core/`, `decision/`, `config/`,
Einstiegspunkt) beschlossen ist und was noch offen ist. Alles, was andere
Bereiche berührt, ist als **Abstimmung nötig** markiert. Das gilt nach Regel 5
im Plan erst, wenn das Team zugestimmt hat. Bis dahin ist es ein Vorschlag von A.

## Beschlossen

### Regeln und Testlauf

1. **Die Regeln stehen vor dem Testlauf fest und bleiben während des Laufs
   unverändert.** Bewertungskriterien kommen aus Studien, nicht aus den eigenen
   Daten. Kriterien an denselben Daten zu suchen, an denen man sie prüft, ist
   Data Snooping.
2. **Bug-Fix oder Strategie-Änderung:**
   - Bug-Fix: Der Code tut nicht, was die Regel sagt. Erlaubt, wird aber mit
     Datum und Grund protokolliert.
   - Strategie-Änderung: Die Regel selbst ändert sich. Das beendet den laufenden
     Testlauf und startet einen neuen, die 6 Monate beginnen von vorn.
3. **`Testlauf` wird zentrales Objekt im Datenmodell.** Ein Testlauf hat ID,
   Namen, Besitzer, Start, Ende und ein eingefrorenes Regelwerk (Haltedauer,
   Plätze, Kosten, ETF, erlaubte Tags). Jedes Portfolio, jede Order und jede
   Entscheidung gehört zu genau einem Testlauf. Ein Testlauf enthält das
   Haupt-Portfolio und die Schattenportfolios der Experten. Mehrere Testläufe
   liegen in derselben Datenbank und sind im Dashboard vergleichbar.
4. **Einzahlungen kommen erst mit echtem Geld.** Im Papiertest gibt es nur das
   Startkapital. Einzahlungen würden die Rendite vom Zeitpunkt abhängig machen
   und eine zeitgewichtete Auswertung sowie identische ETF-Einzahlungen
   erfordern.

### Betrieb

5. **Der Testlauf läuft auf dem Laptop von A.** Verpasstes wird nachgeholt.
6. **Nachholen nach Variante A:** Eine nachgeholte Entscheidung gilt zum
   Zeitpunkt „jetzt“, nicht rückdatiert. So wäre es auch mit echtem Geld.
   Signale, die dabei zu alt geworden sind, fallen weg. Kurse dürfen
   nachträglich aus der Historie geholt werden, denn sie standen zur
   Ausführungszeit fest. Nur die Entscheidung wird nicht rückdatiert.
7. **Schema-Änderungen über nummerierte Migrationen** mit `PRAGMA user_version`.
   `connect()` führt die fehlenden Migrationen aus, jede in einer Transaktion.
8. **Backups über `sqlite3`-`conn.backup(...)`**: vor jeder Migration und
   einmal täglich, Ziel ist ein OneDrive-Ordner. Die laufende Datenbank liegt
   **nicht** in OneDrive, sonst drohen Sperrfehler und Konfliktkopien. Der
   geteilte Backup-Ordner dient dem Team zugleich als Lesekopie.

### Signal-Vertrag (`core/models.py`)

9. **`confidence` bekommt einen gemeinsamen Notenschlüssel:** Der Wert ist die
   Wahrscheinlichkeit, dass die Aktie den Vergleichs-ETF über die Haltedauer
   schlägt. Er muss begründet sein, am besten mit einer Studie, und ist nach
   dem Test überprüfbar (Kalibrierung). **Abstimmung nötig** mit B und C.
10. **Bis die Kriterien belegt sind, gilt `confidence = 0,5`** für alle
    Signale, also „keine Information“. Positionen bekommen damit gleich viel
    Geld. Eine Gewichtung nach Potenzial kommt erst, wenn die Werte kalibriert
    sind.
11. **Die Bevorzugung der obersten Führung (CEO, CFO …) wird eine eigene Regel
    im Entscheidungs-Agenten** statt eines höheren `confidence`-Werts.
12. **`Signal` bekommt `tags: frozenset[str]`.** Die erlaubten Tags legt A in
    `core/` fest, zum Beispiel `"top_executive"`. Ein unbekannter Tag löst
    beim Erzeugen des Signals einen Fehler aus. Später landen hier auch die
    Kriterien aus den Studien, etwa „opportunistischer Käufer“.
    **Abstimmung nötig** mit B: `experts/insider.py` setzt künftig den Tag
    statt 0,6.

## Offen

Die Punkte sind nach Abhängigkeit geordnet: Was oben steht, entscheidet über
das, was darunter steht.

### 1. Haltedauer – nach dem Lesen beider Studien

Die Studien im Plan messen unterschiedliche Zeiträume:

- Cohen, Malloy & Pomorski (2012, *Journal of Finance*): Rendite im Folgemonat
  nach Käufen opportunistischer Insider, also etwa 1 Monat.
- Lakonishok & Lee (2001, *Review of Financial Studies*): Vorsprung über etwa
  12 Monate, vor allem bei kleinen Firmen.

Beide Paper lesen, dann festlegen. Davon hängen ab:

- **Anzahl Trades.** Käufe in 6 Monaten ≈ Plätze × (182 Tage / Haltedauer).
  Heute (10 Plätze, 91 Tage) sind es höchstens etwa 20 je Portfolio. Mit 20
  Trades lässt sich kaum belastbar zeigen, dass ein Portfolio den ETF schlägt.
- **Testdauer.** Ist die Haltedauer länger als 6 Monate, wird im Test keine
  Position verkauft. Dann muss die Zahl der Plätze steigen, der Test länger
  laufen oder das Urteil auf Buchwerten zum Stichtag beruhen.
- **Bedeutung von `confidence`**, denn sie bezieht sich auf die Haltedauer.

### 2. Plätze und Startkapital – nach Punkt 1

Wenn die Haltedauer lang wird, sind mehr Plätze der Hebel für mehr Trades.
Bei 10.000 Startkapital und 50 Plätzen wären es rund 196 USD je Position. Die
feste Gebühr von 1 USD (`paper_trading/costs.py`) kostet dann für Kauf und
Verkauf zusammen etwa 1 %. Im Papiertest lässt sich das Startkapital einfach erhöhen.
Vorschlag: Plätze so wählen, dass ein Portfolio in 6 Monaten mindestens etwa
50 Käufe erreichen kann, und das Startkapital so, dass die feste Gebühr unter
0,1 % je Order bleibt.

### 3. Welche Testläufe es geben soll

Das Datenmodell trägt mehrere Testläufe (siehe oben). Offen ist, **was** sich
zwischen ihnen unterscheiden soll. Achtung: Mehrere Regelwerke nebeneinander
zu testen und am Ende das beste zu küren, ist wieder Data Snooping. Bei
20–60 Trades je Lauf sind die Unterschiede größtenteils Zufall. Vorschlag:
Vor dem Start einen Lauf als **Hauptlauf** benennen, der allein nach der
Entscheidungsregel des Konzepts beurteilt wird. Weitere Läufe gelten nur als
Beobachtung. Alle Läufe laufen auf einem Rechner in einer Datenbank, nicht
auf mehreren Laptops: Das ist einfacher, und kein Lauf misst die
Zuverlässigkeit seines Geräts statt der Strategie. **Abstimmung nötig.**

### 4. Zweck des EDGAR-Nachlaufs

Der Nachlauf ist rückwirkend, also ein Backtest. Er taugt **nicht** zur
Schätzung der Rendite (`MarketCapLookup` liefert den heutigen statt des
damaligen Börsenwerts) und nicht zum Ableiten von Kriterien (Data Snooping).
Vorschlag: eine reine Zählung der Signale pro Woche nach allen Filtern. Sie
beantwortet nur, ob sich die Plätze überhaupt füllen. Kritisch wird es erst
unter etwa 1 Signal pro Woche.

### 5. Zeitsteuerung auf dem Laptop

Ein Scheduler im Python-Prozess (z. B. APScheduler) läuft nicht, solange der
Laptop schläft oder der Prozess beendet ist. Vorschlag: die
**Windows-Aufgabenplanung** ruft stündlich einen Befehl auf, mit der Option
„Aufgabe so schnell wie möglich nach einem verpassten Start ausführen“. Jeder
Aufruf ist idempotent und holt Verpasstes nach (Punkt 6 oben). Dazu gehört
ein Protokoll der Läufe, damit Ausfälle im Ergebnis sichtbar sind.

### 6. Protokoll für Bug-Fixes

Wo und wie Bug-Fixes am Testlauf gespeichert werden. Vorschlag: eigene
Tabelle mit Testlauf, Zeitpunkt, betroffener Regel, Grund und Commit. Das
Dashboard zeigt die Einträge als Markierung im Verlauf.

### 7. Regeln im Dashboard sperren

Heute sind die Regeln im Dashboard jederzeit änderbar (`core/settings.py`).
Mit dem Testlauf werden sie nach dem Start nur noch angezeigt. Ein neuer
Testlauf mit neuen Regeln wird angelegt statt der alte geändert.
**Abstimmung nötig** mit B (`dashboard/`).

### 8. Backup wiederherstellen

Ein Backup, das nie zurückgespielt wurde, ist nicht geprüft. Vorschlag: ein
Test, der ein Backup erzeugt, zurückspielt und den Inhalt vergleicht, und
einmal vor dem Teststart ein echter Probelauf mit der OneDrive-Kopie.

### 9. Bestehende Datenbanken

`data/demo.sqlite` hat noch kein `user_version`. Vorschlag: Version 0 gilt als
„Schema vor den Migrationen“, Migration 1 bringt sie auf den neuen Stand. Die
Demo-Datei darf notfalls neu erzeugt werden, eine echte Testdatenbank nie.

### Offen auf Konzept-Ebene (Regel 5, gemeinsam)

Vergleichs-ETF, LLM-Budget und die übrigen offenen Punkte aus
[KONZEPT.md](KONZEPT.md) entscheidet das Team gemeinsam. Sie gehören zum
eingefrorenen Regelwerk des Testlaufs und müssen daher vor dem Start feststehen.

## Nächste Schritte für A

1. Beide Studien lesen, Haltedauer festlegen (Punkt 1), danach Plätze und
   Startkapital (Punkt 2).
2. Abstimmung mit B und C zu Notenschlüssel, Tags, Testläufen und
   Dashboard-Sperre.
3. Umsetzung in dieser Reihenfolge: Migrationen und Backup → `Testlauf` im
   Datenmodell → `tags` an `Signal` → Einstiegsbefehl mit Windows-Aufgabenplanung
   → Zählung im EDGAR-Nachlauf.
