# Unique Health Scale (Lefu) für Home Assistant

Lokale Home-Assistant-Integration für 8-Elektroden-Körperfettwaagen, die mit der App **Unique Health** (Shenzhen Lefu Scale Co.) arbeiten, z. B. die **PAVABA 8-Elektroden-Waage mit Griff** (Bluetooth-Name `smart scale P1`). Ziel: alle Messwerte direkt per Bluetooth in HA, ohne Cloud und ohne App-Zwang.

> **Status: v0.4 – Gewicht, Herzfrequenz, Segment-Impedanzen und alle Körperwerte (Körperfett, Muskelmasse, Wasser, Segmentwerte …) funktionieren.**
> Das Gewicht wird aus den Funkdaten der Waage gelesen. Für die Körperanalyse verbindet sich die Integration während der Messung mit der Waage und liest die zehn Segment-Impedanzen und die Herzfrequenz mit (an echter Hardware bestätigt). Aus Impedanzen, Gewicht und dem hinterlegten Profil berechnet die Integration die Körperwerte lokal. Details: [docs/protocol.md](docs/protocol.md) und [docs/body-composition.md](docs/body-composition.md).

## Voraussetzungen

- Home Assistant 2024.8 oder neuer mit Bluetooth in Reichweite der Waage (eingebauter Adapter oder ESPHome-Bluetooth-Proxy mit aktiven Verbindungen)
- Die Unique-Health-App sollte während der Messung geschlossen sein: Die Waage lässt nur eine Verbindung zu.

## Installation (HACS, benutzerdefiniertes Repository)

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/schaepi85/ha-unique-health-scale` als *Integration* hinzufügen
2. „Unique Health Scale (Lefu)“ installieren, HA neu starten
3. Auf die Waage stellen – HA zeigt sie unter *Einstellungen → Geräte & Dienste* als entdeckt an. Falls nicht: *Integration hinzufügen → Unique Health Scale* und die Waage aus der Liste wählen.
4. Profil angeben: Geschlecht, Größe und Geburtsdatum (oder Alter). Ohne Profil gibt es nur Gewicht, Herzfrequenz und Impedanzen. Später ändern: *Geräte & Dienste → Unique Health Scale → Konfigurieren*.

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| Gewicht | Gewicht in kg, sobald es auf der Waage feststeht |
| Herzfrequenz | Herzfrequenz am Ende der Messung |
| Körperfett, Fettmasse, fettfreie Masse | Anteil in % bzw. Masse in kg |
| Muskelmasse, Skelettmuskelmasse (+ Anteile) | in kg bzw. % |
| Körperwasser (Masse/Anteil), intra-/extrazelluläres Wasser | in kg bzw. % |
| Protein, Mineralien, Knochenmasse, Körperzellmasse | in kg bzw. % |
| Unterhautfett, Viszeralfett, Taille-Hüft-Verhältnis | kg / %, Stufe, Verhältnis |
| BMI, Grundumsatz, empfohlene Kalorienzufuhr, Skelettmuskelindex | |
| Körperpunktzahl, Körperalter, Körpertyp, Adipositasgrad | |
| Idealgewicht, Zielgewicht, Gewichts-/Fett-/Muskelkontrolle | Empfehlung: wie viel ab- bzw. aufbauen |
| Fettmasse / Muskelmasse je Segment | je fünf Sensoren (Arme, Rumpf, Beine) in kg |
| Impedanz … 20/100 kHz | Diagnose: zehn Sensoren mit den Segment-Impedanzen in Ohm (Arme, Beine, Rumpf bei 20 und 100 kHz) |
| Impedanzen | Diagnose: Übersicht der letzten Körperanalyse, alle Werte als Attribute |
| Rohdaten | Diagnose: letzte Funk- und Verbindungsdaten, Sitzungsstatus und Verlauf – für die Protokollanalyse |

Viele Körperwerte tragen als Attribute den Referenzbereich für Größe und Geschlecht (`normal_min`, `normal_max`) und die Einstufung (`rating`: `low` / `normal` / `high`); die Segmentwerte den Anteil am Normwert (`percent_of_reference`). Die Werte bleiben über Neustarts erhalten und werden mit jeder vollständigen Messung aktualisiert.

## Körperwerte

Die Waage misst nur Gewicht, Herzfrequenz und Impedanzen. Alles Weitere sind Schätzformeln über diese Messwerte, Größe, Alter und Geschlecht. Die Integration rechnet lokal mit einer eigenständig geschriebenen Nachbildung dieser Formeln ([bodycomp.py](custom_components/unique_health_scale/bodycomp.py)), die auf Übereinstimmung mit der Berechnung der App geprüft ist.

- **Inoffiziell:** kein Code und keine Dateien des Herstellers, nicht von Lefu, PAVABA oder Unique Health geprüft oder freigegeben.
- **Nur für die eigenen Messdaten** und die eigene Waage gedacht (Interoperabilität mit eigener Hardware).
- **Keine Medizin:** Bioimpedanz-Werte sind grobe Schätzungen; für Verläufe brauchbar, für Diagnosen nicht.
- Kalibriert ist die Berechnung für die `smart scale P1` (Lefu CF597). Andere Lefu-Modelle senden zwar ähnlich, verwenden aber andere Kalibrierfaktoren.
- Sollte der Hersteller Einwände gegen diesen Teil haben, wird er auf Wunsch entfernt – bitte per Issue melden.

Ausführliches Logging:

```yaml
logger:
  logs:
    custom_components.unique_health_scale: debug
```

## Dashboard-Beispiel

[examples/dashboard-card.yaml](examples/dashboard-card.yaml) ist eine fertige Karte für ein (mobiles) Dashboard: oben die wichtigsten Werte, darunter Verläufe über 90 Tage (Gewicht mit Zielgewicht sowie Fett-, Muskel- und Wasseranteil) und alle übrigen Körperwerte nach Gruppen, einschließlich der Segmente. Die Symbolfarbe zeigt die Einstufung (blau = niedrig, grün = normal, orange = hoch); Tippen auf einen Wert öffnet seinen Verlauf.

Benötigte Frontend-Karten (HACS → Frontend):

- [Mushroom](https://github.com/piitaya/lovelace-mushroom)
- [stack-in-card](https://github.com/custom-cards/stack-in-card)
- [ApexCharts Card](https://github.com/RomRider/apexcharts-card)
- optional [card-mod](https://github.com/thomasloven/lovelace-card-mod) für den Hintergrund (ohne card-mod den `card_mod`-Block löschen)

Einfügen über *Dashboard bearbeiten → Karte hinzufügen → Manuell*. Die Entity-IDs gehen von einem Gerät namens „Smart Scale P1“ und deutscher Oberfläche aus (`sensor.smart_scale_p1_gewicht` usw.); bei anderen Namen `sensor.smart_scale_p1_` per Suchen & Ersetzen anpassen. Die Verläufe nutzen die Langzeitstatistik von Home Assistant (Tagesmittel) und füllen sich nach den ersten Messtagen.

## Entwicklung

```bash
pip install pytest-homeassistant-custom-component aiousbwatcher pyserial
pytest
```

Die Tests simulieren die Waage (Advertising und FFF4-Notifications) gegen ein echtes Home Assistant.

## Roadmap

- [x] Waage erkennen, Rohdaten aufzeichnen
- [x] Gewicht dekodieren
- [x] Impedanzen an echter Hardware mitlesen und in Ohm umrechnen
- [x] Herzfrequenz mitlesen
- [x] Körperwerte berechnen (Körperfett, Muskelmasse, Wasser, Segmentwerte …)
- [ ] Mehrere Personen / Profile

## Hinweis

Inoffizielles Projekt, nicht mit Lefu, PAVABA oder Unique Health verbunden. Die Protokollanalyse dient ausschließlich der Interoperabilität mit eigener Hardware.
