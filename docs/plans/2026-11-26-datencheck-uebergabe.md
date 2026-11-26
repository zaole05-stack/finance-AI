# Übergabe: Datencheck vor dem Insider-Backtest (Plan-Schritt 4b)

Diese Datei ist eine Arbeitsanweisung für Claude. Sie reicht für den ganzen
Lauf. Den Hintergrund erklärt der Plan
[2026-11-26-insider-backtest.md](2026-11-26-insider-backtest.md), Abschnitt
„4b. Datencheck“.

## Worum es geht

Bevor der Insider-Backtest (Bereich B) gerechnet wird, muss klar sein, ob die
Daten dafür taugen. Das Problem sind Aktien, für die es keine Kurse mehr gibt,
weil die Firma pleite, übernommen oder delistet ist. Solche Signale gehen in
der mittleren Stufe mit **−55 %** in die Messung ein. Ist ihr Anteil zu groß,
bestimmt diese Annahme das Ergebnis statt des Signals.

Der Check misst für die Jahre **2008** (Finanzkrise) und **2015** (ruhiges Jahr)
nur die Datenqualität:

- Signale pro Woche;
- Anteil mit Kurs;
- Anteil, der erst über das heutige Kürzel gefunden wird;
- Fälle ohne Kurs, aufgeteilt in Übernahme, Pleite, Grund unbekannt, erst
  nach der Haltedauer verschwunden, keine Meldung.

**Es werden keine Renditen berechnet.** Das ist Absicht: Der Backtest prüft ein
vorher eingefrorenes Regelwerk. Wer vorher in die Renditen schaut, macht das
Ergebnis wertlos.

## Ablauf

Alle Befehle laufen in PowerShell im Repo-Ordner.

### 1. Branch holen

```powershell
git fetch origin
git switch feat/insider-backtest
git pull
```

### 2. Umgebung

Falls noch keine `.venv` existiert (Python 3.12):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Die SEC verlangt einen User-Agent mit Kontaktadresse. Dazu muss in `.env` im
Repo-Ordner diese Zeile stehen:

```
SEC_USER_AGENT="Vorname Nachname name@example.org"
```

Die echten Werte trägt der Mensch selbst ein. Claude schreibt keine
E-Mail-Adresse in Dateien. Die `.env` wird nicht committet.

### 3. Tests

```powershell
.venv\Scripts\python -m pytest
```

Alle Offline-Tests müssen grün sein (Stand beim Push: 211). Wenn nicht: nicht
starten, sondern melden.

### 4. Datencheck starten

Der Lauf geht übers Netz und dauert lange. Starte ihn im Hintergrund und
schreibe die Ausgabe in eine Logdatei:

```powershell
$env:PYTHONIOENCODING = "utf-8"; .venv\Scripts\python -m finance_ai.evaluation.data_check 2008 2015 *> data\data_check.log
```

Was dabei geladen wird (alles landet in `data/`, das per `.gitignore`
ausgeschlossen ist):

- 8 Quartals-ZIPs der SEC „Insider Transactions Data Sets“ (2008q1–q4,
  2015q1–q4) von sec.gov. Jede ist 10–16 MB groß, zusammen rund 100 MB.
- Je Firma mit Signal 2–3 kleine JSON-Dateien von data.sec.gov. Nur ein
  kleiner Auszug wird gespeichert, in `data/raw/companies/`.
- Tageskurse von Yahoo Finance über yfinance, in `data/prices_daily.sqlite`.
  Rechne mit mehreren hundert MB.

Die Laufzeit ist vermutlich 1–3 Stunden. Beim ersten Versuch schaffte der Lauf
etwa 100 Firmen pro Minute. Die SEC-Grenze von 8 Anfragen pro Sekunde hält der
Code selbst ein.

**Rechner:** am Netzteil lassen. Energiesparen und Ruhezustand für die Nacht
ausschalten, die Claude-App offen lassen.

### 5. Normale Meldungen im Log

Diese Zeilen sind kein Fehler:

- Zeilen wie `$PFLC: possibly delisted; no timezone found` oder
  `HTTP Error 404 … Quote not found`. Das ist yfinance bei delisteten Kürzeln,
  genau diese Fälle zählt der Check.
- `NativeCommandError` in PowerShell. Das sind nur Log-Zeilen auf stderr.
- Fortschritt erscheint als `100 Firmen geladen`, `200 Firmen geladen`, …
  und am Ende jedes Jahres als `Jahr 2008: … Signale, … % mit −55 %`.

### 6. Wenn der Lauf abbricht

Einfach denselben Befehl noch einmal starten. Bereits geladene ZIPs, Firmen
und Kurse liegen im Zwischenspeicher und werden nicht neu geholt. Auch
„Yahoo kennt das Kürzel nicht“ ist gespeichert. Der Lauf ist danach also
schnell wieder an der alten Stelle.

Bricht er an derselben Stelle immer wieder ab, nicht herumprobieren.
Fehlermeldung und letzte Logzeilen notieren und melden.

## Was Claude dabei nicht tun soll

- Keine Renditen ausrechnen oder anschauen, auch nicht „nur kurz“.
- Folgendes nicht ändern: die Regeln in `experts/insider.py`, die Schwellen in
  `evaluation/data_check.py` (10 % / 20 %), die Haltedauer und den Ablauf
  von `missing_price_case`. Das sind abgestimmte Entscheidungen.
- Nichts in `core/` ändern.
- Nichts aus `data/` committen. Das betrifft SEC-Rohdaten, Yahoo-Kurse und
  Ergebnisdateien.
- Nicht auf `feat/insider-backtest` pushen. Bereich B arbeitet dort weiter.
- Ist ein echter Programmfehler die Ursache eines Abbruchs, nur melden: welche
  Datei, welche Zeile, welche Eingabe. Nicht still umgehen.

## Ergebnis

Am Ende schreibt der Lauf zwei Dateien und gibt die Tabelle auch aus:

- `data/data_check.md`: die Tabellen und das Ergebnis;
- `data/data_check.json`: dieselben Zahlen maschinenlesbar.

**So wird das Ergebnis gelesen.** Entscheidend ist die Spalte **„mit −55 %“**.
Es zählt das schlechtere der beiden Jahre.

| Anteil | Folge |
|---|---|
| bis 10 % | weiter mit Schritt 5–9 |
| 10–20 % | weiter, mit Warnung ganz oben im Bericht |
| über 20 % | Stopp, im Team andere Wege besprechen |

Die übrigen Spalten bedeuten:

- **pro Woche:** wie viele Signale in die Slots drängen. Das ist A's Frage aus
  `docs/BEREICH-A.md`, Punkt 4: Füllen sich die Plätze überhaupt?
- **davon über heutiges Kürzel:** Die Firma hat ihr Kürzel seitdem gewechselt.
  Ein hoher Wert ist unkritisch.
- **Kurs passt nicht:** Yahoo kennt das Kürzel, aber der Kurs weicht mehr als
  25 % vom gemeldeten Kaufpreis ab. Vermutlich gehört das Kürzel heute einer
  anderen Firma. Diese Fälle zählen zu „keine Meldung“, also zu −55 %.
- **ohne Firmendaten:** Die SEC hat keine Daten zur Firma. Ohne Branchencode
  gibt es kein Signal, genau wie live.

**Abgabe:** Schick `data/data_check.md` und `data/data_check.json` an
Bereich B (@Jumikage), zusammen mit einer kurzen Einordnung in drei bis fünf
Sätzen:

- das Ergebnis nach der Tabelle oben;
- welches Jahr den Ausschlag gab;
- ob Auffälliges im Log stand, z. B. viele Abbrüche, sehr viele Fälle ohne
  Firmendaten oder ein Jahr mit fast keinen Signalen.
