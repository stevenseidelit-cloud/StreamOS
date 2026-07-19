# TwitchBot 2.0.6 – bereinigtes Recovery-Beispiel

## Zweck

Dieser Ordner ist ein kleiner, öffentlich geeigneter Referenzstand für den
Neuaufbau von StreamOS. Er wurde aus dem Installer
`TwitchBot2.0.6_Setup.exe` gewonnen.

SHA-256 des untersuchten Installers:

`70E35BDFDD7D20A85A5BE77142516BE26D19E85A7A478EDCB72674D69DA5D783`

Der Installer selbst, Fremdbibliotheken, Analysewerkzeuge und weitere
Binärdateien sind bewusst nicht Bestandteil dieses Beispiels.

## Enthaltener Umfang

- `ui_original/`
  - die exakt extrahierten Dateien `app.js`, `index.html` und `style.css`
- `bytecode_disassembly/`
  - lesbare Disassemblies der acht identifizierten Projektmodule
- `COLLABORATION_EXAMPLE.md`
  - Beispielablauf für die Zusammenarbeit von Codex und Gemini über GitHub
- `CHANGELOG_RECOVERY.md`
  - Herkunft, Prüfungen und Grenzen dieses Auszugs

Identifizierte Projektmodule:

- `main`
- `src.auth`
- `src.bot_engine`
- `src.db`
- `src.logger`
- `src.paths`
- `src.server`
- `src.__init__`

## Grenzen

Die Anwendung wurde mit Python 3.13 gebaut. Eine zuverlässige automatische
Rückübersetzung in fertige `.py`-Dateien war mit dem getesteten Decompiler nicht
möglich. Die Disassemblies enthalten jedoch Konstanten, Funktionsnamen,
Kontrollfluss und Bytecode-Anweisungen und können als überprüfbare Grundlage für
eine saubere Neuentwicklung dienen.

Dieser Ordner ist kein ursprünglicher und kein direkt lauffähiger Quellstand.
Kommentare, Formatierung und Teile der ursprünglichen Struktur lassen sich aus
kompiliertem Python-Bytecode nicht sicher zurückgewinnen.

## Bekannte Sicherheitslücke des historischen Stands

Die Disassembly zeigt, dass Twitch-Tokens in dieser historischen Version
unverschlüsselt gespeichert wurden. Dieses Verhalten darf nicht in einen
Neuaufbau übernommen werden. Zugangsdaten müssen künftig über einen geeigneten
Secret-Store geschützt werden.

## Sicherheitsumfang

Dieser GitHub-Auszug enthält keine Installer, EXE-, DLL- oder PYC-Dateien,
Datenbanken, Logs, Tokens, Passwörter, Backups oder vollständigen
Fremdbibliotheken.
