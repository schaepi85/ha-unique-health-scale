"""Konstanten fuer die Unique-Health-/Lefu-Waagen-Integration."""

DOMAIN = "unique_health_scale"

# Bluetooth-Company-ID von Lefu (Shenzhen Lefu Scale Co.), 0x1A10.
# Die PAVABA ("smart scale P1") sendet allerdings unter 0xFFFF.
LEFU_MANUFACTURER_ID = 0x1A10

# GATT-Dienst und Characteristics der Lefu-Geraetefamilie "Ice" (CF597/CF577 ...)
LEFU_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"
CHAR_FFF2 = "0000fff2-0000-1000-8000-00805f9b34fb"
CHAR_FFF4 = "0000fff4-0000-1000-8000-00805f9b34fb"  # Messdaten (Notify)
NOTIFY_CHARS = (CHAR_FFF4, CHAR_FFF1, CHAR_FFF2)

# Wie viele Rohframes als Attribut fuer die Protokollanalyse gehalten werden
RAW_HISTORY_SIZE = 60

# Verbindung: maximale Dauer einer Messsitzung und Pause zwischen Versuchen
SESSION_TIMEOUT = 120.0
CONNECT_COOLDOWN = 15.0
