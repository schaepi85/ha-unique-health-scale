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
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
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
ALEX = {"id": "a1", "name": "Alex", **PROFILE}
KIM = {"id": "k2", "name": "Kim", "sex": "female", "height": 165, "birthday": "1997-03-02"}


def persons(*items):
    return {"persons": list(items)}


async def setup(hass, options=None, version=2):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDR, title="smart scale P1", data={CONF_ADDRESS: ADDR},
                            options=options or {}, version=version)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass, suffix, owner="smart_scale_p1"):
    return hass.states.get(f"sensor.{owner}_{suffix}")


def alex(hass, suffix):
    return state(hass, suffix, "alex")


def kim(hass, suffix):
    return state(hass, suffix, "kim")


ASSIGN = "select.smart_scale_p1_assign_last_weighing"


async def test_advertisement_only(hass, enable_bluetooth):
    """Ohne Verbindung: Gewicht kommt aus dem Advertising."""
    with patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=None):
        await setup(hass)
        for frame in (IDLE, "cf0000e10500000000012a", CF_MEASURING):
            inject(hass, frame)
        await hass.async_block_till_done()
        assert state(hass, "last_weighing").state == "unknown"
        inject(hass, CF_LOCKED)
        await hass.async_block_till_done()
        assert state(hass, "last_weighing").state == "75.0"
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
        await setup(hass, persons(ALEX))
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

        assert state(hass, "last_weighing").state == "75.0"
        assert alex(hass, "weight").state == "75.0"
        assert alex(hass, "heart_rate").state == "72"
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
        assert state(hass, "last_weighing").state == "75.0"
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
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={"name": "Kim", "sex": "female", "height": 165})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "age_required"}
    with patch("custom_components.unique_health_scale.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"name": " Kim ", "sex": "female", "height": 165, "birthday": "1997-03-02", "age": 50})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "smart scale P1" and result["data"] == {CONF_ADDRESS: ADDR}
    # Das Geburtsdatum hat Vorrang vor einem zusaetzlich eingetragenen Alter
    (person,) = result["options"]["persons"]
    assert len(person.pop("id")) == 8
    assert person == {"name": "Kim", "sex": "female", "height": 165, "birthday": "1997-03-02"}


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
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={"name": "Alex", **PROFILE, "reference_weight": 74.5})
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "smart scale P1"
    (person,) = result["options"]["persons"]
    assert person["name"] == "Alex" and person["age"] == 35 and person["reference_weight"] == 74.5


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
    """Mit einer Person entstehen aus der Messung deren berechnete Koerperwerte."""
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, persons(ALEX))
        assert alex(hass, "body_fat").state == "unknown"
        raw = state(hass, "raw_data").attributes
        assert raw["body_composition"] == {"Alex": "wartet auf Messung"}
        assert raw["assignment"] == "wartet auf Messung"
        await run_measurement(hass, client)

        raw = state(hass, "raw_data").attributes
        assert raw["body_composition"] == {"Alex": "berechnet"} and raw["assignment"] == "zugeordnet: Alex"
        fat = alex(hass, "body_fat")
        assert fat.state == "13.8" and fat.attributes["unit_of_measurement"] == "%"
        assert fat.attributes["normal_min"] == 10.0 and fat.attributes["normal_max"] == 20.0
        assert fat.attributes["rating"] == "normal"
        muscle = alex(hass, "muscle_mass")
        assert muscle.state == "60.2" and muscle.attributes["device_class"] == "weight"
        assert muscle.attributes["balance_arms"] == "balanced"
        assert alex(hass, "body_water").state == "63.2"
        assert alex(hass, "visceral_fat").state == "6"
        assert alex(hass, "body_score").state == "84"
        assert alex(hass, "body_age").state == "31"
        assert alex(hass, "body_type").state == "fat_normal_muscle_normal"
        arm = alex(hass, "muscle_mass_right_arm")
        assert float(arm.state) > 2 and arm.attributes["rating"] in ("low", "normal", "high")
        assert arm.attributes["percent_of_reference"] > 50
        assert float(alex(hass, "weight_control").state) > 0
        assert alex(hass, "last_measurement").state not in ("unknown", "unavailable")
        # Jeder berechnete Wert hat einen Sensor mit Zustand, am Geraet der Person
        from custom_components.unique_health_scale.sensor import BODY_SENSORS
        registry = er.async_get(hass)
        person_device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{ADDR}_a1")})
        scale_device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, ADDR)})
        assert person_device.name == "Alex" and person_device.via_device_id == scale_device.id
        for description in BODY_SENSORS:
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{ADDR}_a1_{description.key}")
            assert hass.states.get(entity_id).state not in ("unknown", "unavailable"), description.key
            assert registry.async_get(entity_id).device_id == person_device.id

        # Werte ueberstehen das Neuladen (z. B. nach einer Profilaenderung)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert alex(hass, "body_fat").state == "13.8"
        assert alex(hass, "body_fat").attributes["rating"] == "normal"
        assert alex(hass, "heart_rate").state == "72"


async def test_no_person_no_body_values(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        await setup(hass)
        await run_measurement(hass, client)
        assert state(hass, "last_weighing").state == "75.0"
        assert hass.states.get(ASSIGN) is None
        assert state(hass, "raw_data").attributes["body_composition"] == "keine Person hinterlegt"
        assert not hass.states.async_all("persistent_notification")


async def test_measurement_out_of_range(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        await setup(hass, persons({**ALEX, "age": 5}))
        await run_measurement(hass, client)
        assert alex(hass, "body_fat").state == "unknown"
        assert alex(hass, "weight").state == "75.0"
        assert state(hass, "raw_data").attributes["body_composition"]["Alex"].endswith("Bereichs: age")


# ---------------------------------------------------------------------------
# Mehrere Personen
# ---------------------------------------------------------------------------


def notifications(hass):
    from homeassistant.components.persistent_notification import _async_get_or_create_notifications
    return _async_get_or_create_notifications(hass)


async def weigh(hass, client, raw, tenths20=(3100, 3050, 250, 2600, 2580), tenths100=(2700, 2690, 240, 2250, 2270), hr=72):
    """Simulierte Wiegung mit frei waehlbarem Gewicht (raw = 0,01 kg)."""
    if "fff4" not in client.callbacks:
        inject(hass, cf(1, raw=raw).hex())
        for _ in range(20):
            await asyncio.sleep(0)
    notify = client.callbacks["fff4"]
    notify(None, bytearray(cf(1, raw=raw)))
    notify(None, bytearray(cf(8, raw=raw)))
    notify(None, bytearray(bf(0, tenths20)))
    notify(None, bytearray(bf(1, tenths100)))
    notify(None, bytearray(cf(0, hr=hr, b2=0xC0, raw=raw)))
    await hass.async_block_till_done()


async def test_automatic_assignment_by_weight(hass, enable_bluetooth):
    """Zwei Personen mit bekanntem Gewicht: Jede Wiegung landet bei der richtigen."""
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        await setup(hass, persons({**ALEX, "reference_weight": 75}, {**KIM, "reference_weight": 58}))
        await weigh(hass, client, 7520)
        assert alex(hass, "weight").state == "75.2" and kim(hass, "weight").state == "unknown"
        assert alex(hass, "body_fat").state != "unknown" and kim(hass, "body_fat").state == "unknown"
        assert hass.states.get(ASSIGN).state == "Alex"
        alex_fat = alex(hass, "body_fat").state

        await weigh(hass, client, 5790, hr=64)
        assert kim(hass, "weight").state == "57.9" and kim(hass, "heart_rate").state == "64"
        assert kim(hass, "body_fat").state not in ("unknown", alex_fat)
        # Kims Wiegung aendert bei Alex nichts
        assert alex(hass, "weight").state == "75.2" and alex(hass, "body_fat").state == alex_fat
        assert alex(hass, "heart_rate").state == "72"
        assert hass.states.get(ASSIGN).state == "Kim"
        assert state(hass, "last_weighing").state == "57.9"
        assert not notifications(hass)

        # Ab jetzt zaehlt das zuletzt gemessene Gewicht, nicht mehr die Angabe im Profil
        await weigh(hass, client, 5650)
        assert kim(hass, "weight").state == "56.5"


async def test_ambiguous_weighing_asks_and_select_assigns(hass, enable_bluetooth):
    """Aehnliches Gewicht: Rueckfrage, Zuordnung ueber die Auswahl, Korrektur moeglich."""
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        await setup(hass, persons({**ALEX, "reference_weight": 75}, {**KIM, "reference_weight": 74.5}))
        await weigh(hass, client, 7480)
        assert alex(hass, "weight").state == "unknown" and kim(hass, "weight").state == "unknown"
        select = hass.states.get(ASSIGN)
        assert select.state == "–" and select.attributes["options"] == ["Alex", "Kim", "–"]
        assert select.attributes["weight_kg"] == 74.8 and select.attributes["candidates"] == ["Alex", "Kim"]
        (notification,) = notifications(hass).values()
        assert "74.80 kg" in notification["message"] and "Alex, Kim" in notification["message"]
        assert state(hass, "raw_data").attributes["assignment"] == "nicht zugeordnet"

        await hass.services.async_call("select", "select_option", {"entity_id": ASSIGN, "option": "Kim"}, blocking=True)
        await hass.async_block_till_done()
        assert kim(hass, "weight").state == "74.8" and kim(hass, "body_fat").state != "unknown"
        assert kim(hass, "heart_rate").state == "72"
        assert alex(hass, "weight").state == "unknown"
        assert not notifications(hass)

        # Doch falsch: umhaengen nimmt die Werte bei Kim zurueck
        await hass.services.async_call("select", "select_option", {"entity_id": ASSIGN, "option": "Alex"}, blocking=True)
        await hass.async_block_till_done()
        assert alex(hass, "weight").state == "74.8" and alex(hass, "body_fat").state != "unknown"
        assert kim(hass, "weight").state == "unknown" and kim(hass, "body_fat").state == "unknown"
        assert kim(hass, "heart_rate").state == "unknown" and kim(hass, "last_measurement").state == "unknown"

        # Und ganz verwerfen (z. B. Besuch)
        await hass.services.async_call("select", "select_option", {"entity_id": ASSIGN, "option": "–"}, blocking=True)
        await hass.async_block_till_done()
        assert alex(hass, "weight").state == "unknown" and alex(hass, "body_fat").state == "unknown"
        assert hass.states.get(ASSIGN).state == "–"


async def test_unknown_weight_asks_and_new_person_can_take_it(hass, enable_bluetooth):
    """Niemand passt: Rueckfrage; die Wiegung uebersteht das Anlegen der neuen Person."""
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, persons({**ALEX, "reference_weight": 75}))
        await weigh(hass, client, 4210)
        assert alex(hass, "weight").state == "unknown"
        assert len(notifications(hass)) == 1

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_person"})
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"name": "Robin", "sex": "female", "height": 150, "age": 12})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        select = hass.states.get(ASSIGN)
        assert select.state == "–" and select.attributes["options"] == ["Alex", "Robin", "–"]

        await hass.services.async_call("select", "select_option", {"entity_id": ASSIGN, "option": "Robin"}, blocking=True)
        await hass.async_block_till_done()
        assert state(hass, "weight", "robin").state == "42.1"
        assert state(hass, "body_fat", "robin").state != "unknown"
        assert not notifications(hass)


async def test_mobile_question_and_answer(hass, enable_bluetooth):
    """Rueckfrage aufs Handy mit Knoepfen; die Antwort ordnet zu."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    client = FakeClient()
    device_patch, connect_patch = connected(client)
    calls = async_mock_service(hass, "notify", "mobile_app_phone")
    with device_patch, connect_patch:
        await setup(hass, {**persons(ALEX, KIM), "notify": ["mobile_app_phone"]})
        await weigh(hass, client, 6800)
        await hass.async_block_till_done()
        (call,) = calls
        assert "68.00 kg" in call.data["message"]
        actions = call.data["data"]["actions"]
        assert [action["title"] for action in actions] == ["Alex", "Kim"]

        hass.bus.async_fire("mobile_app_notification_action", {"action": "UHS_other"})
        hass.bus.async_fire("mobile_app_notification_action", {"action": actions[1]["action"]})
        await hass.async_block_till_done()
        assert kim(hass, "weight").state == "68.0" and alex(hass, "weight").state == "unknown"
        assert calls[-1].data["message"] == "clear_notification"
        assert not notifications(hass)


async def test_single_person_rejects_far_off_weight(hass, enable_bluetooth):
    """Auch bei nur einer Person landet ein fremdes Gewicht nicht in ihrem Verlauf."""
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        await setup(hass, persons(ALEX))
        await weigh(hass, client, 7500)
        assert alex(hass, "weight").state == "75.0"
        await weigh(hass, client, 3120)
        assert alex(hass, "weight").state == "75.0"
        assert hass.states.get(ASSIGN).state == "–" and len(notifications(hass)) == 1
        # Die naechste passende Wiegung raeumt die Rueckfrage ab
        await weigh(hass, client, 7460)
        assert alex(hass, "weight").state == "74.6" and not notifications(hass)


async def test_last_weight_survives_restart_for_matching(hass, enable_bluetooth):
    """Nach dem Neuladen kommt das Vergleichsgewicht aus dem wiederhergestellten Sensor."""
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, persons(ALEX, KIM))
        await weigh(hass, client, 7500)
        await hass.services.async_call("select", "select_option", {"entity_id": ASSIGN, "option": "Alex"}, blocking=True)
        await weigh(hass, client, 5800)
        await hass.services.async_call("select", "select_option", {"entity_id": ASSIGN, "option": "Kim"}, blocking=True)
        await hass.async_block_till_done()
        client.callbacks.clear()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await weigh(hass, client, 7440)
        assert alex(hass, "weight").state == "74.4" and kim(hass, "weight").state == "58.0"


async def test_options_flow_manages_persons(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, persons(ALEX))
        flow = hass.config_entries.options

        # Hinzufuegen: bis zur Grossfamilie
        for index, name in enumerate(("Kim", "Robin", "Sam", "Toni", "Mika"), start=2):
            result = await flow.async_init(entry.entry_id)
            assert result["type"] is FlowResultType.MENU
            assert result["menu_options"] == ["add_person", "edit_person", "remove_person", "settings"]
            result = await flow.async_configure(result["flow_id"], {"next_step_id": "add_person"})
            if name == "Kim":
                result = await flow.async_configure(result["flow_id"], {"name": "alex", "sex": "female", "height": 165, "age": 30})
                assert result["errors"] == {"name": "name_exists"}
                result = await flow.async_configure(result["flow_id"], {"name": "Kim", "sex": "female", "height": 165})
                assert result["errors"] == {"base": "age_required"}
            result = await flow.async_configure(result["flow_id"], {"name": name, "sex": "female", "height": 165, "age": 30})
            assert result["type"] is FlowResultType.CREATE_ENTRY
            await hass.async_block_till_done()
            assert len(entry.options["persons"]) == index
        assert kim(hass, "weight") is not None and state(hass, "bmi", "mika") is not None
        assert len(hass.states.get(ASSIGN).attributes["options"]) == 7

        # Bearbeiten: Profil und Name; Entity-IDs bleiben
        result = await flow.async_init(entry.entry_id)
        result = await flow.async_configure(result["flow_id"], {"next_step_id": "edit_person"})
        assert result["step_id"] == "edit_person"
        result = await flow.async_configure(result["flow_id"], {"id": "a1"})
        assert result["step_id"] == "person"
        result = await flow.async_configure(result["flow_id"], {"name": "Alexandra", "sex": "female", "height": 180, "age": 35})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert entry.options["persons"][0] == {"id": "a1", "name": "Alexandra", "sex": "female", "height": 180, "age": 35}
        assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{ADDR}_a1")}).name == "Alexandra"
        client.callbacks.clear()
        await weigh(hass, client, 7500)
        await hass.services.async_call("select", "select_option", {"entity_id": ASSIGN, "option": "Alexandra"}, blocking=True)
        await hass.async_block_till_done()
        assert alex(hass, "body_fat").attributes["normal_min"] == 18.0

        # Entfernen: Geraet und Sensoren der Person verschwinden
        kim_id = entry.options["persons"][1]["id"]
        result = await flow.async_init(entry.entry_id)
        result = await flow.async_configure(result["flow_id"], {"next_step_id": "remove_person"})
        result = await flow.async_configure(result["flow_id"], {"id": kim_id})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert len(entry.options["persons"]) == 5
        assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"{ADDR}_{kim_id}")}) is None
        assert kim(hass, "weight") is None and alex(hass, "weight").state == "75.0"

        # Einstellungen
        result = await flow.async_init(entry.entry_id)
        result = await flow.async_configure(result["flow_id"], {"next_step_id": "settings"})
        result = await flow.async_configure(result["flow_id"], {"tolerance": 2, "notify": ["mobile_app_phone"]})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert entry.options["tolerance"] == 2.0 and entry.options["notify"] == ["mobile_app_phone"]
        assert len(entry.options["persons"]) == 5
        assert entry.runtime_data.tolerance_kg == 2.0


async def test_migration_keeps_entities_and_history(hass, enable_bluetooth):
    """Version 1 mit Profil: Sensoren wandern mit Entity-ID zur ersten Person."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDR, title="smart scale P1", data={CONF_ADDRESS: ADDR},
                            options={"sex": "male", "height": 180, "birthday": "1990-05-17"}, version=1)
    entry.add_to_hass(hass)
    devices, registry = dr.async_get(hass), er.async_get(hass)
    scale = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, ADDR)}, name="smart scale P1")
    area = ar.async_get(hass).async_create("Bad")
    devices.async_update_device(scale.id, area_id=area.id)
    old = {}
    for key in ("weight", "heart_rate", "bmi", "body_fat_percent", "muscle_left_leg", "raw_frame", "z20_trunk"):
        old[key] = registry.async_get_or_create(
            "sensor", DOMAIN, f"{ADDR}_{key}", config_entry=entry, device_id=scale.id,
            suggested_object_id=f"bad_smart_scale_p1_{key}").entity_id

    with patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=None):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.version == 2
    (person,) = entry.options["persons"]
    assert person == {"id": person["id"], "name": "Person 1", "sex": "male", "height": 180, "birthday": "1990-05-17"}
    person_device = devices.async_get_device(identifiers={(DOMAIN, f"{ADDR}_{person['id']}")})
    assert person_device.area_id == area.id and person_device.name == "Person 1"
    assert person_device.via_device_id == scale.id
    for key in ("weight", "heart_rate", "bmi", "body_fat_percent", "muscle_left_leg"):
        entity = registry.async_get(old[key])
        assert entity.unique_id == f"{ADDR}_{person['id']}_{key}" and entity.device_id == person_device.id, key
        assert hass.states.get(old[key]) is not None
    for key in ("raw_frame", "z20_trunk"):
        entity = registry.async_get(old[key])
        assert entity.unique_id == f"{ADDR}_{key}" and entity.device_id == scale.id
    # Keine doppelten Sensoren
    assert len([e for e in er.async_entries_for_config_entry(registry, entry.entry_id) if e.unique_id.endswith("_bmi")]) == 1


async def test_migration_without_profile(hass, enable_bluetooth):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDR, title="smart scale P1", data={CONF_ADDRESS: ADDR}, version=1)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    weight = registry.async_get_or_create("sensor", DOMAIN, f"{ADDR}_weight", config_entry=entry).entity_id
    bmi = registry.async_get_or_create("sensor", DOMAIN, f"{ADDR}_bmi", config_entry=entry).entity_id
    with patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=None):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.version == 2 and entry.options == {"persons": []}
    assert registry.async_get(weight).unique_id == f"{ADDR}_last_weight"
    assert registry.async_get(bmi) is None


async def test_renaming_a_person_entity_keeps_it(hass, enable_bluetooth):
    """Entity-ID aendern legt die Entitaet neu an; das darf am Geraet der Person nicht scheitern."""
    with patch("custom_components.unique_health_scale.device.bluetooth.async_ble_device_from_address", return_value=None):
        await setup(hass, persons(ALEX))
        er.async_get(hass).async_update_entity("sensor.alex_last_measurement", new_entity_id="sensor.scale_alex_last")
        await hass.async_block_till_done()
        assert hass.states.get("sensor.scale_alex_last") is not None
        from custom_components.unique_health_scale import sensor
        import inspect
        assert "via_device=" not in inspect.getsource(sensor)
