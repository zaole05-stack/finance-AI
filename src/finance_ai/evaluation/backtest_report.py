"""Bericht `docs/BACKTEST.md` aus den gespeicherten Läufen (Plan-Schritt 8).

Rechnet nichts selbst: Alles kommt aus `data/backtest.sqlite`. Maßgeblich ist
der letzte Lauf, alle Läufe stehen am Ende.
"""

from __future__ import annotations

from collections.abc import Sequence

from finance_ai.evaluation.backtest_runs import YAHOO_NOTE, RunEntry

START_HINT = (
    "Noch kein Lauf. Start, sobald das Regelwerk eingefroren ist:\n\n"
    "```\npython -m finance_ai.evaluation.backtest run --fenster-regel <vor-etf|5pp>\n```\n"
)
GAPS = [
    "**Yahoo:** Für delistete Firmen fehlen meist Kurse, Kürzel werden "
    "wiederverwendet. Die Fälle ohne Kurs gehen mit festen Werten in drei Stufen ein. "
    "Ohne CRSP bleibt das eine Annahme (siehe Datencheck-Befunde).",
    "**10b5-1:** Das Kennzeichen für Käufe nach festem Plan gibt es in den "
    "SEC-Datensätzen erst ab 2023. Davor sind solche Käufe nicht ausgeschlossen.",
    "**SIC:** Der Branchencode ist der heutige, nicht der damalige. Das ist ein "
    "kleiner Blick in die Zukunft beim Ausschluss von Fonds, REITs und SPACs.",
]
DEC = "Urteil"
HALVES = ("Urteil 2011–2018", "Urteil 2019–2026")
STRESS = "Stresstest Finanzkrise"
DECIDING = "vorsichtig-realistisch"
WORST = "schlimmster Fall"


def _pp(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:+.1f} Pp".replace(".", ",")


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f} %"


def _ci(ci) -> str:
    return "–" if ci is None else f"{_pp(ci[0])} bis {_pp(ci[1])}"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines + [""]


def _part_rows(parts: dict, names: Sequence[str]) -> list[list[str]]:
    rows = []
    for name in names:
        p = parts.get(name)
        if p is None:
            continue
        s, w = p["Einzelsignale"], p["Fenster"]
        has_s, has_w = s["Anzahl"] > 0, w["Anzahl"] > 0
        rows.append([
            name, s["Anzahl"], s.get("davon fester Wert", 0), s.get("weggefallen", 0),
            _pp(s["Mittel"] if has_s else None), _ci(s["KI 95 %"]),
            w["Anzahl"], _pp(w["Mittel"] if has_w else None),
            _pct(w["Anteil vor ETF"] if has_w else None), _pct(w["Anteil ≥ 5 Pp"] if has_w else None),
        ])
    return rows


PART_HEADER = ["Teil", "Signale", "fester Wert", "weggefallen", "Vorsprung je Signal",
               "95-%-Intervall", "Fenster", "Vorsprung je Fenster", "Fenster vor ETF",
               "Fenster ≥ 5 Pp"]


def _coverage_rows(groups: dict) -> list[list[str]]:
    return [[name, g["messbar"], g["ohne Kurs"], _pct(g["Anteil messbar"])] for name, g in groups.items()]


def criteria(d: dict, r: dict) -> list[str]:
    """Die beiden Prüfwerte des Urteils als Sätze, für Bericht und Dashboard."""
    dec = d["Stufen"][DECIDING][DEC]
    share_key = "Anteil ≥ 5 Pp" if r.get("Fenster_Regel") == "5pp" else "Anteil vor ETF"
    w, s = dec["Fenster"], dec["Einzelsignale"]
    return [
        f"Vorsprung je 6-Monats-Fenster im Mittel {_pp(w['Mittel'])} "
        f"(nötig: mindestens +5,0 Pp), {share_key.replace('Anteil', 'Anteil der Fenster')} "
        f"{_pct(w[share_key])} (nötig: mindestens 60 %), aus {w['Anzahl']} Fenstern.",
        f"Vorsprung je Einzelsignal im Mittel {_pp(s['Mittel'])}, "
        f"95-%-Intervall {_ci(s['KI 95 %'])} (nötig: untere Grenze über null), "
        f"aus {s['Anzahl']} Signalen. Block-Bootstrap nach Kalendermonat.",
    ]


def markdown(entries: Sequence[RunEntry]) -> str:
    lines = ["# Backtest des Insider-Experten", ""]
    if not entries:
        return "\n".join(lines + [START_HINT])
    last = entries[-1]
    d, r = last.result, last.regelwerk
    per_tier = d.get("Urteil je Stufe", {})

    lines += [f"> **{YAHOO_NOTE}**", ""]
    if per_tier.get(WORST) and per_tier.get(WORST) != per_tier.get(DECIDING):
        lines += [
            f"> **Warnung:** Im schlimmsten Fall (alle Signale ohne Kurs −100 %) lautet das Urteil "
            f"„{per_tier[WORST]}“ statt „{per_tier[DECIDING]}“.", "",
        ]
    lines += [f"Stand: Lauf vom {last.at:%Y-%m-%d %H:%M} UTC · Regelwerk `{last.fingerprint[:12]}`", ""]

    cov = d["Abdeckung"]
    lines += ["## Messbare Signale", "",
              "Messbar heißt: Yahoo hat Kurse über die ganze Haltedauer, und sie passen zum "
              "gemeldeten Kaufpreis.", ""]
    lines += _table(["Abschnitt", "messbar", "ohne Kurs", "Anteil messbar"], _coverage_rows(cov["Abschnitte"]))
    lines += ["Zielsegment (Urteilsabschnitt, Börsenwert bis zur Grenze), nach Börsenwert:", ""]
    lines += _table(["Klasse", "messbar", "ohne Kurs", "Anteil messbar"],
                    _coverage_rows({**cov["Klassen"], "Zielsegment gesamt": cov["Zielsegment"]}))

    lines += ["## Messbar und weggefallen", "",
              "Was später mit den Firmen geschah, laut SEC-Meldungen nach dem Meldetag. "
              "Renditen der weggefallenen Signale gibt es nicht.", ""]
    lines += _table(["Gruppe", "Signale", "später Insolvenz", "später Übernahme"], [
        [name, g["Anzahl"], _pct(g["später Insolvenz"]), _pct(g["später Übernahme"])]
        for name, g in cov["Vergleich"].items()
    ])

    lines += ["## Regelwerk", "", f"Fingerabdruck: `{last.fingerprint}`", ""]
    lines += _table(["Regel", "Wert"], [[k, f"`{v}`"] for k, v in r.items()])

    lines += [
        "## Urteil", "",
        f"**{last.verdict.value}** (mittlere Stufe, Urteilsabschnitt, ETF {r['ETF']})", "",
        *[f"{i}. {c}" for i, c in enumerate(criteria(d, r), 1)], "",
    ]
    lines += ["## Drei Stufen", "",
              "Signale ohne Kurs: optimistisch fallen sie weg, vorsichtig-realistisch (entscheidet) "
              "Übernahme 0 %, Pleite und Unbekanntes −55 %, im schlimmsten Fall alle −100 %.", ""]
    rows = []
    for tier, parts in d["Stufen"].items():
        rows += [[tier, per_tier.get(tier, "–"), *row[1:]] for row in _part_rows(parts, [DEC])]
    lines += _table(["Stufe", "Urteil", *PART_HEADER[1:]], rows)

    lines += ["## Stresstest Finanzkrise", "",
              "1.1.2006 bis 30.6.2011, **ohne Börsenwert-Grenze**, zählt nicht fürs Urteil. Er misst "
              "Insider-Käufe allgemein in der Krise, nicht genau die Small-Cap-Strategie.", ""]
    lines += _table(PART_HEADER, _part_rows(d["Stufen"][DECIDING], [STRESS]))

    lines += ["## Hälften des Urteilsabschnitts", "",
              "Nur zur Beschreibung: Hält das Ergebnis in beiden Phasen? Fenster über den "
              "Jahreswechsel 2018/2019 fallen aus beiden Hälften.", ""]
    lines += _table(PART_HEADER, _part_rows(d["Stufen"][DECIDING], [DEC, *HALVES]))

    lines += ["## Doppelte Slippage", "",
              "Mittlere Stufe, Urteilsabschnitt. Fließt nicht ins Urteil, zeigt nur die "
              "Empfindlichkeit auf Kosten. Dazu der Zweit-ETF. Liegt das Depot teils in Bargeld, "
              "trifft höhere Slippage den voll investierten ETF stärker. Der Vorsprung je Fenster "
              "kann dann sogar steigen. Aussagekräftiger ist hier der Vorsprung je Signal.", ""]
    lines += _table(PART_HEADER, _part_rows(d["Zusatz"], list(d["Zusatz"])))

    lines += ["## Alle Läufe", ""]
    lines += _table(["Zeit (UTC)", "Urteil", "Regelwerk", "Begründung"], [
        [f"{e.at:%Y-%m-%d %H:%M}", e.verdict.value, f"`{e.fingerprint[:12]}`", e.reason or "Erstlauf"]
        for e in entries
    ])

    lines += ["## Bekannte Lücken", ""] + [f"- {g}" for g in GAPS] + [""]
    return "\n".join(lines)
