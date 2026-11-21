# Unique Health Scale (Lefu) für Home Assistant

Lokale Home-Assistant-Integration für 8-Elektroden-Körperfettwaagen, die mit der App **Unique Health** (Shenzhen Lefu Scale Co.) arbeiten, z. B. die **PAVABA 8-Elektroden-Waage mit Griff**. Ziel: alle Messwerte direkt per Bluetooth in HA, ohne Cloud und ohne App-Zwang.

> **Status: v0.1 – Aufzeichnungsphase.** Die Integration findet die Waage per Bluetooth (automatisch über Lefu-Kennung `0x1A10` bzw. Dienst `FFF0`, sonst manuell aus der Geräteliste) und zeichnet die rohen Funk-Frames auf. Das Dekodieren von Gewicht, Impedanzen und Körperwerten folgt, sobald das Protokoll entschlüsselt ist (siehe [docs/protocol.md](docs/protocol.md)).

## Voraussetzungen

- Home Assistant mit Bluetooth in Reichweite der Waage (eingebauter Adapter oder ESPHome-Bluetooth-Proxy)
- Die Waage sollte während der Tests nicht gleichzeitig mit der Unique-Health-App verbunden sein

## Installation (HACS, benutzerdefiniertes Repository)

1. HACS → Integrationen → ⋮ → *Benutzerdefinierte Repositories* → dieses Repo als *Integration* hinzufügen
2. „Unique Health Scale (Lefu)“ installieren, HA neu starten
3. Auf die Waage stellen – HA sollte sie unter *Einstellungen → Geräte & Dienste* als entdeckt anzeigen. Falls nicht: *Integration hinzufügen → Unique Health Scale* und die Waage aus der Liste wählen (stärkstes Signal steht oben)

Alternativ `custom_components/unique_health_scale` manuell nach `/config/custom_components/` kopieren.

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| `sensor.<waage>_gewicht` | Gewicht der letzten stabilen Messung (aktiv, sobald der Decoder fertig ist) |
| `sensor.<waage>_rohdaten` | Letzter Roh-Frame (Hex) plus Bluetooth-Name und die letzten 25 Frames als Attribute – für die Protokollanalyse |

Für ausführliches Logging:

```yaml
logger:
  logs:
    custom_components.unique_health_scale: debug
```

## Roadmap

- [x] Erkennung der Waage, Aufzeichnung der Roh-Frames
- [ ] Protokoll entschlüsseln (Mitschnitte + REA-Analyse von `PPBluetoothKit`)
- [ ] Gewicht und Impedanzen dekodieren
- [ ] Körperwerte (von der Waage gelieferte bzw. nachgerechnete Werte), Segmentwerte für Arme, Beine, Rumpf
- [ ] Mehrere Personen / Profile
- [ ] Optional: Abruf aus der Lefu-Cloud als Fallback

## Hinweis

Inoffizielles Projekt, nicht mit Lefu, PAVABA oder Unique Health verbunden. Die Protokollanalyse dient ausschließlich der Interoperabilität mit eigener Hardware.
