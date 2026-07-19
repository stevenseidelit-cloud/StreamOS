# Versionierung und reproduzierbare Builds

## Ziel

`version.json` im Repository-Root ist die zentrale, reviewbare Versionsquelle
für StreamOS. Die Datei beschreibt die Produktversion, aber keine einzelne
Build-Ausführung.

TwitchBot 2.0.6 bleibt eine historische Verhaltensreferenz. Diese Nummer ist
kein direkter Vorgänger der neu gestarteten StreamOS-Version 0.0.1.

## Format

Pflichtfelder:

- `schema_version`: Version des Dateiformats
- `product`: Produktname
- `version`: SemVer ohne führendes `v`
- `channel`: Release-Kanal

Erlaubte Kanäle:

- `development`
- `alpha`
- `beta`
- `rc`
- `stable`

`legacy_reference` ist ausschließlich dokumentarisch und beeinflusst weder
Update-Reihenfolge noch Release-Tags.

## SemVer

- `MAJOR`: inkompatible Änderungen
- `MINOR`: neue rückwärtskompatible Funktionen
- `PATCH`: rückwärtskompatible Fehlerkorrekturen

Bei `0.x` darf die öffentliche Schnittstelle noch instabil sein. Vorabversionen
verwenden beispielsweise `0.1.0-alpha.1`, `0.1.0-beta.1` oder `0.1.0-rc.1`.

Der Kanal muss zur Version passen:

- `stable`: keine Vorabversionskennung
- `alpha`: Kennung enthält `alpha`
- `beta`: Kennung enthält `beta`
- `rc`: Kennung enthält `rc`
- `development`: stabiler oder vorläufiger Arbeitsstand erlaubt

Build-Metadaten nach `+` dürfen nicht zur Update-Reihenfolge verwendet werden.

## Konsumenten

Der aktuelle Neustart enthält noch Versionsliterale in Python, UI, Installer und
README. Die CI vergleicht diese Übergangsstellen mit `version.json` und stoppt
bei Abweichungen.

In späteren Aufgaben werden die Konsumenten schrittweise umgestellt:

- Python: zentrale `get_version()`-/`get_build_info()`-API
- UI: lokaler `/api/version`-Endpunkt oder generierte Versionsdatei
- PyInstaller: `version.json` als Data-Datei und generierte Windows-Ressource
- Inno Setup: generierte `build/version.iss`
- README: keine manuell gepflegte Produktversionsquelle

Produktive Python-, UI- und Installerdateien werden in dieser
Infrastrukturaufgabe bewusst nicht verändert.

## Release-Ablauf

1. Version und Kanal in `version.json` ändern.
2. CI und Fachtests erfolgreich ausführen.
3. Arbeitsbaum muss sauber sein.
4. Annotierten Tag `v<version>` erstellen.
5. Tag und `version.json` müssen exakt übereinstimmen.
6. Build in sauberer Umgebung erzeugen.
7. Artefakt-Prüfsummen und Build-Provenienz veröffentlichen.
8. Release erst nach unabhängiger Prüfung freigeben.

## Build-Manifest

`build-manifest.json` wird zukünftig während des Builds erzeugt und nicht als
Versionsquelle committed. Vorgesehene Felder:

- StreamOS-Version und Kanal
- Git-Commit
- `SOURCE_DATE_EPOCH`
- sauberer oder veränderter Arbeitsbaum
- Python-, PyInstaller- und Inno-Setup-Version
- Zielplattform
- Hash der Abhängigkeits-Lockdatei
- SHA-256 aller erzeugten Artefakte

Version und Build-Identität bleiben dadurch getrennt.

## Reproduzierbarkeit

- Toolchain und Actions auf feste Versionen beziehungsweise Commit-SHAs pinnen.
- Abhängigkeiten exakt festlegen und später mit Hashes locken.
- Build-Zeit aus dem Commit ableiten.
- Releases nur aus Tags und sauberem Arbeitsbaum erzeugen.
- Einen zweiten Clean-Room-Build vergleichen.
- Bekannte nichtdeterministische PE-/Installer-Felder dokumentieren.

## Rückgängig

Eine Versionsänderung wird durch Rücksetzen des zugehörigen Commits
rückgängig gemacht. Bereits veröffentlichte Versionsnummern oder Tags werden
nicht wiederverwendet.
