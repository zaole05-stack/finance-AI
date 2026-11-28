# Betrieb eines Testlaufs

Der Testlauf läuft auf dem Laptop von A (BEREICH-A.md, Beschluss 5). Die
Windows-Aufgabenplanung ruft jede Stunde `lauf` auf. Verpasste Läufe holt
sie nach, sobald der Laptop wieder an ist.

## Einmalig

1. `.env` aus `.env.example` anlegen: `SEC_USER_AGENT` und `FINANCE_AI_BACKUP_DIR`.
   Das Backup-Ziel ist ein OneDrive-Ordner, die Datenbank selbst bleibt in `data/`.
2. Regeln im Dashboard prüfen. Mit dem Anlegen werden sie eingefroren, zusammen
   mit den Regeln im Code (`decision/regelwerk.py`).
3. Testlauf anlegen:

   ```
   python -m finance_ai.betrieb testlauf-anlegen --id insider-91d --name "Insider, 91 Tage" --owner zaole05-stack
   ```

## Aufgabenplanung

In PowerShell, im Projektordner:

```powershell
$repo = (Get-Location).Path
$action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\python.exe" -Argument "-m finance_ai.betrieb lauf --testlauf insider-91d" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "finance-ai Testlauf" -Action $action -Trigger $trigger -Settings $settings
```

- `-StartWhenAvailable` holt einen verpassten Start nach.
- `-MultipleInstances IgnoreNew` verhindert zwei Läufe gleichzeitig.
- Die Aufgabe läuft nur, wenn A angemeldet ist. Läufe ohne Anmeldung brauchen
  ein gespeichertes Passwort in der Aufgabenplanung. Das richtet A selbst ein.

## Was ein Lauf tut

1. Tägliches Backup, falls fällig.
2. Scan der Form-4-Meldungen seit dem letzten gelungenen Scan. Für Lücken über
   einen Tag kommen die Tagesindizes der SEC dazu.
3. Stundenkurse der letzten 7 Tage für offene Signale, Bestände und den ETF.
4. Entscheidung mit den eingefrorenen Regeln, zum Zeitpunkt „jetzt“.
5. Eine Zeile im Protokoll, auch bei Fehlern. Exit-Code 1 bei Fehler.

Scheitert der Kursabruf, wird nicht entschieden. Sonst würden Signale wegen
eines Netzfehlers dauerhaft abgelehnt. Weichen die Regeln im Code vom Stand
beim Anlegen ab, verweigert die Entscheidung. Dann braucht es einen neuen
Testlauf oder die Änderung wird zurückgenommen.

## Kontrolle

```
python -m finance_ai.betrieb protokoll --testlauf insider-91d
```

## Bekannte Lücken

- Routine-Ausschluss wirkt noch nicht: `insider.py` setzt keine Tags, und
  `insider_trades` wird nicht befüllt (Owner-CIK fehlt in `data/form4.py`, B).
- Der Börsenwert kommt live aktuell von Yahoo, im Backtest aus SEC-Aktienzahl
  mal Kurs. Das ist nicht dieselbe Regel.
- Das Ende des Testlaufs setzt niemand automatisch.
