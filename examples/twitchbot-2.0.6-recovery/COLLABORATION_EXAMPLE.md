# Beispiel: Zusammenarbeit von Codex und Gemini über GitHub

Status: Beispiel, noch nicht auf GitHub veröffentlicht

## Ziel

Codex und Gemini arbeiten nachvollziehbar am selben Projekt, ohne gleichzeitig
dieselben Dateien zu verändern. GitHub dient als gemeinsame Übergabestelle.

## Rollen

- Codex: technische Planung, Integration, Tests und abschließende Prüfung
- Gemini: unabhängige Analyse, alternative Lösungsansätze und Review
- Projektinhaber: entscheidet bei Zielkonflikten und gibt riskante Änderungen frei

## Arbeitsregeln

1. Jede Aufgabe beginnt als GitHub-Issue.
2. Im Issue stehen Ziel, erlaubte Dateien, verbotene Dateien und Akzeptanztests.
3. Codex und Gemini verwenden getrennte Branches.
4. Pro Datei arbeitet immer nur ein Agent zur selben Zeit.
5. Änderungen kommen ausschließlich über Pull Requests zurück.
6. Der andere Agent prüft den Pull Request, bevor er zusammengeführt wird.
7. Zugangsdaten, Tokens, Datenbanken, Logs und private Nutzerdaten werden niemals
   committed.
8. Ein Merge erfolgt erst, wenn die vereinbarten Tests erfolgreich sind.

## Beispielauftrag

- Issue: `EXAMPLE-001`
- Ziel: Eine harmlose Beispieldatei ergänzen und ihre Ausgabe testen.
- Codex-Dateien: `example/codex_result.txt`
- Gemini-Dateien: `example/gemini_review.md`
- Gemeinsame Dateien: keine
- Verboten: Programmcode, Zugangsdaten, reale Konfigurationen und Binärdateien

## Übergabeformat

Jeder Agent hinterlässt im Pull Request:

- Bearbeiter: `Codex` oder `Gemini`
- Ausgangspunkt: Commit-ID
- Geänderte Dateien: vollständige Liste
- Ausgeführte Tests: Befehl und Ergebnis
- Offene Risiken: kurze Liste oder `keine`
- Rückgängig: Commit zurücksetzen oder Pull Request schließen

## Sicherheitsgrenze

Dieses Beispiel autorisiert keinen automatischen Merge und keinen Zugriff auf
den Raspberry Pi. Änderungen an produktiven Systemen benötigen weiterhin eine
gesonderte Freigabe durch den Projektinhaber.
