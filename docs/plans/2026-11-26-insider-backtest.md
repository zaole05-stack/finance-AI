# Plan: Historischer Backtest des Insider-Experten

Stand: 2026-11-26 · Bereich B (@Jumikage) · Ergebnis einer Brainstorm-Session,
nachgeschärft in einer Grill-Session am selben Tag. Nach
[BEREICH-A.md](../BEREICH-A.md) auf eine reine Bestätigung umgestellt.

## Ziel

Bevor 6 Monate Paper Trading laufen, wird geprüft, ob **genau das Regelwerk,
das für den Testlauf eingefroren wird**, den Small-Cap-ETF in der
Vergangenheit nach Kosten geschlagen hätte.

**Warum:** Mit 10 Plätzen und 91 Tagen Haltedauer entstehen in 6 Monaten
höchstens etwa 20 Käufe. Grob geschätzt schwankt der Vorsprung eines solchen
Portfolios vor dem ETF um etwa ±10 Prozentpunkte. Ein echter Vorteil von
5 Punkten wäre davon kaum zu unterscheiden. Der Backtest liefert stattdessen
Tausende Signale über 20 Jahre.

**Reine Bestätigung, keine Auswahl.** Das folgt aus Beschluss 1 in
BEREICH-A.md: Kriterien kommen aus Studien, nicht aus den eigenen Daten. Es
gibt deshalb genau ein Regelwerk. Es steht fest, bevor der Backtest rechnet,
und wird durch das Ergebnis nicht verändert. Der Backtest beantwortet nur:
Hält das Regelwerk, was die Studien versprechen?

Danach folgt das Paper Trading mit demselben Regelwerk. Dort wird jedes Signal
zusätzlich einzeln bewertet (Option B aus der Session, eigener Plan).

## Festgelegte Entscheidungen

### Das geprüfte Regelwerk

Es besteht aus zwei Teilen. Beide müssen feststehen, bevor der volle Lauf
startet (Schritt 7).

| Teil | Wer legt fest | Inhalt |
|---|---|---|
| Insider-Regeln | B, begründet mit Studien | Code P, nur Officers und Directors, mindestens 25.000 USD je Meldung, keine Fonds, REITs und SPACs, kein 10b5-1-Plan (soweit markiert). Oberste Führung als Tag statt höherer `confidence` (BEREICH-A.md, Punkt 11–12). Weitere Kriterien siehe „Offen“. |
| Entscheidungsregeln | A (BEREICH-A.md, offene Punkte 1–2), ETF das Team | Haltedauer, Plätze, Startkapital, Kosten, Börsenwert-Grenze, Vergleichs-ETF |

Der Backtest liest das Regelwerk aus derselben Quelle wie der Testlauf. Er
hat keine eigenen Stellschrauben.

### Daten (alle kostenlos)

| Was | Quelle | Hinweis |
|---|---|---|
| Insider-Meldungen | [SEC Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets), Quartals-ZIPs 2006 Q1 bis 2026 Q3 | ca. 80 Dateien, je 8–16 MB. 10b5-1-Kennzeichen (`AFF10B5ONE`) erst ab 2023. |
| Branchencode (SIC) | SEC, Firmenübersicht je CIK | heutiger Code, nicht historisch (kleiner Vorgriff, im Bericht nennen) |
| Aktienzahl für den historischen Börsenwert | SEC companyfacts je CIK (`dei:EntityCommonStockSharesOutstanding`) | Nur Werte, die vor dem Signaltag **eingereicht** wurden. Behebt den Einwand aus BEREICH-A.md, Punkt 4: Der Börsenwert ist der damalige, nicht der heutige. |
| Kurse | Yahoo Finance, Tageskurse | Für pleitegegangene oder delistete Firmen fehlen meist Kurse |
| Vergleich | Team-ETF, sobald festgelegt. Bis dahin IWM (Russell 2000) und IWC (Micro-Caps). | |

### Methode

- **Einstieg:** Eröffnungskurs am Handelstag nach dem Meldedatum. Die Datensätze
  haben nur ein Datum, keine Uhrzeit. Deshalb gilt jede Meldung als nach
  Börsenschluss eingegangen. Das ist strenger als die 1 Stunde Verzögerung live.
- **Gemessen wird zweifach:**
  1. jedes Signal einzeln: Rendite nach Kosten über die Haltedauer, minus ETF im
     selben Zeitraum;
  2. ein simuliertes Portfolio mit den Entscheidungsregeln aus `decide()` und
     `simulate()`, mit Plätzen und Startkapital aus dem Regelwerk.
- **Kein Blick in die Zukunft:** Börsenwert und alle Insider-Kriterien nutzen
  nur Daten, die am Signaltag schon öffentlich waren.
- **Fehlende Kurse:** Das Ergebnis wird immer in drei Stufen ausgewiesen.

  | Stufe | Signale ohne Kurs zählen als | Zweck |
  |---|---|---|
  | Optimistisch | fallen weg | Obergrenze |
  | **Vorsichtig-realistisch** | Übernahme: 0 %. Pleite oder Grund unbekannt: −55 %. | **entscheidet** |
  | Schlimmster Fall | −100 % | Warnung, steht im Bericht ganz oben, wenn das Urteil dort kippt |

  Der Grund kommt aus den SEC-Meldungen der Firma: Fusionsunterlagen wie
  DEFM14A oder SC TO-T vor dem Verschwinden gelten als Übernahme. Einen
  Übernahmeaufschlag rechnen wir bewusst nicht ein. Der Wert −55 % beruht auf
  Shumway & Warther (1999, *Journal of Finance*), delistete Nasdaq-Werte. Er
  ist vor der Umsetzung in der Studie nachzuprüfen.

  Jede Bezeichnung „konservativ“ in diesem Plan meint die mittlere Stufe. Die
  Anteile je Stufe stehen immer im Bericht.
- **Wiederverwendete Kürzel:** Weicht der Yahoo-Schlusskurs am Kauftag um mehr
  als 25 % vom gemeldeten Kaufpreis ab, gilt das Signal als „Kurs passt nicht“
  und zählt wie „kein Kurs“. Für den Vergleich werden die Yahoo-Kurse um
  spätere Aktiensplits zurückgerechnet.
- **Geänderte Kürzel:** Findet Yahoo das damalige Kürzel nicht, wird das heutige
  Kürzel der Firma versucht. Es steht in der Zuordnung von Firmennummer (CIK) zu
  Kürzel bei der SEC (`company_tickers.json`). Erst danach gilt ein Signal als
  „kein Kurs“.
- **Kosten:** das `CostModel` aus dem Regelwerk, zusätzlich eine Rechnung mit
  doppelter Slippage. Sie fließt nicht ins Urteil, sie zeigt nur, wie
  empfindlich das Ergebnis auf Kosten reagiert.

### Zeitraum

- **2006 bis 2026 Q3 in einem Lauf.** Es wird nichts ausgewählt, deshalb braucht
  es keinen gesperrten Teil.
- Der Bericht zeigt zusätzlich die beiden Hälften 2006–2017 und 2018 bis
  2026 Q3 getrennt. Das dient nur der Beschreibung: Hält das Ergebnis in beiden
  Phasen, oder trägt eine allein?

### Erfolgskriterium (konservativ, ganzer Zeitraum)

- **Bestanden**, wenn beides gilt:
  1. Das Portfolio liegt im Mittel mindestens 5 Prozentpunkte je 6-Monats-Fenster
     vor dem ETF, und das in mindestens 60 % der Fenster. Die Fenster beginnen
     monatlich und überlappen sich.
  2. Der mittlere Vorsprung je Einzelsignal ist positiv. Die untere Grenze
     seines 95-%-Konfidenzintervalls liegt über null. Gerechnet wird mit einem
     Block-Bootstrap nach Kalendermonat, weil Signale im selben Monat
     zusammenhängen.
- **Knapp:** positiv, aber Kriterium 1 nicht erreicht.
- **Durchgefallen:** im Mittel nicht vor dem ETF.

| Ergebnis | Folge |
|---|---|
| Bestanden | Paper Trading mit genau diesem Regelwerk starten. |
| Knapp | Paper Trading trotzdem, mit gedämpfter Erwartung. Dem Team melden. |
| Durchgefallen | Vor M6 im Team klären, ob der Dauerlauf sinnvoll ist. Ein neues Regelwerk braucht neue Begründung aus Studien, **nicht** aus diesem Ergebnis, und einen neuen Backtest. |

### Lauf und Neulauf

- Der volle Lauf rechnet **einmal**, sobald das Regelwerk feststeht. Er wird mit
  Zeitstempel und einem Fingerabdruck des Regelwerks gespeichert.
- Neulauf nur nach einem belegten Fehler im Code. Das entspricht Beschluss 2
  in BEREICH-A.md. Bedingungen:
  - Der Fehler ist durch einen Test belegt.
  - Die Korrektur ist im PR von einer zweiten Person bestätigt.
  - Das Regelwerk bleibt unverändert, der Fingerabdruck muss gleich sein.
  - Jeder Lauf ist mit Begründung protokolliert. Bericht und Dashboard zeigen
    alle Läufe.
- Ändert sich das Regelwerk, ist das eine Strategie-Änderung und ein neuer
  Backtest, kein Neulauf.

### Nicht dabei (YAGNI)

Keine Varianten, keine Auswahl, kein LLM, keine Verkaufssignale, keine
weiteren Experten, keine Stundenkurse.

## Aufbau

| Datei | Bereich | Inhalt |
|---|---|---|
| `src/finance_ai/experts/insider.py` | B | Regeln in eine Funktion auf `Form4` herausziehen, die live und im Backtest gilt |
| `src/finance_ai/data/sec_insider_datasets.py` (neu) | B (CODEOWNERS ergänzen) | Quartals-ZIPs laden, zwischenspeichern, Zeilen → `Form4` |
| `src/finance_ai/data/sec_company.py` (neu) | B (CODEOWNERS ergänzen) | SIC, Aktienzahl-Historie, heutiges Kürzel, Grund des Verschwindens je CIK |
| `src/finance_ai/paper_trading/daily_prices.py` (neu) | B (CODEOWNERS ergänzen, A fragen) | Yahoo-Tageskurse mit Zwischenspeicher als `PriceSource` |
| `src/finance_ai/evaluation/backtest.py` (neu) | B | Signale, Messung, Lauf und Neulauf, CLI |
| `src/finance_ai/evaluation/backtest_report.py` (neu) | B | `docs/BACKTEST.md` erzeugen |
| `src/finance_ai/dashboard/app.py`, `dashboard/backtest_view.py` (neu) | B | Tab „Backtest“ |
| `tests/test_backtest.py`, `tests/fixtures/insider_datasets/` (neu) | B (CODEOWNERS ergänzen) | Tests |
| `data/backtest.sqlite`, `data/raw/` | lokal | Ergebnisse, Downloads, Kurse. Nicht committet. |

Die Haupt-Datenbank und `core/` bleiben unberührt (Teamregel 1). `decide()`
und `simulate()` werden nur aufgerufen, nicht geändert. Der Börsenwert-Filter
bekommt je Lauf eine Funktion, die an den Stichtag gebunden ist. Dafür muss die
Schnittstelle `MarketCapLookup` nicht geändert werden.

## Aufgaben

Jede Code-Aufgabe nach TDD: erst ein Test, der das Verhalten prüft und
fehlschlägt, dann die kleinste Umsetzung, dann aufräumen.

### 0. Vorher

- [x] Atom-Feed-Arbeit committet und gepusht (`feat/insider-atom-feed`).
- [ ] PR für den Atom-Feed öffnen.
- [ ] `.env` mit `SEC_USER_AGENT` anlegen (Name und E-Mail). Ohne sie lehnt die
      SEC automatische Downloads ab.
- [x] Branch `feat/insider-backtest` von aktuellem `main`.
- [x] `/data/` in `.gitignore`.
- [ ] Abstimmung mit A:
  - Backtest als reine Bestätigung des Regelwerks;
  - der Datencheck (4b) ersetzt A's Zählung im EDGAR-Nachlauf;
  - A's Einwand zum heutigen Börsenwert ist mit der SEC-Aktienzahl gelöst;
  - Tag für oberste Führung statt `confidence` 0,6.

### 1. Gemeinsame Insider-Regeln

- [x] `signal_from_form4(doc, accession, source_url, observed_at, issuer_sic,
      created_at, min_value)` aus `signal_from_filing` herausziehen.
      `signal_from_filing` ruft sie nur noch auf.
- [x] Bestehende Insider-Tests bleiben unverändert grün.
- [ ] Umstellung auf Tags statt 0,6, sobald `Signal.tags` in `core/` da ist
      (A, BEREICH-A.md Punkt 12).

### 2. Quartals-Datensätze

- [x] Spaltennamen und Bedeutungen anhand der SEC-Dokumentation (PDF auf der
      Datensatz-Seite) prüfen: `SUBMISSION`, `REPORTINGOWNER`, `NONDERIV_TRANS`.
- [x] Download je Quartal mit `EdgarClient`, gespeichert unter `data/raw/`.
      Bereits vorhandene Dateien werden nicht erneut geladen. Die Adressen
      kommen von der Übersichtsseite, weil die Pfade je Quartal verschieden sind.
- [x] Zeilen einer Meldung → `Form4` plus Meldedatum und Accession. Nur
      `DOCUMENT_TYPE` = 4, keine 4/A.
- [x] Fixture: kleiner echter Ausschnitt aus einem Quartal mit einem bekannten
      Kauf. Prüfung: Er ergibt dasselbe Signal wie dieselbe Meldung über das XML.
      Abweichung: Die Datensätze runden Preise auf 2 Stellen.
- [ ] Vor dem vollen Lauf prüfen, wie viele Signale durch die Rundung über
      oder unter die 25.000-USD-Schwelle rutschen. Im Bericht nennen.

### 3. Firmendaten

- [ ] SIC je CIK aus der Firmenübersicht der SEC, zwischengespeichert.
- [ ] Aktienzahl-Historie aus companyfacts. `shares_at(cik, day)` nimmt den
      letzten Wert, der vor `day` eingereicht wurde. Ohne Wert: `None`, dann
      „Börsenwert unbekannt“ wie live.

### 4. Tageskurse

- [ ] Yahoo-Tageskurse je Ticker einmal laden und speichern. Die Quelle kann als
      Erstes ausfallen, deshalb Wartezeit und Wiederholung einbauen.
- [ ] `PriceSource` mit zwei Kursen je Handelstag: Eröffnung (09:30 New York)
      und Schluss (16:00). So arbeiten `decide()` und `simulate()` unverändert.
- [ ] Split-Historie laden, um den damaligen Kurs für die Kürzel-Prüfung
      zurückzurechnen.
- [ ] Rückgriff auf das heutige Kürzel über `company_tickers.json`.
- [ ] Grund für fehlende Kurse bestimmen: Übernahme oder Pleite/unbekannt, aus
      der Liste der SEC-Meldungen der Firma.

### 4b. Datencheck: weiter oder nicht

Schritte 5–9 beginnen erst, wenn dieser Check bestanden ist. Er braucht das
Regelwerk noch nicht.

- [ ] Insider-Grundregeln für **2008** (Finanzkrise, härtester Fall) und
      **2015** (ruhiges Jahr).
- [ ] Gemessen wird nur die Datenqualität, **keine Renditen**:
  - Signale pro Woche und pro Jahr;
  - Anteil mit Kurs;
  - Anteil, der erst über das heutige Kürzel gefunden wird;
  - Anteil ohne Kurs, aufgeteilt in Übernahme und Pleite/unbekannt.
- [ ] Entscheidung nach dem Anteil Pleite/unbekannt im schlechteren der beiden
      Jahre:

| Anteil | Folge |
|---|---|
| bis 10 % | weiter mit Schritt 5–9 |
| 10–20 % | weiter. Im Bericht steht ganz oben: „Ergebnis hängt stark an der Annahme zu fehlenden Kursen“. |
| über 20 % | Stopp. Im Team andere Wege besprechen, z. B. nur Firmen von 300 Mio. bis 2 Mrd. USD oder bessere Kursdaten. |

Grund für die Schwellen: Der Anteil *p*, der mit −55 % eingeht, verschiebt den
mittleren Vorsprung um etwa 0,55 × *p*. Bei 10 % sind das rund 5,5 Punkte.
Mehr sollte die Annahme nicht bewegen, sonst entscheidet sie statt des Signals.

- [ ] Ergebnis an A geben. Die Signale pro Woche beantworten A's Frage aus
      BEREICH-A.md, Punkt 4: Füllen sich die Plätze überhaupt?

### 5. Signale

- [ ] Signale aus allen Quartalen über die Regeln aus Aufgabe 1, mit Status: ok,
      kein Kurs, Kurs passt nicht, Börsenwert unbekannt.
- [ ] Für jedes Kriterium, das Historie braucht, ein Test, der einen Blick in
      die Zukunft entlarven würde.

### 6. Messung

- [ ] Vorsprung je Einzelsignal in drei Stufen, gegen den ETF aus dem Regelwerk
      (bis dahin IWM, IWC als Zweitwert).
- [ ] Portfolio über `decide()` und `simulate()` mit den Regeln aus dem
      Regelwerk, Lauf je Handelstag.
- [ ] 6-Monats-Fenster mit monatlichem Start: Mittelwert und Anteil der Fenster
      vor dem ETF. Zusätzlich getrennt für die beiden Hälften.
- [ ] Block-Bootstrap nach Kalendermonat für das 95-%-Intervall.
- [ ] Rechnung mit doppelter Slippage.
- [ ] Prüfung: Für einen kleinen Fall mit festen Kursen stimmen die Zahlen mit
      einer Rechnung von Hand überein.

### 7. Lauf und Neulauf

- [ ] `python -m finance_ai.evaluation.backtest run` liest das Regelwerk,
      rechnet und speichert Urteil, Zeitstempel und Fingerabdruck des
      Regelwerks.
- [ ] Ein zweiter Lauf verlangt `--rerun "<Begründung>"` und verweigert sich,
      wenn der Fingerabdruck abweicht.
- [ ] Tests: Ohne `--rerun` wird ein zweiter Lauf verweigert. Mit `--rerun`
      und geändertem Regelwerk ebenfalls. Mit `--rerun` und gleichem
      Regelwerk steht der Lauf in der Liste.

### 8. Bericht

- [ ] `docs/BACKTEST.md` erzeugen. Inhalt:
  - geprüftes Regelwerk mit Fingerabdruck;
  - Urteil mit den Prüfwerten;
  - drei Stufen und Anteil ohne Kurs;
  - beide Hälften getrennt;
  - Empfindlichkeit bei doppelter Slippage;
  - alle Läufe;
  - bekannte Lücken: 10b5-1 vor 2023, heutiger SIC, Yahoo.

### 9. Dashboard-Tab „Backtest“

- [ ] Liest nur `data/backtest.sqlite`, rechnet nichts selbst.
- [ ] Regelwerk, Urteil, drei Stufen, beide Hälften.
- [ ] Vorsprung je 6-Monats-Fenster als Diagramm.
- [ ] Einzelsignale mit Quellenlink und Status.
- [ ] Liste aller Läufe mit Begründung.
- [ ] Ohne Backtest-Datei ein Hinweis, wie man ihn startet.

### 10. Abschluss

- [ ] CODEOWNERS: neue Dateien unter B eintragen.
- [ ] Voller Lauf, sobald das Regelwerk feststeht.
- [ ] PR mit Bericht. Reviewer: A, weil CODEOWNERS und `docs/` betroffen sind.
- [ ] Ergebnis und Folge (Tabelle oben) im Team besprechen. `KONZEPT.md` und
      `PLAN.md` aktualisiert A.

## Abhängigkeiten

| Braucht | Von | Für |
|---|---|---|
| Haltedauer, Plätze, Startkapital | A (BEREICH-A.md, offene Punkte 1–2) | Schritt 6 und 7 |
| Vergleichs-ETF | Team (KONZEPT.md) | Schritt 7. Bis dahin IWM und IWC. |
| `Signal.tags` | A (BEREICH-A.md, Punkt 12) | Umstellung in Schritt 1 |

Schritt 1–5 und der Datencheck laufen ohne diese Entscheidungen.

## Erfolgskriterien für die Umsetzung

- Alle Offline-Tests grün, Netz-Tests mit `@pytest.mark.network`.
- Backtest und Live-Betrieb nutzen dieselbe Regel-Funktion für Insider-Signale
  und dasselbe Regelwerk.
- Jeder Lauf ist mit Zeitstempel, Begründung und Fingerabdruck des Regelwerks
  in `data/backtest.sqlite` belegt.
- `docs/BACKTEST.md` und der Dashboard-Tab zeigen dieselben Zahlen.

## Offen

- **Weitere Insider-Kriterien aus Studien:** Vorschlag ist, Routinekäufer
  auszuschließen (Cohen, Malloy & Pomorski 2012). Routinekäufer ist, wer in
  jedem der 3 Vorjahre im selben Kalendermonat gekauft hat. Die Historie dafür
  liefern die Quartalsdaten auch live. B entscheidet vor dem vollen Lauf, A
  hat dafür schon einen Tag „opportunistischer Käufer“ vorgesehen.
- **Wert −55 %:** in Shumway & Warther (1999) nachprüfen, bevor er im Code steht.
- **Laufzeit:** Wie lange der Yahoo-Abruf für einige Tausend Ticker dauert und
  ob Yahoo ihn drosselt. Das zeigt sich erst in Schritt 4.
