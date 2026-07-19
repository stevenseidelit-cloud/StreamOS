# Recovery-Nachweis für den GitHub-Auszug

## Durchgeführte Schritte

1. SHA-256 des ursprünglichen Installers bestätigt.
2. Installer isoliert extrahiert, ohne ihn zu installieren oder auszuführen.
3. PyInstaller-Struktur und Python-Version 3.13 identifiziert.
4. Acht anwendungsspezifische Python-Module ermittelt.
5. Exakte HTML-, JavaScript- und CSS-Dateien gesichert.
6. Lesbare Bytecode-Disassemblies der Projektmodule erzeugt.
7. Den öffentlichen Beispielumfang auf Text- und UI-Dateien reduziert.
8. Upload-Kandidat auf Geheimnisse, private Pfade und Binärdateien geprüft.

## Inhalt dieses Auszugs

- drei originale UI-Dateien
- acht Bytecode-Disassemblies
- drei Dokumentationsdateien

Nicht enthalten sind Installer, Programme, Python-Bytecode, Fremdbibliotheken,
Analysewerkzeuge, Datenbanken, Logs, Backups und Zugangsdaten.

## Rückgängig

Da dieser Stand über einen getrennten Branch und Pull Request bereitgestellt
wird, kann er durch Schließen des Pull Requests oder Zurücksetzen des zugehörigen
Commits vollständig entfernt werden.
