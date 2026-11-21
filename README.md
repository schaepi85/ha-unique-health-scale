# Unique Health Scale (Lefu) für Home Assistant

Lokale Home-Assistant-Integration für 8-Elektroden-Körperfettwaagen, die mit der App **Unique Health** (Shenzhen Lefu Scale Co.) arbeiten, z. B. die **PAVABA 8-Elektroden-Waage mit Griff** (Bluetooth-Name `smart scale P1`). Ziel: alle Messwerte direkt per Bluetooth in HA, ohne Cloud und ohne App-Zwang.

> **Status: v0.5 – Gewicht, Herzfrequenz, Segment-Impedanzen und alle Körperwerte (Körperfett, Muskelmasse, Wasser, Segmentwerte …) funktionieren, für beliebig viele Personen.**
> Das Gewicht wird aus den Funkdaten der Waage gelesen. Für die Körperanalyse verbindet sich die Integration während der Messung mit der Waage und liest die zehn Segment-Impedanzen und die Herzfrequenz mit (an echter Hardware bestätigt). Aus Impedanzen, Gewicht und dem Profil der Person berechnet die Integration die Körperwerte lokal. Details: [docs/protocol.md](docs/protocol.md) und [docs/body-composition.md](docs/body-composition.md).

## Voraussetzungen

- Home Assistant 2024.8 oder neuer mit Bluetooth in Reichweite der Waage (eingebauter Adapter oder ESPHome-Bluetooth-Proxy mit aktiven Verbindungen)
- Die Unique-Health-App sollte während der Messung geschlossen sein: Die Waage lässt nur eine Verbindung zu.

## Installation (HACS, benutzerdefiniertes Repository)

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/schaepi85/ha-unique-health-scale` als *Integration* hinzufügen
2. „Unique Health Scale (Lefu)“ installieren, HA neu starten
3. Auf die Waage stellen – HA zeigt sie unter *Einstellungen → Geräte & Dienste* als entdeckt an. Falls nicht: *Integration hinzufügen → Unique Health Scale* und die Waage aus der Liste wählen.
4. Erste Person angeben: Name, Geschlecht, Größe und Geburtsdatum (oder Alter). Weitere Personen und Änderungen: *Geräte & Dienste → Unique Health Scale → Konfigurieren*.

## Mehrere Personen

Unter *Konfigurieren* lassen sich beliebig viele Personen anlegen, bearbeiten und entfernen. Jede Person bekommt ein eigenes Gerät mit eigenen Sensoren (Gewicht, Herzfrequenz, alle Körperwerte, Zeitpunkt der letzten Messung); die Körperwerte werden mit ihrem Profil berechnet.

**Automatische Zuordnung:** Eine Wiegung gehört der Person, deren letztes Gewicht am nächsten liegt. Sie wird ohne Rückfrage zugeordnet, wenn

- das Gewicht höchstens um die Toleranz (Standard 3 kg, einstellbar) vom letzten Gewicht der Person abweicht und
- keine zweite Person ebenfalls in der Toleranz liegt – es sei denn, die nächste Person liegt mindestens 1 kg näher.

Solange eine Person noch nie gewogen wurde, zählt das optionale „ungefähre Gewicht“ aus ihrem Profil. Ist nur eine Person angelegt und noch kein Gewicht bekannt, bekommt sie ihre erste Wiegung direkt.

**Rückfrage:** Passt niemand oder passen mehrere (Beispiel: zwei Personen mit 74 und 75 kg, oder Besuch), bleibt die Wiegung zunächst ohne Person. Home Assistant zeigt eine Mitteilung, und an der Waage steht die Auswahl **Letzte Wiegung zuordnen**: Person wählen, und Gewicht, Herzfrequenz und Körperwerte werden bei ihr eingetragen. Mit `–` bleibt die Wiegung ohne Person. Über dieselbe Auswahl lässt sich auch eine falsche Zuordnung korrigieren; die Sensoren der fälschlich gewählten Person springen auf ihren vorigen Stand zurück (der eine falsche Punkt im Verlauf bleibt allerdings stehen). Die letzte Wiegung bleibt zuordenbar, bis die nächste kommt oder Home Assistant neu startet.

Optional geht die Rückfrage aufs Handy: Unter *Konfigurieren → Zuordnung und Rückfrage* die Geräte der Home-Assistant-App wählen. Die Mitteilung zeigt die bis zu drei nächstliegenden Personen als Knöpfe.

Für Automationen: `select.select_option` auf die Auswahl ordnet zu; ihr Zustand nennt die Person der letzten Wiegung (`–` = offen), die Attribute `weight_kg`, `time` und `candidates` die Details.

**Aktualisierung von v0.4:** Aus dem bisherigen Profil wird automatisch „Person 1“ (unter *Konfigurieren → Person bearbeiten* umbenennbar). Alle Sensoren behalten ihre Entity-IDs und ihren Verlauf; Dashboards und Automationen laufen unverändert weiter. Neu an der Waage ist „Letzte Wiegung“ (Gewicht unabhängig von der Person).

## Entitäten

Je Person (eigenes Gerät):

| Entität | Beschreibung |
| --- | --- |
| Gewicht | Gewicht in kg, sobald es auf der Waage feststeht |
| Herzfrequenz | Herzfrequenz am Ende der Messung |
| Letzte Messung | Zeitpunkt der letzten Wiegung der Person |
| Körperfett, Fettmasse, fettfreie Masse | Anteil in % bzw. Masse in kg |
| Muskelmasse, Skelettmuskelmasse (+ Anteile) | in kg bzw. % |
| Körperwasser (Masse/Anteil), intra-/extrazelluläres Wasser | in kg bzw. % |
| Protein, Mineralien, Knochenmasse, Körperzellmasse | in kg bzw. % |
| Unterhautfett, Viszeralfett, Taille-Hüft-Verhältnis | kg / %, Stufe, Verhältnis |
| BMI, Grundumsatz, empfohlene Kalorienzufuhr, Skelettmuskelindex | |
| Körperpunktzahl, Körperalter, Körpertyp, Adipositasgrad | |
| Idealgewicht, Zielgewicht, Gewichts-/Fett-/Muskelkontrolle | Empfehlung: wie viel ab- bzw. aufbauen |
| Fettmasse / Muskelmasse je Segment | je fünf Sensoren (Arme, Rumpf, Beine) in kg |

An der Waage:

| Entität | Beschreibung |
| --- | --- |
| Letzte Wiegung | Gewicht der letzten Wiegung, egal von wem |
| Letzte Wiegung zuordnen | Auswahl: wem die letzte Wiegung gehört (siehe oben) |
| Impedanz … 20/100 kHz | Diagnose: zehn Sensoren mit den Segment-Impedanzen in Ohm (Arme, Beine, Rumpf bei 20 und 100 kHz) |
| Impedanzen | Diagnose: Übersicht der letzten Körperanalyse, alle Werte als Attribute |
| Rohdaten | Diagnose: letzte Funk- und Verbindungsdaten, Sitzungsstatus, Zuordnung und Verlauf – für die Protokollanalyse |

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
- [x] Mehrere Personen mit automatischer Zuordnung über das Gewicht

## Hinweis

Inoffizielles Projekt, nicht mit Lefu, PAVABA oder Unique Health verbunden. Die Protokollanalyse dient ausschließlich der Interoperabilität mit eigener Hardware.
