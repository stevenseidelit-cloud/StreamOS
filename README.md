# StreamOS 0.0.1

## Zweck dieses Neustarts

Dieses Repository ist der saubere Neustart des Projekts StreamOS. Die technische Grundlage stammt aus der zuvor lokal geführten Version 0.0.6. Sie wird hier bewusst als **StreamOS 0.0.1** neu begonnen, damit die weitere Entwicklung nachvollziehbar und Schritt für Schritt erfolgen kann.

Die vorhandene Anwendung läuft grundsätzlich, ist aber noch nicht zuverlässig und nicht vollständig. Sie dient als Ausgangsbasis und wird nicht als fertige Version betrachtet.

## Projektziel

StreamOS soll ein modernes Windows-Desktopprogramm für Twitch-Nutzer werden. Es soll gefolgte Kanäle verwalten, Streamstatus überwachen, Zuschauer-Serien und Kanalpunkte erfassen, Aktivitäten protokollieren und Statistiken übersichtlich darstellen.

## Verbindliches Design

- Dunkles Windows-Desktop-UI
- Inspiration: Discord, Steam, Visual Studio Code und Battle.net
- Orange `#FF6A1A` als Akzentfarbe
- Keine Apple-Optik und keine Apple-Symbole
- Keine typische Bootstrap-Webseitenoptik
- Linke Sidebar
- Fest angeheftete Statusleiste am unteren Fensterrand
- Scrollbare Seiteninhalte ohne Seitennummerierung
- Kompakte, einheitliche Karten, Tabellen und Schaltflächen

## Geplante Navigation

1. Dashboard
2. Kanäle
3. Logs
4. Statistiken
5. Aktivitäten
6. Einstellungen
7. Rückmeldung
8. Über

## Vorhandene technische Grundlage

- Python-Backend
- lokales Desktopfenster mit PyWebView
- aiohttp-API auf `localhost:8080`
- HTML-, CSS- und JavaScript-Oberfläche
- SQLite-Datenbank
- Playwright mit Firefox
- verschlüsselte Speicherung des Twitch-Tokens mit Fernet
- Synchronisierung gefolgter Twitch-Kanäle
- Live-Erkennung und Serienüberwachung
- mehrere parallele Worker
- automatische Bonustruhe
- Einstellungen, Backups und Live-Logs
- PyInstaller- und Inno-Setup-Konfiguration
- GitHub-Updater für Installer und portable Testversionen

## Release-Artefakte

Jedes mit `vX.Y.Z` getaggte GitHub-Release erzeugt zwei Windows-Versionen:

- `StreamOS_X.Y.Z_Setup.exe` für den normalen dauerhaften Einsatz
- `StreamOS_X.Y.Z_Portable.zip` zum manuellen Testen ohne Installation

Zu beiden Dateien wird eine eigene `.sha256`-Datei veröffentlicht. StreamOS prüft
Downloads anhand dieser SHA-256-Prüfsumme, bevor sie verwendet werden können.

Die Portable-ZIP muss vor dem Start vollständig entpackt werden. Vor einem Test ist
eine bereits installierte StreamOS-Version zu schließen, damit nicht zwei Instanzen
gleichzeitig Port `8080` verwenden. Anschließend wird `StreamOS.exe` direkt aus dem
entpackten Ordner gestartet. Die portable Version schreibt Einstellungen, Datenbank,
Tokens und Logs weiterhin nach `%APPDATA%\StreamOS` und nicht in ihren Programmordner.

Die Setup-Version bleibt der empfohlene Weg für den normalen dauerhaften Einsatz.
Weitere Details stehen in [RELEASE.md](RELEASE.md).

## Aktueller automatischer Ablauf

1. Datenbank und Einstellungen laden
2. Twitch-Token laden
3. Firefox über Playwright starten
4. gefolgte Kanäle erfassen
5. unbekannte Serien synchronisieren
6. Live-Kanäle regelmäßig erkennen
7. freie Worker auf live und bereite Kanäle verteilen
8. Serie prüfen und Bonustruhe einsammeln
9. Ergebnis speichern
10. Wartezeit einhalten und Ablauf wiederholen

## Bekannte Probleme der Ausgangsbasis

- Noch keine eigene Kanalseite
- Kanäle können nicht manuell hinzugefügt oder gelöscht werden
- Kanalpunkte werden noch nicht gespeichert
- Statistikseite ist nur ein Platzhalter
- Aktivitäten und Rückmeldung fehlen
- BetterTTV ist noch nicht implementiert
- Einige vorhandene Einstellungen werden vom Backend nicht verwendet
- `last_update` wird nicht zuverlässig aktualisiert
- Offline-Reset arbeitet noch nicht korrekt nach der eingestellten Zeit
- Token wird gespeichert, aber nicht vollständig auf Twitch-Gültigkeit geprüft
- Sync kann im falschen Programmzustand fehlschlagen
- Mehrere Fehler werden durch leere `except`-Blöcke verschluckt
- Pluginsystem fehlt
- Oberfläche entspricht noch nicht dem neuen StreamOS-Design
- Externe Lucide-Symbole benötigen derzeit eine Internetverbindung

## Regeln für die weitere Entwicklung

- Funktionen werden einzeln und nachvollziehbar bearbeitet.
- Bestehende funktionierende Logik wird nicht unnötig entfernt.
- Frontend und Backend bleiben klar getrennt.
- Änderungen müssen vollständige, verwendbare Dateien ergeben.
- Jede Änderung wird geprüft, bevor die nächste Funktion begonnen wird.
- Versionsnummern werden im gesamten Projekt einheitlich geführt.
- Keine Zugangsdaten, Tokens, Datenbanken oder persönlichen Logs werden in Git gespeichert.
- Der Branch `main` enthält nur einen nachvollziehbaren, grundsätzlich startbaren Stand.

## Versionsstart

`0.0.1` – Sauberer Neustart auf Grundlage der bisherigen lokalen Version 0.0.6.
