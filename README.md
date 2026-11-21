# Unique Health Scale (Lefu) für Home Assistant

Lokale Home-Assistant-Integration für 8-Elektroden-Körperfettwaagen, die mit der App **Unique Health** (Shenzhen Lefu Scale Co.) arbeiten, z. B. die **PAVABA 8-Elektroden-Waage mit Griff** (Bluetooth-Name `smart scale P1`). Ziel: alle Messwerte direkt per Bluetooth in HA, ohne Cloud und ohne App-Zwang.

> **Status: v0.2 – Gewicht, Herzfrequenz und Roh-Impedanzen funktionieren, Körperwerte in Arbeit.**
> Das Gewicht wird aus den Funkdaten der Waage gelesen. Für die Körperanalyse verbindet sich die Integration während der Messung mit der Waage und liest die zehn Segment-Impedanzen und die Herzfrequenz mit (an echter Hardware bestätigt). Die Umrechnung der Impedanzen in Körperfett, Muskelmasse usw. fehlt noch. Details: [docs/protocol.md](docs/protocol.md).

## Voraussetzungen

- Home Assistant 2024.8 oder neuer mit Bluetooth in Reichweite der Waage (eingebauter Adapter oder ESPHome-Bluetooth-Proxy mit aktiven Verbindungen)
- Die Unique-Health-App sollte während der Messung geschlossen sein: Die Waage lässt nur eine Verbindung zu.

## Installation (HACS, benutzerdefiniertes Repository)

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/schaepi85/ha-unique-health-scale` als *Integration* hinzufügen
2. „Unique Health Scale (Lefu)“ installieren, HA neu starten
3. Auf die Waage stellen – HA zeigt sie unter *Einstellungen → Geräte & Dienste* als entdeckt an. Falls nicht: *Integration hinzufügen → Unique Health Scale* und die Waage aus der Liste wählen.

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| Gewicht | Gewicht in kg, sobald es auf der Waage feststeht |
| Herzfrequenz | Herzfrequenz am Ende der Messung |
| Impedanzen (kodiert) | Diagnose: die zehn Segment-Impedanzen (Arme, Beine, Rumpf bei 20 und 100 kHz) als Attribute, noch unentschlüsselt |
| Rohdaten | Diagnose: letzte Funk- und Verbindungsdaten, Sitzungsstatus und Verlauf – für die Protokollanalyse |

Ausführliches Logging:

```yaml
logger:
  logs:
    custom_components.unique_health_scale: debug
```

## Entwicklung

```bash
pip install pytest-homeassistant-custom-component aiousbwatcher pyserial
pytest
```

Die Tests simulieren die Waage (Advertising und FFF4-Notifications) gegen ein echtes Home Assistant.

## Roadmap

- [x] Waage erkennen, Rohdaten aufzeichnen
- [x] Gewicht dekodieren
- [x] Impedanzen an echter Hardware mitlesen
- [x] Herzfrequenz mitlesen
- [ ] Körperwerte berechnen (Körperfett, Muskelmasse, Wasser, Segmentwerte …)
- [ ] Mehrere Personen / Profile

## Hinweis

Inoffizielles Projekt, nicht mit Lefu, PAVABA oder Unique Health verbunden. Die Protokollanalyse dient ausschließlich der Interoperabilität mit eigener Hardware.
