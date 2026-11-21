"""Konstanten fuer die Unique-Health-/Lefu-Waagen-Integration."""

DOMAIN = "unique_health_scale"

# Bluetooth-Company-ID von Lefu (Shenzhen Lefu Scale Co.), 0x1A10
LEFU_MANUFACTURER_ID = 0x1A10

# GATT-Dienst, den die Unique-Health-App (PPBluetoothKit) anspricht
LEFU_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"

# Wie viele Rohframes als Attribut fuer die Protokollanalyse gehalten werden
RAW_HISTORY_SIZE = 25
