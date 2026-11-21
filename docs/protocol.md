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

## Verwandte Projekte

- [cloudbr34k84/ha-renpho-cloud-ble](https://github.com/cloudbr34k84/ha-renpho-cloud-ble) – dekodiert Lefu-Waagen (`0x1A10`, Familien „0x55aa“ und „MorphoScan“) lokal
- [KristianP26/ble-scale-sync](https://github.com/KristianP26/ble-scale-sync)
- [oliexdev/openScale](https://github.com/oliexdev/openScale)

## Offene Punkte

1. Echte Frames der PAVABA mitschneiden (Sensor „Rohdaten“), Gerätename und Modellcode notieren
2. In `PPBluetoothKit` die Parser für Advertising-Frames und `FFF0`-Notifications finden
3. Klären, ob die Waage fertige Körperwerte oder nur Impedanzen schickt
4. Falls aktive Verbindung nötig: Handshake (Benutzerprofil, Zeit) nachbauen
