# Befunde zum Datencheck und zu den offenen Punkten des Backtest-Plans

Stand: 2026-11-28. Ergänzt [2026-11-26-insider-backtest.md](2026-11-26-insider-backtest.md).
Alle Zahlen kommen aus den Daten von 2008 und 2015, die für den Datencheck
schon lokal lagen. **Es wurden keine Renditen berechnet oder angesehen.**

## 1. Der Datencheck misst die falsche Größe

Schritt 4b entscheidet nach dem Anteil, der mit −55 % eingeht. Der ist klein
(4,4 % und 3,3 %). Viel größer ist aber der Anteil, der in der entscheidenden
mittleren Stufe **ganz wegfällt**, weil die Aktie erst nach der Haltedauer
verschwand:

| Jahr | Signale | messbar (ok) | wegfallend | mit −55 % |
|---|---|---|---|---|
| 2008 | 10.226 | 32,2 % | 62,7 % | 4,4 % |
| 2015 | 6.507 | 40,7 % | 50,0 % | 3,3 % |
| 2015, Börsenwert bekannt und ≤ 2 Mrd. USD | 4.294 | 42,3 % | 53,4 % | 3,6 % |

Das Urteil stünde damit auf 30–45 % der Signale. Und die sind keine
Zufallsauswahl: Es sind die Firmen, die Yahoo heute noch führt.

**Die Lücke ist dort am größten, wo die Strategie kauft** (2015, Börsenwert
aus Aktienzahl × gemeldetem Kaufpreis):

| Börsenwert | mit Kurs | wegfallend | übrige ohne Kurs |
|---|---|---|---|
| unter 50 Mio. | 28 % | 53 % | 19 % |
| 50–300 Mio. | 38 % | 59 % | 3 % |
| 300 Mio.–2 Mrd. | 50 % | 48 % | 1 % |
| über 2 Mrd. | 64 % | 35 % | 1 % |

**Die wegfallenden Firmen sind anders.** Spätere Meldungen bei der SEC
(irgendwann nach der Haltedauer):

| | später Insolvenz (8-K 1.03) | später Übernahme |
|---|---|---|
| wegfallend 2008 | 19,2 % | 72,5 % |
| mit Kurs 2008 | 1,8 % | 23,1 % |
| wegfallend 2015 | 18,8 % | 77,4 % |
| mit Kurs 2015 | 1,7 % | 16,9 % |

Die erste solche Meldung kommt im Median 3,6 bis 4 Jahre nach dem Signal
(2008: 1.444 Tage, 2015: 1.304), bei 90 % erst nach mehr als 350 Tagen. Die Haltedauer selbst
verlief also meist normal, nur fehlen ihre Kurse.

**In welche Richtung das verzerrt, ist offen.** Später pleite gegangene Firmen
sprechen für schlechtere Renditen der Weggefallenen. Übernommene Firmen, oft
mit Aufschlag, sprechen für bessere. Ohne Renditen lässt sich das nicht
beziffern, und ansehen dürfen wir sie nicht.

**Warum die Kurse fehlen** (Signale ohne Kurs):

| Ursache | 2008 | 2015 |
|---|---|---|
| Yahoo kennt keines der Kürzel | 5.545 | 2.838 |
| Kürzel bei Yahoo erst ab einem späteren Datum (wiederverwendet oder neu notiert) | 1.065 | 468 |
| Kurse vorhanden, passen aber nicht zum Kaufpreis | 287 | 179 |
| kein gültiges Kürzel in der Meldung | 36 | 6 |

Stichproben zeigen außerdem, dass Yahoo die alte Historie nach einer
Umstrukturierung verwirft: LEA erst ab 11/2009, Chesapeake (CHK → EXE) erst ab
2021, Cree (CREE → WOLF) erst ab 2025. Am Code lässt sich das nicht beheben.
Es ist eine Grenze der Quelle.

### Vorschlag

Bevor Schritt 6 rechnet, braucht es eine Entscheidung im Team. Sie muss fallen,
ohne dass jemand Renditen gesehen hat:

1. **Bessere Kursquelle mit delisteten Aktien.** Am saubersten wäre CRSP über
   WRDS. Ob die HWR Zugang hat, ist offen. Andere Hochschulen regeln das über
   die Bibliothek oder den Lehrstuhl, etwa
   [Mannheim](https://www.bib.uni-mannheim.de/en/subject-specific-research/business-studies/company-and-finance-databases)
   und [Hamburg](https://www.bwl.uni-hamburg.de/en/finance/forschung/data.html).
   Kostenpflichtige Anbieter (Sharadar, EODHD, Norgate) werben mit delisteten
   Kursen, ungeprüft. Tiingo führt delistete Kürzel laut eigener Doku nur,
   solange sie nicht neu vergeben sind
   ([Symbology](https://api.tiingo.com/documentation/appendix/symbology)).
2. **Schwelle in 4b ergänzen:** zusätzlich ein Mindestanteil messbarer Signale
   im Zielsegment, etwa 70 %. Mit Yahoo würde der Check dann klar durchfallen.
3. **Weiter mit Yahoo, aber offen ausweisen:** Der Bericht nennt ganz oben,
   dass das Urteil nur für Firmen gilt, die bis heute bei Yahoo geführt werden.
   Die schlimmste Stufe (−100 % für alle ohne Kurs) bleibt dabei als Grenze
   drin, sagt aber wenig.

Meine Empfehlung: zuerst 1 klären, also bei der HWR-Bibliothek nach WRDS/CRSP
fragen. Sonst 3, mit 2 als ehrlicher Kennzahl im Bericht.

## 2. Der Wert −55 % (Shumway & Warther 1999)

Bestätigt: Der Aufsatz (*Journal of Finance* 54(6), 2361–2379) schätzt, dass
−55 % für fehlende Delisting-Renditen bei **leistungsbedingten**
Delistings an der Nasdaq die Verzerrung in CRSP beheben
([RePEc](https://ideas.repec.org/a/bla/jfinan/v54y1999i6p2361-2379.html)).

Einschränkung: Gemeint ist die Rendite vom letzten CRSP-Kurs bis nach dem
Delisting, nicht die Rendite ab Kauf. Wir setzen den Wert für die ganze
Haltedauer ein, und zwar dann, wenn gar kein Kurs da ist. Das passt nicht
genau:

- Bei Pleite in der Haltedauer fehlt der Kursverfall vor dem Delisting. −55 %
  ist dann eher zu mild.
- Bei „keine Meldung zum Verschwinden“ (2008: 2,3 %, 2015: 2,6 %) ist unklar,
  ob die Firma überhaupt verschwand. −55 % ist dann eher zu hart.
- „Grund unbekannt“ enthält auch freiwillige Abmeldungen (15-12G), die nicht
  leistungsbedingt sein müssen.

Für das Urteil ändert das wenig, weil diese Fälle unter 5 % liegen. Im
Bericht sollte es als Annahme mit Quelle stehen, nicht als belegter Wert.

## 3. Routinekäufer nach Cohen, Malloy & Pomorski (2012)

Geprüft am Arbeitspapier ([NBER w16454](https://www.nber.org/papers/w16454),
S. 12–13 und Tabelle III; veröffentlicht in *Journal of Finance* 67,
1009–1044):

- Eingestuft wird nur, wer in **jedem der drei Vorjahre mindestens einmal
  gehandelt** hat. Gezählt werden Käufe und Verkäufe am offenen Markt.
- Routinehändler ist, wer drei Jahre in Folge im selben Kalendermonat
  gehandelt hat. Alle anderen mit dieser Historie gelten als opportunistisch.
- Eingestuft wird zu Beginn jedes Kalenderjahres, nur mit vergangenen Daten.
- Andere Rückblicke (1–5 Jahre) ergeben laut den Autoren ähnliche
  Ergebnisse (Fußnote 9).
- Die Stichprobe schrumpft dadurch auf etwa ein Drittel aller Insider-Trades
  und ist zu größeren Firmen verschoben.
- Opportunistische Käufe bringen im Folgemonat 90 Basispunkte mehr als
  Insider-Trades insgesamt (t = 4,64), Routinekäufe 14 (t = 0,81).
  Zeitraum 1986–2007, Horizont ein Monat.

**Folge für unser Regelwerk:** „Routinekäufer ausschließen“ ist nicht dasselbe
wie das Papier. Unsere Signale enthalten auch Insider ohne dreijährige
Historie. Für die hat das Papier keine Aussage. Es gibt zwei saubere Wege:

- die Regel genau wie im Papier übernehmen: nur Insider mit Historie,
  opportunistische behalten. Dann gibt es deutlich weniger Signale;
- nur Routinekäufer ausschließen und die Abweichung im Bericht nennen.

B entscheidet vor dem vollen Lauf, begründet mit dem Papier, nicht mit
unseren Daten.

## 4. Rundung an der Schwelle von 25.000 USD

Die Datensätze runden Preise auf 2 Stellen, also um höchstens 0,005 USD je
Aktie. Bei so vielen Meldungen könnte die Rundung den Wert über oder unter
25.000 USD schieben (Obergrenze):

| Jahr | Signale | betroffen höchstens |
|---|---|---|
| 2008 | 10.226 | 135 (1,3 %) |
| 2015 | 6.507 | 73 (1,1 %) |

Das ist vernachlässigbar. Im Bericht reicht ein Satz.

## 5. Schritt 5 im Code

`src/finance_ai/evaluation/backtest.py` erzeugt aus den Quartalsdaten die
Signale mit Status (ok, kein Kurs, Kurs passt nicht, Börsenwert unbekannt),
Abschnitt (Stresstest oder Urteil), Fall ohne Kurs und damaligem Börsenwert.
Der Datencheck nutzt jetzt dieselbe Kurslogik und ergibt dieselben Zahlen wie
vorher.

Neu ist: **Auch Signale ohne Yahoo-Kurs bekommen einen Börsenwert**, aus
Aktienzahl mal gemeldetem Kaufpreis. Sonst gingen in die Stufe mit −55 % auch
Firmen über 2 Mrd. USD ein, die das Regelwerk nie kaufen würde. Der
Datencheck hat die Grenze bisher nicht beachtet.

2015 sind 359 Signale (5,5 %) „Börsenwert unbekannt“. Für 899 gab es vor dem
Meldetag keine Aktienzahl.
