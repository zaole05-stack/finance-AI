# Plan: Historischer Backtest des Insider-Experten

Stand: 2026-11-26 · Bereich B (@Jumikage) · Ergebnis einer Brainstorm-Session,
nachgeschärft in einer Grill-Session am selben Tag

## Ziel

Bevor 6 Monate Paper Trading laufen, wird belastbar geklärt, ob und mit welchen
Regeln der Insider-Experte den Small-Cap-ETF nach Kosten schlägt.

**Warum:** Mit 10 Plätzen und 91 Tagen Haltedauer entstehen in 6 Monaten
höchstens etwa 20 Käufe. Grob geschätzt schwankt der Vorsprung eines solchen
Portfolios vor dem ETF um etwa ±10 Prozentpunkte. Ein echter Vorteil von
5 Punkten wäre davon kaum zu unterscheiden. Der Backtest liefert stattdessen
Tausende Signale über 20 Jahre.

Danach folgt das Paper Trading mit eingefrorenen Regeln. Dort wird jedes Signal
zusätzlich einzeln bewertet (Option B aus der Session, eigener Plan).

## Festgelegte Entscheidungen

### Daten (alle kostenlos)

| Was | Quelle | Hinweis |
|---|---|---|
| Insider-Meldungen | [SEC Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets), Quartals-ZIPs 2006 Q1 bis 2026 Q3 | ca. 80 Dateien, je 8–16 MB. 10b5-1-Kennzeichen (`AFF10B5ONE`) erst ab 2023. |
| Branchencode (SIC) | SEC, Firmenübersicht je CIK | heutiger Code, nicht historisch (kleiner Vorgriff, im Bericht nennen) |
| Aktienzahl für den historischen Börsenwert | SEC companyfacts je CIK (`dei:EntityCommonStockSharesOutstanding`) | Nur Werte, die vor dem Signaltag **eingereicht** wurden |
| Kurse | Yahoo Finance, Tageskurse | Für pleitegegangene oder delistete Firmen fehlen meist Kurse |
| Vergleich | IWM (Russell 2000) und IWC (Micro-Caps) | Der Team-ETF ist noch offen (KONZEPT.md) |

### Methode

- **Einstieg:** Eröffnungskurs am Handelstag nach dem Meldedatum. Die Datensätze
  haben nur ein Datum, keine Uhrzeit. Deshalb gilt jede Meldung als nach
  Börsenschluss eingegangen. Das ist strenger als die 1 Stunde Verzögerung live.
- **Gemessen wird zweifach:**
  1. jedes Signal einzeln: Rendite nach Kosten über die Haltedauer, minus ETF im
     selben Zeitraum;
  2. ein simuliertes 10er-Portfolio mit den echten Regeln aus `decide()` und
     `simulate()`.
- **Kein Blick in die Zukunft:** Börsenwert, Routinekäufer und gemeinsame Käufe
  nutzen nur Daten, die am Signaltag schon öffentlich waren.
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
- **Kosten:** das bestehende `CostModel`, zusätzlich eine Variante mit doppelter
  Slippage.

### Zeiträume

- **Einstellung:** 2006–2017. Nur hier wird verglichen und ausgewählt.
- **Sperre:** 2018 bis 2026 Q3. Wird **einmal** ausgewertet, nur für die
  Gewinnervariante, nachdem sie festgeschrieben ist. Ein Neulauf ist nur nach
  einem belegten Fehler erlaubt, mit derselben Variante und sichtbar
  protokolliert (Schritt 7).

### Varianten (vorher festgelegt, 2⁵ = 32)

Grundregeln für alle, wie in `insider.py`: Code P, nur Officers und Directors,
mindestens 25.000 USD je Meldung, keine Fonds, REITs und SPACs, kein
10b5-1-Plan (soweit markiert).

| Stellschraube | Stufe 1 | Stufe 2 |
|---|---|---|
| Wer kauft | alle Officers und Directors | nur oberste Führung (`_TOP_TITLES`) |
| Gemeinsame Käufe | auch Einzelkäufe | mind. 2 verschiedene Insider derselben Firma innerhalb von 30 Tagen. Signaltag ist der Tag, an dem die Bedingung erstmals erfüllt ist. |
| Routinekäufer | behalten | ausschließen: Die Person hat in jedem der 3 Vorjahre im selben Kalendermonat gekauft (nach Cohen, Malloy & Pomorski 2012) |
| Börsenwert | bis 2 Mrd. USD | bis 300 Mio. USD |
| Haltedauer | 91 Tage | 182 Tage |

### Auswahl und Erfolgskriterium

- **Auswahl (2006–2017):** Gewinner ist die Variante mit dem höchsten
  konservativen mittleren Vorsprung des 10er-Portfolios vor IWM je
  6-Monats-Fenster. Die Fenster beginnen monatlich und überlappen sich.
  Teilnehmen dürfen nur Varianten mit mindestens 50 Signalen pro Jahr.
- **Bestanden (Sperrzeitraum, konservativ)**, wenn beides gilt:
  1. Das Portfolio liegt im Mittel mindestens 5 Prozentpunkte je 6-Monats-Fenster
     vor dem ETF, und das in mindestens 60 % der Fenster.
  2. Der mittlere Vorsprung je Einzelsignal ist positiv. Die untere Grenze
     seines 95-%-Konfidenzintervalls liegt über null. Gerechnet wird mit einem
     Block-Bootstrap nach Kalendermonat, weil Signale im selben Monat
     zusammenhängen.
- **Knapp:** positiv, aber Kriterium 1 nicht erreicht.
- **Durchgefallen:** im Mittel nicht vor dem ETF.

| Ergebnis | Folge |
|---|---|
| Bestanden | Regeln einfrieren: Standard in `insider.py`, Vorschlag für `DecisionRules` an A. Danach Paper Trading. |
| Knapp | Paper Trading trotzdem, mit gedämpfter Erwartung. Dem Team melden. |
| Durchgefallen | Vor M6 im Team klären, ob der Dauerlauf mit dem Insider-Experten sinnvoll ist. |

### Nicht dabei (YAGNI)

Kein LLM, keine Verkaufssignale, keine weiteren Experten, keine Stundenkurse,
keine Optimierung über die 32 Varianten hinaus.

## Aufbau

| Datei | Bereich | Inhalt |
|---|---|---|
| `src/finance_ai/experts/insider.py` | B | Regeln in eine Funktion auf `Form4` herausziehen, die live und im Backtest gilt |
| `src/finance_ai/data/sec_insider_datasets.py` (neu) | B (CODEOWNERS ergänzen) | Quartals-ZIPs laden, zwischenspeichern, Zeilen → `Form4` |
| `src/finance_ai/data/sec_company.py` (neu) | B (CODEOWNERS ergänzen) | SIC und Aktienzahl-Historie je CIK |
| `src/finance_ai/paper_trading/daily_prices.py` (neu) | B (CODEOWNERS ergänzen, A fragen) | Yahoo-Tageskurse mit Zwischenspeicher als `PriceSource` |
| `src/finance_ai/evaluation/backtest.py` (neu) | B | Varianten, Messung, Auswahl, Sperre, CLI |
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

- [ ] Atom-Feed-Arbeit (`feat/insider-atom-feed`) committen und als eigenen PR
      abschicken.
- [ ] `.env` mit `SEC_USER_AGENT` anlegen (Name und E-Mail). Ohne sie lehnt die
      SEC automatische Downloads ab.
- [ ] Branch `feat/insider-backtest` von aktuellem `main`.
- [ ] `data/` in `.gitignore`.
- [ ] A Bescheid geben: Der Quartalsdaten-Lader aus Schritt 2 und der Datencheck
      aus Schritt 4b decken A's geplanten Nachlauf ab. So baut niemand
      dasselbe doppelt.

### 1. Gemeinsame Insider-Regeln

- [ ] `signal_from_form4(doc, accession, source_url, observed_at, issuer_sic,
      created_at, min_value)` aus `signal_from_filing` herausziehen.
      `signal_from_filing` ruft sie nur noch auf.
- [ ] Bestehende Insider-Tests bleiben unverändert grün.

### 2. Quartals-Datensätze

- [ ] Spaltennamen und Bedeutungen anhand der SEC-Dokumentation (PDF auf der
      Datensatz-Seite) prüfen: `SUBMISSION`, `REPORTINGOWNER`, `NONDERIV_TRANS`.
- [ ] Download je Quartal mit `EdgarClient`, gespeichert unter `data/raw/`.
      Bereits vorhandene Dateien werden nicht erneut geladen.
- [ ] Zeilen einer Meldung → `Form4` plus Meldedatum und Accession. Nur
      `DOCUMENT_TYPE` = 4, keine 4/A.
- [ ] Fixture: kleiner echter Ausschnitt aus einem Quartal mit einem bekannten
      Kauf. Prüfung: Er ergibt dasselbe Signal wie dieselbe Meldung über das XML.

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

Schritte 5–9 beginnen erst, wenn dieser Check bestanden ist.

- [ ] Grundregeln, ohne Varianten, für **2008** (Finanzkrise, härtester Fall)
      und **2015** (ruhiges Jahr). Beide liegen im Einstellungszeitraum, die
      Sperre bleibt unberührt.
- [ ] Gemessen wird nur die Datenqualität, **keine Renditen**:
  - Signale pro Jahr;
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

- [ ] Ergebnis des Checks an A geben. Es ist zugleich der Nachlauf „Signale pro
      Woche“ aus A's Startaufgabe, über einen längeren Zeitraum.

### 5. Signale je Variante

- [ ] Grundsignale aus allen Quartalen über die Regeln aus Aufgabe 1, mit
      Status: ok, kein Kurs, Kurs passt nicht, Börsenwert unbekannt.
- [ ] Stellschrauben: Rolle, gemeinsame Käufe, Routinekäufer, Börsenwert,
      Haltedauer. Jede nutzt nur Daten bis zum Signaltag. Für gemeinsame Käufe
      und Routinekäufer je ein Test, der einen Blick in die Zukunft entlarven
      würde.

### 6. Messung

- [ ] Vorsprung je Einzelsignal, optimistisch und konservativ, gegen IWM und IWC.
- [ ] 10er-Portfolio über `decide()` und `simulate()`, Lauf je Handelstag.
- [ ] 6-Monats-Fenster mit monatlichem Start: Mittelwert und Anteil der Fenster
      vor dem ETF.
- [ ] Block-Bootstrap nach Kalendermonat für das 95-%-Intervall.
- [ ] Variante mit doppelter Slippage.
- [ ] Prüfung: Für einen kleinen Fall mit festen Kursen stimmen die Zahlen mit
      einer Rechnung von Hand überein.

### 7. Auswahl und Sperre

- [ ] `python -m finance_ai.evaluation.backtest design` rechnet nur 2006–2017,
      speichert alle 32 Varianten und schreibt den Gewinner fest, mit Zeitstempel.
- [ ] `python -m finance_ai.evaluation.backtest holdout` rechnet 2018 bis 2026 Q3
      nur für den festgeschriebenen Gewinner und speichert das Urteil.
- [ ] Neulauf nach einem Fehler: Ein zweiter Lauf verlangt
      `--rerun "<Begründung>"` und nutzt immer dieselbe festgeschriebene
      Gewinnervariante. Die Auswahl wird nicht wiederholt. Vorher muss der
      Fehler durch einen Test belegt und die Korrektur im PR von einer zweiten
      Person bestätigt sein.
- [ ] Jeder Lauf wird mit Zeitstempel und Begründung gespeichert. Bericht und
      Dashboard zeigen alle Läufe, nicht nur den letzten.
- [ ] Tests: Ohne `--rerun` wird ein zweiter Lauf verweigert. Mit `--rerun`
      bleibt die Variante gleich, und der Lauf steht in der Liste.
- [ ] `design` liest keine Daten nach 2017. Der Test prüft das.

### 8. Bericht

- [ ] `docs/BACKTEST.md` erzeugen. Inhalt:
  - Varianten-Tabelle;
  - Gewinner und Urteil mit den drei Prüfwerten;
  - Spanne optimistisch/konservativ und Anteil ohne Kurs;
  - bekannte Lücken: 10b5-1 vor 2023, heutiger SIC, Yahoo.

### 9. Dashboard-Tab „Backtest“

- [ ] Liest nur `data/backtest.sqlite`, rechnet nichts selbst.
- [ ] Varianten-Übersicht 2006–2017 mit markiertem Gewinner.
- [ ] Sperrzeitraum: nur der Gewinner, Urteil, Vorsprung je 6-Monats-Fenster
      als Diagramm.
- [ ] Einzelsignale mit Quellenlink und Status.
- [ ] Keine Zahlen aus dem Sperrzeitraum für andere Varianten. Der Test prüft das.
- [ ] Ohne Backtest-Datei ein Hinweis, wie man ihn startet.

### 10. Abschluss

- [ ] CODEOWNERS: neue Dateien unter B eintragen.
- [ ] Voller Lauf: `design`, prüfen, dann einmal `holdout`.
- [ ] PR mit Bericht. Reviewer: A, weil CODEOWNERS und `docs/` betroffen sind.
- [ ] Ergebnis und Folge (Tabelle oben) im Team besprechen. `KONZEPT.md` und
      `PLAN.md` aktualisiert A.

## Erfolgskriterien für die Umsetzung

- Alle Offline-Tests grün, Netz-Tests mit `@pytest.mark.network`.
- Backtest und Live-Betrieb nutzen dieselbe Regel-Funktion für Insider-Signale.
- Der Sperrzeitraum ist nur für die festgeschriebene Variante ausgewertet.
  Jeder Lauf ist mit Zeitstempel und Begründung in `data/backtest.sqlite`
  belegt.
- `docs/BACKTEST.md` und der Dashboard-Tab zeigen dieselben Zahlen.

## Offen

- **Vergleichs-ETF:** im Team noch offen. Bis dahin IWM für die Auswahl, IWC
  als Zweitwert.
- **Laufzeit:** Wie lange der Yahoo-Abruf für einige Tausend Ticker dauert und
  ob Yahoo ihn drosselt. Das zeigt sich erst in Aufgabe 4.
- **Wert −55 %:** in Shumway & Warther (1999) nachprüfen, bevor er im Code steht.
- **Anteil ohne Kurs:** Darüber entscheidet der Datencheck (Schritt 4b), nicht
  erst das Ende.
