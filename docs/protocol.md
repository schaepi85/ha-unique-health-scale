# Protokoll-Notizen

Stand: 2026-11-21 · Gerät: PAVABA 8-Elektroden-Waage mit Griff, Bluetooth-Name **`smart scale P1`**

Quellen: statische Analyse der App „Unique Health“ (iOS, `PPBluetoothKit.framework`) mit REA sowie Mitschnitte der Waage über Home Assistant. Beispiel-Frames in diesem Dokument sind synthetisch (MAC und Gewicht ersetzt).

| Kennzeichnung | Bedeutung |
| --- | --- |
| ✅ bestätigt | an der echten Waage beobachtet |
| 🔎 aus der App | aus dem App-Code abgeleitet, an der Waage noch nicht gesehen |

## Einordnung

- Hersteller der App und der Technik: **Shenzhen Lefu Scale Co., Ltd.**; die App bindet Lefus SDK ein (`PPBluetoothKit`, `PPBaseKit`, `PPBasicCalculateKit`).
- Das SDK ordnet Geräte über den Bluetooth-Namen einer Gerätefamilie zu. Die Frames dieser Waage passen zur Familie **„Ice“** (`PPBluetoothPeripheralIce`, `PPBluetoothIceDataAnalysis`; im Code auch als CF597 bezeichnet). 🔎
- Die Zuordnung Name → Familie liegt in einer Gerätekonfiguration, die die App vom Server lädt. Sie wurde nicht ausgelesen; die Einordnung beruht auf dem Frame-Format.

## Advertising ✅

- Name `smart scale P1`, Dienste `FFF0` und `1812`
- Herstellerdaten unter Company ID **`0xFFFF`** (nicht Lefus `0x1A10`), 17 Bytes:

```
aa bb cc dd ee ff | cf 00 00 4c 1d 00 00 00 00 08 96
└── MAC (6) ─────┘ └── CF-Frame (11) ──────────────┘
```

- Im Ruhezustand sind die 11 Frame-Bytes null.

## CF-Frame (11 Bytes): Gewicht und Status

| Byte | Inhalt | Status |
| --- | --- | --- |
| 0 | `0xCF` | ✅ |
| 1 | Herzfrequenz in Schlägen pro Minute, gültig wenn Byte 2 = `0xC0` | ✅ |
| 2 | `0x80` = Herzfrequenz wird gemessen, `0xC0` = Herzfrequenz liegt vor | ✅ |
| 3–4 | Gewicht, Little Endian, Einheit 0,01 kg | ✅ |
| 5–7 | bei dieser Familie ungenutzt (andere Familien: Impedanz) | ✅ immer 0 |
| 8 | Anzeigeeinheit der Waage | 🔎 |
| 9 | Status, siehe unten | ✅ 0, 1, 3 und 8 |
| 10 | Prüfsumme: XOR der Bytes 0–9 | ✅ |

Status (Byte 9):

| Wert | Bedeutung |
| --- | --- |
| 0 | Messung abgeschlossen ✅ |
| 1 | Gewicht schwankt noch ✅ |
| 2 | Überlast 🔎 |
| 3 | Herzfrequenz wird gemessen (zusammen mit Byte 2 = `0x80`) ✅ |
| 5, 8 | Gewicht steht fest, Körperanalyse beginnt (✅ 8) |
| 6 | Körperanalyse läuft 🔎 |

## Verbindung (GATT)

- Dienst `FFF0` mit **`FFF4` (Notify)** und **`FFF1` (Write)**; dazu Geräteinformation (`180A`) und Batterie (`2A19`). Ein `FFF2` hat diese Waage nicht. ✅
- `FFF4` liefert die Messdaten **ohne Authentifizierung und ohne dass vorher etwas geschrieben wird**: erst der CF-Frame mit Status 8, etwa 0,6 s später vier DF-Frames, danach CF mit Status 3. ✅
- Der Verbindungsaufbau über Home Assistant dauerte im Test rund 10 s; die Waage lieferte die Frames trotzdem vollständig. ✅
- Schreiben über `FFF1` (Zeit setzen, Einheit, Körperfett zurückschreiben); Keep-alive ist der Befehl `1000`. 🔎
- Die App kennt eine optionale Authentifizierung (Befehle `C0`–`C3`, AES); diese Waage braucht sie zum Mitlesen nicht.
- Die App schreibt nach der Berechnung Werte auf die Waage zurück (`cmdWirteBodyFat`). Die Körperwerte entstehen also **in der App**, nicht auf der Waage.

## Ablauf einer Messung ✅

Beobachtet über `FFF4` bei bestehender Verbindung:

| Zeit | Frame | Bedeutung |
| --- | --- | --- |
| 0 s | `cf`, Status 1, etwa viermal pro Sekunde | Gewicht pendelt sich ein |
| ca. 4 s | `cf`, Status 8 | Gewicht steht fest |
| ca. 9 s | vier `df`-Frames (20 kHz Arme+Rumpf, 20 kHz Beine, 100 kHz Arme+Rumpf, 100 kHz Beine) | Impedanzen |
| direkt danach | `cf`, Status 3, Byte 2 = `0x80` | Herzfrequenz wird gemessen |
| ca. 17 s | `cf`, Status 0, Byte 2 = `0xC0`, Byte 1 = Puls | Messung abgeschlossen |

## BF-Frame (23 Bytes): Impedanzen einer Frequenz 🔎

| Byte | Inhalt |
| --- | --- |
| 0 | `0xBF` |
| 1 | Bit 5 gesetzt = Werte zurücksetzen; unteres Nibble: 0 = 20 kHz, 1 = 100 kHz |
| 2–5 | rechter Arm (int32 LE) |
| 6–9 | linker Arm |
| 10–13 | Rumpf |
| 14–17 | rechtes Bein |
| 18–21 | linkes Bein |
| 22 | vermutlich Prüfsumme |

## DF-Frame (17 Bytes): Impedanzen in Teilpaketen ✅

| Byte | Inhalt |
| --- | --- |
| 0 | `0xDF` |
| 1 | `0xFF` = zurücksetzen (🔎); beobachtet: `0x02` |
| 2 | Teil: 0 = Arme + Rumpf, 1 = Beine |
| 3 | Frequenz: 0 = 20 kHz, 1 = 100 kHz |
| 4–7, 8–11, 12–15 | Teil 0: rechter Arm, linker Arm, Rumpf · Teil 1: rechtes Bein, linkes Bein |
| 16 | Prüfsumme: XOR der Bytes 0–15 ✅ |

Diese Waage nutzt DF-Frames; BF-Frames wurden bisher nicht beobachtet.

## Kodierung der Impedanzen ✅

Die Impedanzen heißen im SDK `z20KhzLeftArmEnCode` usw. Jeder 32-Bit-Wert enthält den Messwert (Einheit 0,1 Ω) und einen Zufallsschlüssel, nibbleweise verschränkt:

| Nibble (0 = niederwertig) | Inhalt |
| --- | --- |
| 0, 2, 4, 6 | verschlüsselter Wert `t` (niederwertiges Nibble zuerst) |
| 1, 3 | Schlüsselbyte `k` |
| 5 | Multiplikator `m` |
| 7 | ungenutzt |

Dekodierung: `Wert = (t − k·m) XOR k`.

Zwei Messungen derselben Person ergaben damit bis auf wenige Ohm dieselben Werte in plausibler Größenordnung (Arme und Beine einige hundert Ohm, Rumpf rund 20–25 Ω, bei 100 kHz jeweils niedriger als bei 20 kHz).

## Offene Punkte

1. Gewichtsformat mit der Anzeige der Waage abgleichen
2. Körperwerte aus Gewicht, Profil und Impedanzen berechnen

## Öffentliche Quellen von Lefu

- [LefuHengqi/BluetoothKit-iOSDemo](https://github.com/LefuHengqi/BluetoothKit-iOSDemo), [LefuHengqi/BluetoothKit-AndroidDemo](https://github.com/LefuHengqi/BluetoothKit-AndroidDemo), [LefuHengqi/PPCalculateKit](https://github.com/LefuHengqi/PPCalculateKit)
- Android-SDK als AAR: [LefuHengqi/PPBaseKit-Android](https://github.com/LefuHengqi/PPBaseKit-Android)

## Verwandte Projekte

- [cloudbr34k84/ha-renpho-cloud-ble](https://github.com/cloudbr34k84/ha-renpho-cloud-ble) – andere Lefu-Familien (`0x1A10`)
- [KristianP26/ble-scale-sync](https://github.com/KristianP26/ble-scale-sync), [oliexdev/openScale](https://github.com/oliexdev/openScale)
