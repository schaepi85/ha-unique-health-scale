"""Diagnose-Daten fuer Fehler- und Testberichte.

Abrufbar ueber Einstellungen -> Geraete & Dienste -> Unique Health Scale ->
drei Punkte -> "Diagnose herunterladen". Bluetooth-Adresse, Namen und
Geburtsdaten werden unkenntlich gemacht; Messwerte bleiben enthalten, weil
sie fuer die Fehlersuche gebraucht werden.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from . import ScaleConfigEntry, compat
from .const import CONF_PERSONS, CONF_TOLERANCE, CONF_UNTESTED_BODY

REDACTED = "**REDACTED**"


def _hide_address(text: str, address: str) -> str:
    """Bluetooth-Adresse in beliebiger Schreibweise aus einem Text entfernen."""
    plain = address.replace(":", "").lower()
    for variant in (address, address.lower(), plain, plain.upper()):
        text = text.replace(variant, "<mac>")
    return text


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ScaleConfigEntry
) -> dict[str, Any]:
    """Zustand der Waage fuer einen Bericht zusammenstellen."""
    device = entry.runtime_data
    info = device.last_info
    measurement = device.measurement

    advertisement: dict[str, Any] | None = None
    if info is not None:
        advertisement = {
            "name": info.name,
            "rssi": info.rssi,
            "source": _hide_address(str(info.source), device.address),
            "connectable": info.connectable,
            "service_uuids": list(info.service_uuids),
            "manufacturer_data": {
                f"0x{company:04X}": _hide_address(data.hex(), device.address)
                for company, data in info.manufacturer_data.items()
            },
            "service_data": {
                uuid: _hide_address(data.hex(), device.address)
                for uuid, data in info.service_data.items()
            },
        }

    integration = await async_get_integration(hass, entry.domain)
    today = dt_util.now().date()

    return {
        "integration_version": str(integration.version),
        "model": device.model,
        "tested": device.tested,
        "protocol_problem": device.protocol_problem,
        "sessions_without_impedance": device.sessions_without_impedance,
        "no_impedance_limit": compat.NO_IMPEDANCE_LIMIT,
        "options": {
            "persons": len(entry.options.get(CONF_PERSONS, [])),
            "tolerance": entry.options.get(CONF_TOLERANCE),
            "untested_body": entry.options.get(CONF_UNTESTED_BODY, False),
        },
        "persons": [
            {
                "name": REDACTED,
                "sex": data.person.profile.sex.name.lower(),
                "height_cm": data.person.profile.height_cm,
                "age": data.person.profile.age_on(today),
                "body_state": data.body_state.replace(data.person.name, REDACTED),
                "weight_kg": data.weight_kg,
                "heart_rate": data.heart_rate,
            }
            for data in device.persons.values()
        ],
        "advertisement": advertisement,
        "session": device.session_state,
        "connected": device.connected,
        "gatt_characteristics": device.gatt_characteristics,
        "measurement": {
            "status": measurement.status,
            "weight_kg": measurement.weight_kg,
            "heart_rate": measurement.heart_rate,
            "impedances_raw": dict(measurement.impedances),
            "impedances_ohm": measurement.impedances_ohm,
            "complete": measurement.complete,
        },
        "history": [
            {**item, "data": _hide_address(item["data"], device.address)}
            for item in device.history
        ],
    }

