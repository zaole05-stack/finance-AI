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
- **Fehlende Kurse:** Das Ergebnis wird immer in drei Stufen ausgewiesen. Der
  Grund für das Verschwinden zählt nur, wenn die Aktie **während der
  Haltedauer** verschwand (plus 30 Tage Puffer, weil Delisting-Meldungen kurz
  vor oder nach dem letzten Handelstag eingehen). Sonst war die Position schon
  verkauft, und es fehlen nur die Kurse. Beispiel aus echten Daten: Yahoo führt
  unter DBD nur die neuen Aktien nach der Insolvenz 2023. Ein Kauf von 2015
  hat deshalb keinen Kurs, obwohl er normal verlief.

  | Fall (`MissingPrice`) | Optimistisch | **Vorsichtig-realistisch (entscheidet)** | Schlimmster Fall |
  |---|---|---|---|
  | Übernahme in der Haltedauer | fällt weg | 0 % | −100 % |
  | Pleite in der Haltedauer | fällt weg | −55 % | −100 % |
  | In der Haltedauer verschwunden, Grund unbekannt | fällt weg | −55 % | −100 % |
  | Erst nach der Haltedauer verschwunden | fällt weg | **fällt weg**, Ausgang unbekannt | −100 % |
  | Keine Meldung zum Verschwinden | fällt weg | −55 % | −100 % |

  Der schlimmste Fall ist eine Warnung und steht im Bericht ganz oben, wenn
  das Urteil dort kippt. Der Anteil jedes Falls steht immer im Bericht.

  Der Grund kommt aus den SEC-Meldungen der Firma: Insolvenz (8-K Punkt 1.03)
  hat Vorrang vor Übernahme (DEFM14A, SC TO-T, SC 14D9 …). Einen
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

Ein Lauf, zwei Abschnitte. Es wird nichts ausgewählt, deshalb braucht es keinen
gesperrten Teil. Maßgeblich für die Zuordnung ist der Signaltag.

| Abschnitt | Zeitraum | Regeln | Zählt fürs Urteil |
|---|---|---|---|
| **Stresstest Finanzkrise** | 1.1.2006 bis 30.6.2011 | alle Insider-Regeln, **ohne Börsenwert-Grenze** | nein |
| **Urteil** | 1.7.2011 bis 30.9.2026 | das vollständige Regelwerk | ja |

**Warum getrennt:** Die SEC liefert die Aktienzahl in auswertbarer Form (XBRL)
erst ab 2010 für große und ab Mitte 2011 für kleine Firmen. Davor lässt sich
der Börsenwert nicht bestimmen. Der Stresstest zeigt trotzdem, wie sich
Insider-Käufe in der Finanzkrise und der Erholung danach verhalten. Pleitefirmen
bleiben dabei drin, für sie gilt die Stufe mit −55 %. Ohne Grenze sind aber
auch größere Firmen enthalten. Der Abschnitt misst also Insider-Käufe allgemein
in der Krise, nicht exakt die Small-Cap-Strategie. Das steht so im Bericht.

Der Urteilsabschnitt wird zusätzlich in zwei Hälften gezeigt (Mitte 2011 bis
2018 und 2019 bis 2026 Q3). Das dient nur der Beschreibung: Hält das Ergebnis
in beiden Phasen, oder trägt eine allein?

### Erfolgskriterium (konservativ, Urteilsabschnitt)

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
- [x] Vor dem vollen Lauf prüfen, wie viele Signale durch die Rundung über
      oder unter die 25.000-USD-Schwelle rutschen. Im Bericht nennen.
      Höchstens 1,3 % (2008) und 1,1 % (2015), siehe
      [Befunde](2026-11-28-datencheck-befunde.md).

### 3. Firmendaten

- [x] SIC je CIK aus der Firmenübersicht der SEC, zwischengespeichert.
- [x] Aktienzahl-Historie aus companyfacts. `shares_at(day)` nimmt die Angabe
      mit dem jüngsten Stichtag aus Berichten, die vor `day` eingereicht wurden,
      Deckblatt (dei) vor Bilanz (us-gaap). Älter als 400 Tage oder ohne Wert:
      `None`, dann „Börsenwert unbekannt“ wie live.
- [x] Ereignisse je Firma für Schritt 4: Delisting (25, 25-NSE, 15-…),
      Übernahme (DEFM14A, SC TO-T, SC 14D9 …), Insolvenz (8-K Punkt 1.03).
      S-4 und 425 zählen nicht, die reicht oft der Käufer ein.
- [ ] Aktienzahl gilt vor späteren Splits: Börsenwert mit dem damaligen,
      nicht split-bereinigten Kurs rechnen (Schritt 4).
- [x] XBRL-Aktienzahlen gibt es erst ab 2010 (große) bzw. Mitte 2011 (kleine
      Firmen). Entschieden: 2006 bis Mitte 2011 läuft als Stresstest ohne
      Börsenwert-Grenze und zählt nicht fürs Urteil (siehe „Zeitraum“).

### 4. Tageskurse

- [x] Yahoo-Tageskurse je Ticker einmal laden und speichern, auch „nichts
      gefunden“. Wartezeit und Wiederholung bei Fehlern.
- [x] `PriceSource` mit zwei Kursen je Handelstag: Eröffnung (09:30 New York)
      und Schluss (16:00). So arbeiten `decide()` und `simulate()` unverändert.
- [x] Split-Faktoren aus den Yahoo-Daten, `raw_close` rechnet den damaligen
      Kurs zurück (geprüft an AAPL, 4:1-Split 2020).
- [x] Rückgriff auf die heutigen Kürzel der Firma. Sie kommen aus den
      SEC-Stammdaten (`submissions`), `company_tickers.json` ist nicht nötig.
- [x] Grund für fehlende Kurse aus den SEC-Meldungen: Übernahme, Pleite oder
      unbekannt. Insolvenz hat Vorrang.
- [x] Befund aus echten Daten: Yahoo führt unter DBD nur die neuen Aktien ab
      August 2023. Entschieden: Der Grund zählt nur, wenn die Aktie während
      der Haltedauer verschwand (`CompanyInfo.missing_price_case`, Tabelle
      unter „Methode“).

### 4b. Datencheck: weiter oder nicht

Schritte 5–9 beginnen erst, wenn dieser Check bestanden ist. Er braucht das
Regelwerk noch nicht. Anleitung zum Ausführen:
[2026-11-26-datencheck-uebergabe.md](2026-11-26-datencheck-uebergabe.md).

- [ ] Insider-Grundregeln für **2008** (Finanzkrise, härtester Fall, aus dem
      Stresstest) und **2015** (ruhiges Jahr, aus dem Urteilsabschnitt).
- [ ] Gemessen wird nur die Datenqualität, **keine Renditen**:
  - Signale pro Woche und pro Jahr;
  - Anteil mit Kurs;
  - Anteil, der erst über das heutige Kürzel gefunden wird;
  - Anteil ohne Kurs, aufgeteilt nach den fünf Fällen aus „Methode“.
- [ ] Entscheidung nach dem Anteil, der in der mittleren Stufe mit −55 %
      eingeht (Pleite, Grund unbekannt, keine Meldung), im schlechteren der
      beiden Jahre:

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

- [x] Signale aus allen Quartalen über die Regeln aus Aufgabe 1, mit Status: ok,
      kein Kurs, Kurs passt nicht, Börsenwert unbekannt (`evaluation/backtest.py`).
      Auch Signale ohne Kurs bekommen einen Börsenwert (Aktienzahl × gemeldeter
      Kaufpreis), damit die Grenze für alle drei Stufen gilt.
- [ ] Vor Schritt 6: Entscheidung zu den 50–63 % Signalen, die in der
      mittleren Stufe wegfallen ([Befunde](2026-11-28-datencheck-befunde.md),
      Abschnitt 1).
- [x] Für jedes Kriterium, das Historie braucht, ein Test, der einen Blick in
      die Zukunft entlarven würde (Aktienzahl, Kurs für den Börsenwert,
      Abschnitt). Für Routinekäufer folgt er mit dem Kriterium.

### 6. Messung

- [ ] Vorsprung je Einzelsignal in drei Stufen, gegen den ETF aus dem Regelwerk
      (bis dahin IWM, IWC als Zweitwert).
- [ ] Portfolio über `decide()` und `simulate()` mit den Regeln aus dem
      Regelwerk, Lauf je Handelstag. Im Stresstest ohne Börsenwert-Funktion
      (`market_cap=None`), sonst unverändert.
- [ ] 6-Monats-Fenster mit monatlichem Start: Mittelwert und Anteil der Fenster
      vor dem ETF. Getrennt für Stresstest, Urteilsabschnitt und dessen
      beide Hälften.
- [ ] Test: Das Urteil nutzt keine Signale vor dem 1.7.2011.
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
  - Stresstest Finanzkrise getrennt, mit dem Hinweis „ohne Börsenwert-Grenze“;
  - beide Hälften des Urteilsabschnitts getrennt;
  - Empfindlichkeit bei doppelter Slippage;
  - alle Läufe;
  - bekannte Lücken: 10b5-1 vor 2023, heutiger SIC, Yahoo.

### 9. Dashboard-Tab „Backtest“

- [ ] Liest nur `data/backtest.sqlite`, rechnet nichts selbst.
- [ ] Regelwerk, Urteil, drei Stufen, beide Hälften.
- [ ] Stresstest Finanzkrise als eigener Abschnitt, deutlich als
      „zählt nicht fürs Urteil, ohne Börsenwert-Grenze“ gekennzeichnet.
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
  hat dafür schon einen Tag „opportunistischer Käufer“ vorgesehen. Die Definition im
  Papier verlangt drei Jahre Historie, siehe [Befunde](2026-11-28-datencheck-befunde.md),
  Abschnitt 3.
- **Wert −55 %:** in Shumway & Warther (1999) nachprüfen, bevor er im Code steht.
  Geprüft, mit Einschränkung: [Befunde](2026-11-28-datencheck-befunde.md),
  Abschnitt 2.
- **Laufzeit:** Wie lange der Yahoo-Abruf für einige Tausend Ticker dauert und
  ob Yahoo ihn drosselt. Das zeigt sich erst in Schritt 4.
