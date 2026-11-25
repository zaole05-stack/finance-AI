"""Einstellungen aus Umgebungsvariablen oder einer lokalen `.env`-Datei.

Die `.env` liegt im Projektordner und ist von Git ausgeschlossen. Vorlage:
`.env.example`.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class MissingSetting(RuntimeError):
    pass


def sec_user_agent() -> str:
    """User-Agent für SEC EDGAR. Die SEC verlangt Name und Kontakt, z. B. 'Max Muster max@example.org'."""
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if not value or "@" not in value:
        raise MissingSetting(
            "SEC_USER_AGENT fehlt oder enthält keine E-Mail-Adresse. "
            "In .env eintragen, z. B.: SEC_USER_AGENT=\"Vorname Nachname name@example.org\""
        )
    return value
