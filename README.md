# Unique Health Scale (Lefu) für Home Assistant

Lokale Home-Assistant-Integration für 8-Elektroden-Körperfettwaagen, die mit der App **Unique Health** (Shenzhen Lefu Scale Co.) arbeiten, z. B. die **PAVABA 8-Elektroden-Waage mit Griff** (Bluetooth-Name `smart scale P1`). Ziel: alle Messwerte direkt per Bluetooth in HA, ohne Cloud und ohne App-Zwang.

> **Status: v0.6 – Gewicht, Herzfrequenz, Segment-Impedanzen und alle Körperwerte (Körperfett, Muskelmasse, Wasser, Segmentwerte …) funktionieren, für beliebig viele Personen. Getestet mit genau einem Modell, siehe [Kompatibilität](#kompatibilität).**
> Das Gewicht wird aus den Funkdaten der Waage gelesen. Für die Körperanalyse verbindet sich die Integration während der Messung mit der Waage und liest die zehn Segment-Impedanzen und die Herzfrequenz mit (an echter Hardware bestätigt). Aus Impedanzen, Gewicht und dem Profil der Person berechnet die Integration die Körperwerte lokal. Details: [docs/protocol.md](docs/protocol.md) und [docs/body-composition.md](docs/body-composition.md).

**Inhalt:** [Kompatibilität](#kompatibilität) · [Voraussetzungen](#voraussetzungen) · [Installation](#installation) · [Einrichtung](#einrichtung) · [Wiegen](#wiegen) · [Mehrere Personen](#mehrere-personen) · [Entitäten](#entitäten) · [Dashboard](#dashboard-beispiel) · [Fehlersuche](#fehlersuche)

## Kompatibilität

Die Unique-Health-App bedient viele verschiedene Waagen. Sie stammen zwar alle von Lefu, unterscheiden sich aber im Funkprotokoll, in der Zahl der Elektroden und in den Kalibrierfaktoren der Körperwert-Berechnung. **Dass eine Waage mit der App funktioniert, heißt deshalb nicht, dass sie auch mit dieser Integration funktioniert.** Garantiert ist nur, was getestet wurde:

| Waage | Bluetooth-Name | Elektroden | Stand |
| --- | --- | --- | --- |
| PAVABA 8-Elektroden-Waage mit Griff (Lefu CF597) | `smart scale P1` | 8 | ✅ getestet: Gewicht, Herzfrequenz, Impedanzen, alle Körperwerte (Abgleich mit der App) |
| andere 8-Elektroden-Waagen der App mit Griff | verschieden | 8 | ❔ ungetestet: Gewicht und Impedanzen kommen wahrscheinlich an, die Körperwerte können abweichen |
| 4-Elektroden-Waagen der App (nur Fußfläche) | verschieden | 4 | ❌ nicht unterstützt: anderes Datenformat, keine Segmentwerte; bestenfalls das Gewicht |
| Waagen anderer Apps | – | – | ❌ nicht unterstützt |

So geht die Integration mit einer Waage um, die nicht in der Liste der getesteten Modelle steht:

- **Gemessenes wird angezeigt, Berechnetes nicht.** Gewicht, Herzfrequenz und Impedanzen erscheinen, sofern die Waage dasselbe Protokoll spricht (Prüfsumme und Plausibilitätsprüfung sichern das ab). Die Körperwerte bleiben leer, weil sie mit einer fremden Kalibrierung falsch sein könnten.
- Unter *Einstellungen → System → Reparaturen* steht der Hinweis „Waage … ist nicht getestet“, im Log eine Warnung.
- Zum Ausprobieren lassen sich die Körperwerte einschalten: *Konfigurieren → Zuordnung und Rückfrage → Körperwerte für ungetestete Waage berechnen*. Danach bitte mit der App vergleichen.
- Erkennt die Integration ein fremdes Datenformat (z. B. das der 4-Elektroden-Waagen, unbekannte Pakete oder einen fehlenden Datenkanal), meldet sie das als Reparatur „… nutzt ein anderes/unbekanntes Protokoll“. Geraten wird nichts.

**Du hast eine andere Waage? Bitte melde dich**, egal ob es klappt oder nicht: [Testbericht anlegen](https://github.com/schaepi85/ha-unique-health-scale/issues/new?template=testbericht.yml). Mit der Diagnose-Datei (siehe [Fehlersuche](#fehlersuche)) lässt sich ein Modell meist schnell einordnen und in die Liste aufnehmen.

## Voraussetzungen

- **Home Assistant 2024.8 oder neuer.** Das eigene Symbol der Integration zeigt Home Assistant ab 2026.3.
- **Bluetooth in Reichweite der Waage** (wenige Meter, möglichst ohne Wände dazwischen). Es gibt zwei Wege:
  - *Adapter am Home-Assistant-Gerät:* eingebautes Bluetooth (z. B. Raspberry Pi) oder ein USB-Stick. Unter *Einstellungen → Geräte & Dienste* muss die Integration **Bluetooth** eingerichtet sein.
  - *Bluetooth-Proxy mit ESPHome:* ein ESP32 in der Nähe der Waage, wenn Home Assistant zu weit weg steht. Wichtig sind **aktive Verbindungen**:

    ```yaml
    esp32_ble_tracker:
    bluetooth_proxy:
      active: true
    ```

    Am einfachsten über die fertigen [ESPHome Bluetooth Proxies](https://esphome.io/projects/?type=bluetooth). Proxys, die nur mithören (z. B. viele Shelly-Geräte), reichen für das Gewicht, aber nicht für die Körperwerte.
- **Die Waage** ist mit Batterien versorgt und stand schon einmal auf festem, ebenem Boden. Ein Konto in der Unique-Health-App wird nicht benötigt.
- **Die App darf nicht gleichzeitig verbunden sein:** Die Waage lässt nur eine Bluetooth-Verbindung zu. Am besten die App während der Messung ganz schließen oder Bluetooth am Handy ausschalten.

## Installation

### Variante A: HACS (empfohlen)

[HACS](https://hacs.xyz/docs/use/) muss installiert sein. Die Integration steht nicht im HACS-Katalog und wird deshalb als benutzerdefiniertes Repository hinzugefügt.

[![Repository in HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=schaepi85&repository=ha-unique-health-scale&category=integration)

Mit dem Knopf oben oder von Hand:

1. In Home Assistant **HACS** öffnen.
2. Oben rechts **⋮ → Benutzerdefinierte Repositories**.
3. Bei *Repository* `https://github.com/schaepi85/ha-unique-health-scale` eintragen, als *Typ* **Integration** wählen, **Hinzufügen**.
4. In HACS nach **Unique Health Scale (Lefu)** suchen, öffnen und unten rechts **Herunterladen**.
5. **Home Assistant neu starten** (*Einstellungen → System → ⏻ → Home Assistant neu starten*).

Aktualisierungen erscheinen später von selbst unter *Einstellungen → Aktualisierungen*; nach jeder Aktualisierung einmal neu starten.

### Variante B: von Hand

1. Auf GitHub **Code → Download ZIP** wählen und die Datei entpacken.
2. Den Ordner `custom_components/unique_health_scale` aus dem ZIP in den Ordner `custom_components` im Konfigurationsverzeichnis von Home Assistant kopieren (dort, wo auch `configuration.yaml` liegt; den Ordner `custom_components` bei Bedarf anlegen). Der Zugriff geht z. B. mit den Add-ons *Samba share*, *File editor* oder *Studio Code Server*.
3. Am Ende muss es die Datei `config/custom_components/unique_health_scale/manifest.json` geben.
4. **Home Assistant neu starten.**

Für eine Aktualisierung den Ordner durch die neue Fassung ersetzen und neu starten.

## Einrichtung

1. **Waage wecken:** kurz auf die Waage stellen, bis die Anzeige leuchtet.
2. **Waage hinzufügen:** Unter *Einstellungen → Geräte & Dienste* erscheint sie nach einigen Sekunden als *Entdeckt* – dort **Hinzufügen** wählen. Falls nicht: **Integration hinzufügen → Unique Health Scale (Lefu)** und die Waage aus der Liste wählen (erkannte Lefu-Waagen stehen oben und tragen den Zusatz `[Lefu]`).

   [![Integration hinzufügen](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=unique_health_scale)
3. **Erste Person anlegen:** Name, Geschlecht, Größe und Geburtsdatum (empfohlen) oder Alter. Das optionale „ungefähre Gewicht“ hilft, die erste Wiegung der richtigen Person zuzuordnen. Diese Angaben bleiben lokal in Home Assistant; die Körperwerte hängen von ihnen ab.
4. **Bereich wählen** (z. B. Badezimmer) und fertigstellen.
5. **Weitere Personen:** *Geräte & Dienste → Unique Health Scale → Konfigurieren → Person hinzufügen*. Dort lassen sich Personen auch bearbeiten und entfernen, siehe [Mehrere Personen](#mehrere-personen).

Danach gibt es das Gerät der Waage und je Person ein eigenes Gerät mit ihren Sensoren. Die Sensoren zeigen „Unbekannt“, bis die erste Messung da ist.

## Wiegen

1. Unique-Health-App schließen.
2. Barfuß auf die Waage stellen, den Griff herausziehen und mit beiden Händen halten, Arme leicht vom Körper weg.
3. Stehen bleiben, bis die Waage die Messung beendet (Gewicht, dann Körperanalyse, dann Herzfrequenz; zusammen rund 20 Sekunden).
4. Das Gewicht erscheint sofort in Home Assistant. Die Körperwerte folgen, sobald die Waage die Analyse über Bluetooth abgegeben hat; das kann ein bis zwei Minuten dauern.

**Home Assistant oder App:** Home Assistant verbindet sich während der Messung mit der Waage. Solange diese Verbindung besteht, bekommt die App nichts mit. Wer ausnahmsweise mit der App messen möchte, deaktiviert die Integration vorher (*Geräte & Dienste → Unique Health Scale → ⋮ → Deaktivieren*) und aktiviert sie danach wieder.

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
- Kalibriert ist die Berechnung für die `smart scale P1` (Lefu CF597). Andere Lefu-Modelle senden zwar ähnlich, verwenden aber andere Kalibrierfaktoren; bei ihnen rechnet die Integration nur auf ausdrücklichen Wunsch, siehe [Kompatibilität](#kompatibilität).
- Sollte der Hersteller Einwände gegen diesen Teil haben, wird er auf Wunsch entfernt – bitte per Issue melden.

## Fehlersuche

| Problem | Ursache und Abhilfe |
| --- | --- |
| Die Waage wird nicht gefunden | Kurz draufstellen, damit sie sendet. Prüfen, ob die Integration *Bluetooth* eingerichtet ist und der Adapter bzw. Proxy nah genug steht. Unter *Integration hinzufügen → Unique Health Scale* stehen alle sichtbaren Bluetooth-Geräte in der Liste. |
| Die Integration taucht unter *Integration hinzufügen* nicht auf | Home Assistant nach der Installation neu starten, Browser-Cache leeren. Bei manueller Installation den Pfad prüfen (`config/custom_components/unique_health_scale/manifest.json`). |
| Nur das Gewicht kommt an, keine Körperwerte | Die App war verbunden, der Griff wurde nicht bis zum Ende gehalten, oder mit Socken gemessen. Bei einem Proxy: `active: true` gesetzt? Der Diagnose-Sensor *Rohdaten* nennt im Attribut `session` den Stand der Verbindung, z. B. „kein verbindungsfaehiger Bluetooth-Adapter in Reichweite“. |
| Hinweis „Waage … ist nicht getestet“ | Das Modell steht nicht in der Liste, siehe [Kompatibilität](#kompatibilität). Körperwerte lassen sich in den Einstellungen einschalten; bitte einen Testbericht schicken. |
| Hinweis „… nutzt ein anderes/unbekanntes Protokoll“ | Die Waage sendet in einem Format, das die Integration nicht kennt. Bitte einen [Testbericht](https://github.com/schaepi85/ha-unique-health-scale/issues/new?template=testbericht.yml) mit Diagnose-Datei anlegen. |
| Hinweis „Keine Körperanalyse von …“ | Drei Messungen hintereinander kamen ohne Impedanzen an. Ursachen wie in der Zeile „Nur das Gewicht“; der Hinweis verschwindet mit der nächsten vollständigen Messung. |
| Körperwerte „Unbekannt“, beim Sensor *Rohdaten* steht im Attribut `body_composition` „Messung ausserhalb des gueltigen Bereichs“ | Die gemessenen Impedanzen passen nicht zusammen (z. B. schlechter Hautkontakt). Die Integration rechnet dann bewusst nicht. Noch einmal messen, mit trockenen bis leicht feuchten Händen und Füßen. |
| Die Wiegung landet bei der falschen Person oder bei niemandem | An der Waage unter **Letzte Wiegung zuordnen** die Person wählen. Bei häufigen Rückfragen die Toleranz anpassen, siehe [Mehrere Personen](#mehrere-personen). |
| Die App zeigt nach dem Wiegen nichts mehr an | Home Assistant hält die Verbindung, siehe [Wiegen](#wiegen). |
| Werte weichen leicht von der App ab | Abweichungen von wenigen Zehnteln sind normal (Rundung). Bei größeren Unterschieden zuerst das Profil prüfen: Größe, Geburtsdatum und Geschlecht müssen mit der App übereinstimmen. |

**Diagnose-Datei:** *Einstellungen → Geräte & Dienste → Unique Health Scale → ⋮ → Diagnose herunterladen*, am besten direkt nach einer Messung. Sie enthält Modell, Verbindungsstand und die letzten Funkdaten. Bluetooth-Adresse, Namen und Geburtsdaten sind unkenntlich gemacht; deine Messwerte (Gewicht, Impedanzen, Herzfrequenz) stehen drin, weil sie für die Fehlersuche gebraucht werden.

**Ausführliches Logging** (in `configuration.yaml`, danach neu starten):

```yaml
logger:
  logs:
    custom_components.unique_health_scale: debug
```

Fehler bitte über [ein Issue](https://github.com/schaepi85/ha-unique-health-scale/issues/new/choose) melden.

## Dashboard-Beispiel

[examples/dashboard-card.yaml](examples/dashboard-card.yaml) ist eine fertige Karte für ein (mobiles) Dashboard: oben die wichtigsten Werte, darunter Verläufe über 90 Tage (Gewicht mit Zielgewicht sowie Fett-, Muskel- und Wasseranteil) und alle übrigen Körperwerte nach Gruppen, einschließlich der Segmente. Die Symbolfarbe zeigt die Einstufung (blau = niedrig, grün = normal, orange = hoch); Tippen auf einen Wert öffnet seinen Verlauf.

Benötigte Frontend-Karten (HACS → Frontend):

- [Mushroom](https://github.com/piitaya/lovelace-mushroom)
- [stack-in-card](https://github.com/custom-cards/stack-in-card)
- [ApexCharts Card](https://github.com/RomRider/apexcharts-card)
- optional [card-mod](https://github.com/thomasloven/lovelace-card-mod) für den Hintergrund (ohne card-mod den `card_mod`-Block löschen)

Einfügen über *Dashboard bearbeiten → Karte hinzufügen → Manuell*. Die Karte zeigt die Werte einer Person. Ihre Entity-IDs gehen von deutscher Oberfläche und dem Präfix `sensor.smart_scale_p1_` aus (`sensor.smart_scale_p1_gewicht` usw.), wie ihn eine von v0.4 aktualisierte Installation behält. Bei einer neuen Installation tragen die Sensoren den Namen der Person (z. B. `sensor.alex_gewicht`): dann `sensor.smart_scale_p1_` per Suchen & Ersetzen durch `sensor.<name>_` ersetzen. Für mehrere Personen die Karte je Person einmal einfügen. Die Verläufe nutzen die Langzeitstatistik von Home Assistant (Tagesmittel) und füllen sich nach den ersten Messtagen.

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
- [x] Ungetestete Waagen erkennen, Diagnose-Datei für Testberichte
- [ ] Weitere Modelle bestätigen (Testberichte willkommen)

## Hinweis

Inoffizielles Projekt, nicht mit Lefu, PAVABA oder Unique Health verbunden. Die Protokollanalyse dient ausschließlich der Interoperabilität mit eigener Hardware.
