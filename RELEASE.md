# StreamOS Releases

## Automatischer Release-Build

Ein Git-Tag im Format `vX.Y.Z` startet den Windows-Release-Workflow. Installer und
portable Version werden aus demselben PyInstaller-Ordner `dist\StreamOS` erzeugt.
Dadurch enthalten beide Varianten dieselben UI-Dateien, Python-Abhängigkeiten und
den zu Playwright gehörenden Firefox-Browser.

Ein Release enthält diese vier Dateien:

- `StreamOS_X.Y.Z_Setup.exe`
- `StreamOS_X.Y.Z_Setup.exe.sha256`
- `StreamOS_X.Y.Z_Portable.zip`
- `StreamOS_X.Y.Z_Portable.zip.sha256`

Die ZIP enthält als obersten Ordner `StreamOS_X.Y.Z_Portable`. Direkt darin liegt
`StreamOS.exe`.

## Portable Version testen

1. Die installierte oder eine andere portable StreamOS-Version vollständig schließen.
2. `StreamOS_X.Y.Z_Portable.zip` vollständig entpacken.
3. Nicht direkt aus der ZIP starten.
4. `StreamOS_X.Y.Z_Portable\StreamOS.exe` aus dem entpackten Ordner starten.
5. Nach dem Test StreamOS normal schließen.

Die portable Version ist nur für manuelle Tests vorgesehen. Sie wird vom Updater
weder automatisch entpackt noch gestartet oder installiert. Nach dem verifizierten
Download zeigt StreamOS den lokalen Speicherort an und kann den zugehörigen Ordner
auf ausdrücklichen Klick öffnen.

Benutzerdaten werden nicht im Portable-Ordner abgelegt. Einstellungen, Datenbank,
Token, Backups und Logs bleiben unter `%APPDATA%\StreamOS`.

## Setup-Version verwenden

`StreamOS_X.Y.Z_Setup.exe` ist die empfohlene Variante für den normalen dauerhaften
Einsatz. Der Updater lädt Installer und Prüfsumme herunter, verifiziert SHA-256 und
startet den Installer erst nach einer ausdrücklichen Bestätigung sichtbar.

## Gleichzeitige Instanzen

StreamOS verwendet den lokalen Port `8080`. Ist dieser Port bereits durch StreamOS
oder eine andere Anwendung belegt, wird keine zweite StreamOS-Oberfläche geöffnet.
Stattdessen erscheint eine verständliche Fehlermeldung. Vor Portable-Tests muss die
installierte Version deshalb geschlossen werden.
