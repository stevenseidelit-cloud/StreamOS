# StreamOS-Schichten

Die neue Struktur wird schrittweise neben den bestehenden flachen Modulen
aufgebaut. Bestehende Laufzeitimporte werden dadurch zunächst nicht verändert.

| Schicht | Paket | Verantwortung |
|---|---|---|
| A | `desktop` | Fenster, Dateidialoge, Lifecycle und Composition Root |
| B | `ui` | UI-API, DTOs sowie Lade-, Leer-, Fehler- und Erfolgszustände |
| C | `application` | Anwendungsfälle, Orchestrierung und Ports |
| D | `domain` | Reine Fachmodelle und Zustandsübergänge ohne I/O |
| E | `adapters` | Twitch, SQLite, Token, GitHub, Autostart, Zeit und IDs |

## Abhängigkeitsregel

- `domain` kennt keine andere Schicht.
- `application` verwendet `domain` und definiert Ports.
- `adapters` implementiert Ports aus `application` und darf Domain-Typen
  verwenden.
- `ui` spricht ausschließlich mit `application`.
- `desktop` verdrahtet `ui`, `application` und `adapters`.

Insbesondere importiert `domain` weder Playwright, aiohttp, SQLite, GitHub noch
pywebview.

Die Domain-State-Machine und ihre Tests werden aus der separat von PC2
gelieferten, unabhängig geprüften Übergabe integriert.
