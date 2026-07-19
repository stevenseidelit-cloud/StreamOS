# Zusammenarbeit mehrerer KI-Agenten

GitHub ist die gemeinsame Schnittstelle zwischen den Agenten. Ein Issue
beschreibt die Aufgabe, eine Task-Datei reserviert exklusive Dateibereiche, ein
Branch isoliert die Arbeit und ein Pull Request übergibt das Ergebnis.

## Agenten

Jede Installation verwendet einen dauerhaft eindeutigen Namen, zum Beispiel:

- `chatgpt-pc1`
- `chatgpt-pc2`
- `gemini-pc2`

## Ablauf

1. GitHub-Issue mit Ziel und Abnahmekriterien anlegen.
2. `.coordination/templates/task.json` nach
   `.coordination/tasks/<task-id>.json` kopieren.
3. Agent, Branch, Issue und exklusive Pfadpräfixe eintragen.
4. Status auf `in_progress` setzen und diese Reservierung zuerst mergen.
5. In einem eigenen Branch ausschließlich innerhalb der reservierten Pfade
   arbeiten.
6. Frühzeitig einen Draft-Pull-Request öffnen.
7. Bei Übergabe Status auf `review` setzen und Tests sowie offene Fragen im PR
   dokumentieren.
8. Der andere Agent prüft den PR.
9. Nach dem Merge die Task in einem kleinen Folge-PR auf `done` setzen. Dadurch
   werden die Pfade wieder freigegeben.

## Status und Sperren

- `queued`: geplant, reserviert noch keine Pfade
- `in_progress`: arbeitet und reserviert Pfade
- `blocked`: pausiert, behält die Reservierung
- `review`: wartet auf Prüfung und behält die Reservierung
- `done`: abgeschlossen, gibt Pfade frei
- `cancelled`: abgebrochen, gibt Pfade frei

Ein Pfad ist ein Repository-relativer Präfix ohne Globzeichen, zum Beispiel
`src/auth.py` oder `ui`. `ui` kollidiert absichtlich mit `ui/app.js`.

## Konfliktregeln

- Nie direkt auf `main` arbeiten.
- Nie den Branch eines anderen Agenten verändern oder force-pushen.
- Ein aktiver Pfadpräfix darf nur einer aktiven Task gehören.
- Gemeinsame Kerndateien erhalten eine eigene Integrationsaufgabe.
- Recovery-Dateien sind grundsätzlich nur lesbar, sofern eine Aufgabe nicht
  ausdrücklich etwas anderes festlegt.
- Keine Tokens, Passwörter, Datenbanken, Logs, EXE-Dateien oder privaten Pfade
  committen.
- Vor einem Merge muss der Branch auf dem aktuellen `main` basieren und der
  Check `coordination` erfolgreich sein.
- Der Validator prüft bei Pull Requests zusätzlich, dass jede geänderte Datei
  innerhalb der `exclusive_paths` der zum Branch gehörenden aktiven Task liegt.
- Ein Branch darf nur seine eigene Task-Datei verändern. Fremde Reservierungen
  dürfen weder gelöscht noch auf `done` oder `cancelled` gesetzt werden.
- Eine neue Reservierung muss in einem eigenen kleinen Pull Request gemergt
  werden, bevor derselbe Branch Implementierungsdateien ändern darf.
- `task_id`, Agent, Branch und `exclusive_paths` sind nach dem Merge der
  Reservierung unveränderlich. Eine Erweiterung benötigt eine neue Task.

## Wichtige technische Grenze

Der Validator schützt Pull Requests vor bekannten Überschneidungen. Zwei
gleichzeitig geprüfte Pull Requests können jedoch beide einen veralteten
`main`-Stand sehen. Deshalb muss GitHub für `main` zusätzlich Pull Requests,
aktuelle Branches und idealerweise die Merge Queue erzwingen.

Die geschützten Koordinationsdateien sind in `.github/CODEOWNERS` dem
Repository-Eigentümer zugeordnet. Diese Regel wirkt erst zuverlässig, wenn der
Branch-Schutz eine Code-Owner-Freigabe verlangt.
