"""End-to-End-Test gegen echtes Home Assistant mit simulierter Waage."""
import asyncio
import time
from unittest.mock import AsyncMock, patch

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth import async_get_advertisement_callback
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unique_health_scale.const import DOMAIN
ADDR = "AA:BB:CC:DD:EE:FF"
MAC = "aabbccddeeff"
FFF0 = "0000fff0-0000-1000-8000-00805f9b34fb"
DEVICE = BLEDevice(ADDR, "smart scale P1", {})


def info(frame_hex: str) -> BluetoothServiceInfoBleak:
    mfr = {0xFFFF: bytes.fromhex(MAC + frame_hex)}
    adv = AdvertisementData(local_name="smart scale P1", manufacturer_data=mfr, service_data={},
                            service_uuids=[FFF0], tx_power=None, rssi=-61, platform_data=())
    return BluetoothServiceInfoBleak(name="smart scale P1", address=ADDR, rssi=-61, manufacturer_data=mfr,
        service_data={}, service_uuids=[FFF0], source="local", device=DEVICE, advertisement=adv,
        connectable=True, time=time.monotonic(), tx_power=None)


def inject(hass, frame_hex):
    async_get_advertisement_callback(hass)(info(frame_hex))


IDLE = "0000000000000000000000"
CF_MEASURING = "cf00004c1d00000000019f"
CF_LOCKED = "cf00004c1d000000000896"


def cf(status, hr=0, b2=0, raw=7500):
    b = bytearray([0xCF, hr, b2, raw & 0xFF, raw >> 8, 0, 0, 0, 0, status, 0])
    x = 0
    for v in b[:10]:
        x ^= v
    b[10] = x
    return bytes(b)


def enc(tenths, key=0x35, mult=3):
    t = (tenths ^ key) + key * mult
    n = [(t >> (4 * i)) & 0xF for i in range(4)]
    return n[0] | (key & 0xF) << 4 | n[1] << 8 | (key >> 4) << 12 | n[2] << 16 | mult << 20 | n[3] << 24


def bf(freq, tenths):
    return bytes([0xBF, freq]) + b"".join(enc(v).to_bytes(4, "little") for v in tenths) + b"\x00"


class FakeChar:
    def __init__(self, uuid, props):
        self.uuid, self.properties = uuid, props


class FakeService:
    def __init__(self, chars):
        self.characteristics = chars


class FakeServices(list):
    def get_characteristic(self, uuid):
        for svc in self:
            for c in svc.characteristics:
                if c.uuid == uuid:
                    return c
        return None


class FakeClient:
    def __init__(self):
        self.callbacks = {}
        self.disconnected_callback = None
        self.disconnect = AsyncMock()
        self.is_connected = True
        u = "0000fff%d-0000-1000-8000-00805f9b34fb"
        self.services = FakeServices([FakeService([
            FakeChar(u % 1, ["write", "notify"]), FakeChar(u % 2, ["write-without-response", "notify"]),
            FakeChar(u % 4, ["notify"])])])

    async def start_notify(self, char, cb):
        self.callbacks[char.uuid[4:8]] = cb


PROFILE = {"sex": "male", "height": 180, "age": 35}


async def setup(hass, options=None):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDR, title="smart scale P1", data={CONF_ADDRESS: ADDR},
                            options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass, suffix):
    return hass.states.get(f"sensor.smart_scale_p1_{suffix}")


async def test_advertisement_only(hass, enable_bluetooth):
    """Ohne Verbindung: Gewicht kommt aus dem Advertising."""
    with patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=None):
        await setup(hass)
        for frame in (IDLE, "cf0000e10500000000012a", CF_MEASURING):
            inject(hass, frame)
        await hass.async_block_till_done()
        assert state(hass, "weight").state == "unknown"
        inject(hass, CF_LOCKED)
        await hass.async_block_till_done()
        assert state(hass, "weight").state == "75.0"
        raw = state(hass, "raw_data")
        assert raw.attributes["status"] == 8
        assert raw.attributes["history"][-1]["data"].endswith("0896") or raw.attributes["history"][-1]["src"] == "gatt"
        assert "kein verbindungsfaehiger" in raw.attributes["session"]


async def test_full_session(hass, enable_bluetooth):
    """Mit Verbindung: Gewicht, Impedanzen und Herzfrequenz ueber FFF4."""
    client = FakeClient()

    async def fake_establish(cls, device, name, disconnected_callback=None, **kw):
        client.disconnected_callback = disconnected_callback
        # Wie an der echten Waage beobachtet: Der erste Versuch scheitert und
        # meldet einen Disconnect, bevor die Verbindung steht.
        disconnected_callback(client)
        await asyncio.sleep(0)
        return client

    with patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=DEVICE), \
         patch("custom_components.unique_health_scale.device.establish_connection", side_effect=fake_establish):
        await setup(hass)
        inject(hass, CF_MEASURING)
        for _ in range(20):
            await asyncio.sleep(0)
        assert set(client.callbacks) == {"fff1", "fff2", "fff4"}
        raw = state(hass, "raw_data")
        assert raw.attributes["session"] == "verbunden, lausche auf fff4,fff1,fff2"
        assert raw.attributes["gatt_characteristics"][2] == "fff4 [notify]"

        notify = client.callbacks["fff4"]
        notify(None, bytearray(cf(1)))
        notify(None, bytearray(cf(8)))
        inject(hass, CF_LOCKED)  # Advertising darf waehrend der Sitzung nichts zuruecksetzen
        notify(None, bytearray(bf(0, (3100, 3050, 250, 2600, 2580))))
        inject(hass, CF_MEASURING)
        notify(None, bytearray(bf(1, (2700, 2690, 240, 2250, 2270))))
        notify(None, bytearray(cf(3, b2=0x80)))  # Herzfrequenz wird gemessen
        await hass.async_block_till_done()
        assert state(hass, "raw_data").attributes["session"] == "verbunden, lausche auf fff4,fff1,fff2"
        assert state(hass, "impedances").state == "10"
        notify(None, bytearray(cf(0, hr=72, b2=0xC0)))
        notify(None, bytearray(b"\x12\x34"))
        await hass.async_block_till_done()

        assert state(hass, "weight").state == "75.0"
        assert state(hass, "heart_rate").state == "72"
        imp = state(hass, "impedances")
        assert imp.state == "10" and imp.attributes["complete"] is True
        assert imp.attributes["z20_right_arm"] == 310.0 and imp.attributes["z100_left_leg"] == 227.0
        assert state(hass, "impedance_trunk_20_khz").state == "25.0"
        assert state(hass, "impedance_right_leg_100_khz").state == "225.0"
        assert state(hass, "impedance_right_leg_100_khz").attributes["unit_of_measurement"] == "Ω"
        hist = state(hass, "raw_data").attributes["history"]
        assert [h["src"] for h in hist].count("fff4") == 7

        client.disconnected_callback(client)
        for _ in range(20):
            await asyncio.sleep(0)
        await hass.async_block_till_done()
        assert state(hass, "raw_data").attributes["session"] == "Waage hat getrennt"
        client.disconnect.assert_awaited()


async def test_connection_failure(hass, enable_bluetooth):
    from bleak.exc import BleakError
    with patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=DEVICE), \
         patch("custom_components.unique_health_scale.device.establish_connection", side_effect=BleakError("boom")):
        await setup(hass)
        inject(hass, CF_MEASURING)
        inject(hass, CF_LOCKED)
        for _ in range(20):
            await asyncio.sleep(0)
        await hass.async_block_till_done()
        assert state(hass, "weight").state == "75.0"
        assert "fehlgeschlagen: boom" in state(hass, "raw_data").attributes["session"]


async def test_unload(hass, enable_bluetooth):
    with patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=None):
        entry = await setup(hass)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_bluetooth_discovery_flow(hass, enable_bluetooth):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info(IDLE))
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "bluetooth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "profile"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={"sex": "female", "height": 165})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "age_required"}
    with patch("custom_components.unique_health_scale.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"sex": "female", "height": 165, "birthday": "1997-03-02", "age": 50})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "smart scale P1" and result["data"] == {CONF_ADDRESS: ADDR}
    # Das Geburtsdatum hat Vorrang vor einem zusaetzlich eingetragenen Alter
    assert result["options"] == {"sex": "female", "height": 165, "birthday": "1997-03-02"}


async def test_user_flow(hass, enable_bluetooth):
    inject(hass, IDLE)
    await hass.async_block_till_done()
    for flow in hass.config_entries.flow.async_progress():
        hass.config_entries.flow.async_abort(flow["flow_id"])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    options = result["data_schema"].schema[CONF_ADDRESS].container
    assert options[ADDR].startswith("smart scale P1 [Lefu]")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={CONF_ADDRESS: ADDR})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "profile"
    with patch("custom_components.unique_health_scale.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=PROFILE)
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "smart scale P1"
    assert result["options"] == PROFILE


async def run_measurement(hass, client):
    """Simulierte Messung: 75,00 kg, zehn Impedanzen, Herzfrequenz 72."""
    inject(hass, CF_MEASURING)
    for _ in range(20):
        await asyncio.sleep(0)
    notify = client.callbacks["fff4"]
    notify(None, bytearray(cf(1)))
    notify(None, bytearray(cf(8)))
    notify(None, bytearray(bf(0, (3100, 3050, 250, 2600, 2580))))
    notify(None, bytearray(bf(1, (2700, 2690, 240, 2250, 2270))))
    notify(None, bytearray(cf(0, hr=72, b2=0xC0)))
    await hass.async_block_till_done()


def connected(client):
    async def fake_establish(cls, device, name, disconnected_callback=None, **kw):
        client.disconnected_callback = disconnected_callback
        return client

    return (
        patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=DEVICE),
        patch("custom_components.unique_health_scale.device.establish_connection", side_effect=fake_establish),
    )


async def test_body_composition(hass, enable_bluetooth):
    """Mit Profil entstehen aus der Messung die berechneten Koerperwerte."""
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, PROFILE)
        assert state(hass, "body_fat").state == "unknown"
        assert state(hass, "raw_data").attributes["body_composition"] == "wartet auf Messung"
        await run_measurement(hass, client)

        assert state(hass, "raw_data").attributes["body_composition"] == "berechnet"
        fat = state(hass, "body_fat")
        assert fat.state == "13.8" and fat.attributes["unit_of_measurement"] == "%"
        assert fat.attributes["normal_min"] == 10.0 and fat.attributes["normal_max"] == 20.0
        assert fat.attributes["rating"] == "normal"
        muscle = state(hass, "muscle_mass")
        assert muscle.state == "60.2" and muscle.attributes["device_class"] == "weight"
        assert muscle.attributes["balance_arms"] == "balanced"
        assert state(hass, "body_water").state == "63.2"
        assert state(hass, "visceral_fat").state == "6"
        assert state(hass, "body_score").state == "84"
        assert state(hass, "body_age").state == "31"
        assert state(hass, "body_type").state == "fat_normal_muscle_normal"
        arm = state(hass, "muscle_mass_right_arm")
        assert float(arm.state) > 2 and arm.attributes["rating"] in ("low", "normal", "high")
        assert arm.attributes["percent_of_reference"] > 50
        assert float(state(hass, "weight_control").state) > 0
        # Jeder berechnete Wert hat einen Sensor mit Zustand
        from custom_components.unique_health_scale.sensor import BODY_SENSORS
        registry = hass.data["entity_registry"]
        for description in BODY_SENSORS:
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{ADDR}_{description.key}")
            assert hass.states.get(entity_id).state not in ("unknown", "unavailable"), description.key

        # Werte ueberstehen das Neuladen (z. B. nach einer Profilaenderung)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert state(hass, "body_fat").state == "13.8"
        assert state(hass, "body_fat").attributes["rating"] == "normal"


async def test_no_profile_no_body_values(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        await setup(hass)
        await run_measurement(hass, client)
        assert state(hass, "weight").state == "75.0"
        assert state(hass, "body_fat").state == "unknown"
        assert state(hass, "raw_data").attributes["body_composition"] == "kein Profil hinterlegt"


async def test_measurement_out_of_range(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        await setup(hass, {"sex": "male", "height": 180, "age": 5})
        await run_measurement(hass, client)
        assert state(hass, "body_fat").state == "unknown"
        assert state(hass, "raw_data").attributes["body_composition"].endswith("Bereichs: age")


async def test_options_flow_changes_profile(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, PROFILE)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM and result["step_id"] == "init"
        result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={"sex": "female", "height": 180})
        assert result["errors"] == {"base": "age_required"}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"sex": "female", "height": 180, "age": 35})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert entry.options == {"sex": "female", "height": 180, "age": 35}

        # Der Eintrag wurde neu geladen; die naechste Messung rechnet mit dem neuen Profil
        client.callbacks.clear()
        await run_measurement(hass, client)
        assert state(hass, "body_fat").attributes["normal_min"] == 18.0
