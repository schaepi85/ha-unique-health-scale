"""Ungetestete Waagen und fremde Protokolle: Hinweis statt falscher Werte."""
import asyncio
import time

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth import async_get_advertisement_callback
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unique_health_scale.compat import is_tested
from custom_components.unique_health_scale.const import DOMAIN
from custom_components.unique_health_scale.diagnostics import async_get_config_entry_diagnostics

from test_integration import (
    ADDR, ALEX, CF_MEASURING, FFF0, IDLE, MAC, FakeClient, alex, bf, cf, connected, inject, persons, run_measurement,
    setup,
)

OTHER = "Health Scale X9"


def inject_as(hass, name, frame_hex, company=0xFFFF):
    mfr = {company: bytes.fromhex(MAC + frame_hex)}
    device = BLEDevice(ADDR, name, {})
    adv = AdvertisementData(local_name=name, manufacturer_data=mfr, service_data={},
                            service_uuids=[FFF0], tx_power=None, rssi=-61, platform_data=())
    async_get_advertisement_callback(hass)(BluetoothServiceInfoBleak(
        name=name, address=ADDR, rssi=-61, manufacturer_data=mfr, service_data={}, service_uuids=[FFF0],
        source="local", device=device, advertisement=adv, connectable=True, time=time.monotonic(), tx_power=None))


async def setup_other(hass, options):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDR, title=OTHER, data={CONF_ADDRESS: ADDR},
                            options=options, version=2)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def measure_other(hass, client, extra=()):
    inject_as(hass, OTHER, IDLE)
    inject_as(hass, OTHER, CF_MEASURING)
    for _ in range(20):
        await asyncio.sleep(0)
    notify = client.callbacks["fff4"]
    notify(None, bytearray(cf(1)))
    notify(None, bytearray(cf(8)))
    for frame in extra:
        notify(None, bytearray(frame))
    await hass.async_block_till_done()
    return notify


def issue(hass, kind, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{kind}_{entry.entry_id}")


def test_tested_models():
    assert is_tested("smart scale P1") and is_tested(" Smart Scale p1 ")
    assert not is_tested("Health Scale X9") and not is_tested(None) and not is_tested("")


async def test_tested_scale_has_no_issue(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, persons(ALEX))
        await run_measurement(hass, client)
        assert alex(hass, "body_fat").state == "13.8"
        assert not ir.async_get(hass).issues
        assert issue(hass, "untested_model", entry) is None


async def test_untested_scale_gets_no_body_values_until_enabled(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    frames = (bf(0, (3100, 3050, 250, 2600, 2580)), bf(1, (2700, 2690, 240, 2250, 2270)), cf(0, hr=72, b2=0xC0))
    with device_patch, connect_patch:
        entry = await setup_other(hass, persons(ALEX))
        found = issue(hass, "untested_model", entry)
        assert found.translation_key == "untested_model" and found.translation_placeholders["model"] == OTHER
        await measure_other(hass, client, frames)
        # Gemessenes kommt an, Berechnetes nicht
        assert alex(hass, "weight").state == "75.0" and alex(hass, "heart_rate").state == "72"
        assert hass.states.get("sensor.health_scale_x9_impedances").state == "10"
        assert alex(hass, "body_fat").state == "unknown"
        raw = hass.states.get("sensor.health_scale_x9_raw_data").attributes
        assert "ungetestet" in raw["body_composition"]["Alex"]

        # Einstellung erscheint nur bei ungetesteten Waagen und schaltet die Berechnung ein
        flow = hass.config_entries.options
        result = await flow.async_init(entry.entry_id)
        result = await flow.async_configure(result["flow_id"], {"next_step_id": "settings"})
        assert "untested_body" in {str(key) for key in result["data_schema"].schema}
        result = await flow.async_configure(result["flow_id"], {"tolerance": 3, "untested_body": True})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert entry.options["untested_body"] is True
        # Die gemerkte Wiegung wird nach dem Neuladen nachgerechnet, sobald Daten kommen
        # Nach dem Neuladen laeuft die Sitzung wieder; die naechste Messung wird berechnet
        for _ in range(20):
            await asyncio.sleep(0)
        notify = client.callbacks["fff4"]
        for frame in (cf(1), cf(8), *frames):
            notify(None, bytearray(frame))
        await hass.async_block_till_done()
        assert alex(hass, "body_fat").state == "13.8"
        assert issue(hass, "untested_model", entry) is not None


async def test_settings_hide_switch_for_tested_scale(hass, enable_bluetooth):
    entry = await setup(hass, persons(ALEX))
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "settings"})
    assert "untested_body" not in {str(key) for key in result["data_schema"].schema}


async def test_four_electrode_frame_is_reported(hass, enable_bluetooth):
    """Impedanz im Gewichts-Frame: andere Geraetefamilie."""
    frame = bytearray(cf(8))
    frame[5:8] = b"\x10\x27\x00"
    frame[10] = 0
    for value in frame[:10]:
        frame[10] ^= value
    with connected(FakeClient())[0]:
        entry = await setup_other(hass, persons(ALEX))
        assert issue(hass, "unsupported_protocol", entry) is None
        inject_as(hass, OTHER, frame.hex())
        await hass.async_block_till_done()
        found = issue(hass, "unsupported_protocol", entry)
        assert found.translation_key == "unsupported_four_electrode"
        assert found.severity is ir.IssueSeverity.ERROR
        # Das Gewicht ist trotzdem gueltig
        assert hass.states.get("sensor.health_scale_x9_last_weighing").state == "75.0"


async def test_unknown_advertising_is_reported(hass, enable_bluetooth):
    entry = await setup_other(hass, persons(ALEX))
    for index in range(9):
        inject_as(hass, OTHER, f"a5{index:02x}112233445566778899", company=0x1A10)
    await hass.async_block_till_done()
    assert issue(hass, "unsupported_protocol", entry) is None
    inject_as(hass, OTHER, "a5ff112233445566778899", company=0x1A10)
    await hass.async_block_till_done()
    assert issue(hass, "unsupported_protocol", entry).translation_key == "unsupported_unknown_advertising"
    assert hass.states.get("sensor.health_scale_x9_last_weighing").state == "unknown"


async def test_unknown_frames_are_reported(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup_other(hass, persons(ALEX))
        await measure_other(hass, client, (b"\xa1\x02\x03\x04\x05\x06",))
        client.disconnected_callback(client)
        for _ in range(20):
            await asyncio.sleep(0)
        await hass.async_block_till_done()
        assert issue(hass, "unsupported_protocol", entry).translation_key == "unsupported_unknown_frames"
        assert alex(hass, "body_fat").state == "unknown"


async def test_repeated_missing_impedances(hass, enable_bluetooth):
    """Drei Messungen ohne Impedanzen: Hinweis; die naechste vollstaendige loescht ihn."""
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, persons(ALEX))
        device = entry.runtime_data
        for count in range(1, 4):
            assert issue(hass, "no_impedance", entry) is None
            device._last_attempt = 0
            client.callbacks.clear()
            inject(hass, IDLE)
            inject(hass, CF_MEASURING)
            for _ in range(20):
                await asyncio.sleep(0)
            notify = client.callbacks["fff4"]
            notify(None, bytearray(cf(1, raw=7500 + count)))
            notify(None, bytearray(cf(8, raw=7500 + count)))
            notify(None, bytearray(cf(0)))
            await hass.async_block_till_done()
            client.disconnected_callback(client)
            for _ in range(20):
                await asyncio.sleep(0)
            await hass.async_block_till_done()
            assert device.sessions_without_impedance == count
        assert issue(hass, "no_impedance", entry).translation_key == "no_impedance"

        device._last_attempt = 0
        client.callbacks.clear()
        inject(hass, IDLE)
        await run_measurement(hass, client)
        client.disconnected_callback(client)
        for _ in range(20):
            await asyncio.sleep(0)
        await hass.async_block_till_done()
        assert issue(hass, "no_impedance", entry) is None and device.sessions_without_impedance == 0


async def test_diagnostics_hide_address_and_names(hass, enable_bluetooth):
    client = FakeClient()
    device_patch, connect_patch = connected(client)
    with device_patch, connect_patch:
        entry = await setup(hass, persons(ALEX))
        await run_measurement(hass, client)
        data = await async_get_config_entry_diagnostics(hass, entry)
    text = str(data)
    assert ADDR not in text and MAC not in text and "Alex" not in text
    assert data["model"] == "smart scale P1" and data["tested"] is True
    assert data["integration_version"] == "0.6.0"
    assert data["measurement"]["weight_kg"] == 75.0 and len(data["measurement"]["impedances_ohm"]) == 10
    assert data["persons"] == [{"name": "**REDACTED**", "sex": "male", "height_cm": 180, "age": 35,
                                "body_state": "berechnet", "weight_kg": 75.0, "heart_rate": 72}]
    assert data["gatt_characteristics"][2] == "fff4 [notify]"
    assert any(item["src"] == "adv" and "<mac>" in item["data"] for item in data["history"])
