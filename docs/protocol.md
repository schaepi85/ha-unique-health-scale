# Protokoll-Notizen

Stand: 2026-11-21

## Herkunft der Waage

- App „Unique Health“, Entwickler **Shenzhen Lefu Scale Co., Ltd.**; auf dem Mac installiert als `XMProject.app` (iOS-App, arm64)
- Die App bindet Lefus SDK ein: `PPBluetoothKit.framework`, `PPBaseKit.framework`, `PPBasicCalculateKit.bundle`
- Lefu-Waagen senden Herstellerdaten mit **Bluetooth Company ID `0x1A10`**

## Erkenntnisse aus der App (REA, statisch)

- Bluetooth: Die App sucht den GATT-Dienst **`FFF0`** (`discoverFFF0Service`)
- SDK-Klassen/Delegates: `PPBluetoothAdvDeviceModel`, `PPBluetoothScaleBaseModel`, `PPBluetooth180ADeviceModel`, `PPBluetoothScaleDataDelegate`, `PPBluetoothCMDDataDelegate`, **`PPBluetoothCalculateInScaleDataDelegate`** (liefert ein `PPBodyFatModel`)
  → Hinweis, dass dieses Modell die Körperanalyse **auf der Waage selbst** rechnet und fertige Werte überträgt. Zu prüfen.
- Ressourcen in der App: `BodyParam.json`, `BodyParam_HT_8.json`, `scale_8.json` (vermutlich Kennzahl-Definitionen/Grenzwerte für 8-Elektroden-Modelle)
- Algorithmus-Kennung im Binary: `LF_4_Z_Lefu_2023-05-15_V1.0.0`
- Cloud: `uhde.lefuenergy.com` (EU/DE-Region), `uhus.lefuenergy.com`, `unique.lefuenergy.com` – möglicher Fallback

## Wie Lefus SDK ein Gerät einordnet (REA, `PPBluetoothKit` iOS)

- `+[PPBluetoothAdvDeviceModel filterDeviceTypeAdvModelByCBAdvDataManufacturerData:andDeivceName:RSSI:]` gleicht den **Bluetooth-Namen** gegen eine Gerätekonfigurationsliste ab (erst exakt, dann unscharf per `CONTAINS`). Je nach Protokoll kommen Länge der Herstellerdaten (`advLength`), MAC-Position (`macAddressStart`) und eine Signatur (`sign`) dazu.
  → Die Herstellerdaten stehen **nicht zwingend** unter Company ID `0x1A10`. Die Integration zeichnet deshalb alle Hersteller- und Service-Daten auf und bietet im Einrichtungsdialog alle sichtbaren Geräte an.
- Aus der Konfiguration ergeben sich `deviceConnectType`, `deviceProtocolType`, `deviceType`, `deviceCalcuteType`. `-[PPBluetoothAdvDeviceModel PeripheralType]` bildet das auf eine Gerätefamilie ab (Codenamen im SDK: Apple, Banana, Coconut, Durian, Egg, Fish, Grapes, Hamburger, Ice, Jambul, Torre, Borre, Dorre, Forre, Korre, Lorre, Morre). Jede Familie hat eigene Klassen `PPBluetoothPeripheral<Familie>`, `PPBluetoothCMD<Familie>` und `PPBluetooth<Familie>DataAnalysis`.
- **Entscheidend ist also der Bluetooth-Name der Waage.** Erst damit steht fest, welche Familie (und damit welches Frame-Format) gilt.

## Öffentliche Quellen von Lefu

- SDK-Demos und Doku: [LefuHengqi/BluetoothKit-iOSDemo](https://github.com/LefuHengqi/BluetoothKit-iOSDemo), [LefuHengqi/BluetoothKit-AndroidDemo](https://github.com/LefuHengqi/BluetoothKit-AndroidDemo) (enthält eine Architekturübersicht des SDK), [LefuHengqi/PPCalculateKit](https://github.com/LefuHengqi/PPCalculateKit)
- Android-SDK als AAR (teils obfuskiert): [LefuHengqi/PPBaseKit-Android](https://github.com/LefuHengqi/PPBaseKit-Android) – `ppbluetoothkit`, `ppcalculatekit` (mit `BodyParam_HT_8.json`), `ppbasekit`
- Berechnung laut SDK-Übersicht: `CalculateManager` verzweigt nach `deviceCalcuteType`, u. a. `CalculateHelper8` für 8 Elektroden

## Verwandte Projekte

- [cloudbr34k84/ha-renpho-cloud-ble](https://github.com/cloudbr34k84/ha-renpho-cloud-ble) – dekodiert Lefu-Waagen (`0x1A10`, Familien „0x55aa“ und „MorphoScan“) lokal
- [KristianP26/ble-scale-sync](https://github.com/KristianP26/ble-scale-sync)
- [oliexdev/openScale](https://github.com/oliexdev/openScale)

## Offene Punkte

1. **Bluetooth-Namen** der PAVABA und echte Frames mitschneiden (Sensor „Rohdaten“)
2. Daraus die Gerätefamilie bestimmen und deren `…DataAnalysis`-Klasse dekompilieren
3. Klären, ob die Waage fertige Körperwerte oder nur Impedanzen schickt
4. Falls aktive Verbindung nötig: Handshake (Benutzerprofil, Zeit) über Dienst `FFF0` nachbauen
