"""Sensoren: Gewicht (sobald dekodiert) und Rohdaten fuer die Analyse."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, RAW_HISTORY_SIZE
from .parser import parse_advertisement

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensoren fuer eine Waage anlegen."""
    address: str = entry.data[CONF_ADDRESS]
    device_info = DeviceInfo(
        identifiers={(DOMAIN, address)},
        connections={(CONNECTION_BLUETOOTH, address)},
        name=entry.title,
        manufacturer="Lefu (PAVABA)",
        model="8-Elektroden-Koerperfettwaage",
    )
    raw = RawAdvertisementSensor(address, device_info)
    weight = WeightSensor(address, device_info)
    async_add_entities([weight, raw])

    @callback
    def _on_advertisement(
        info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        frame = {
            "manufacturer_data": {
                f"0x{cid:04X}": data.hex()
                for cid, data in info.manufacturer_data.items()
            },
            "service_data": {
                uuid: data.hex() for uuid, data in info.service_data.items()
            },
        }
        if not frame["manufacturer_data"] and not frame["service_data"]:
            return
        _LOGGER.debug(
            "Frame von %s (%s, RSSI %s): %s", address, info.name, info.rssi, frame
        )
        raw.handle_frame(frame, info)
        reading = parse_advertisement(
            info.name, dict(info.manufacturer_data), dict(info.service_data)
        )
        if reading and reading.stable and reading.weight_kg is not None:
            weight.handle_weight(reading.weight_kg)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _on_advertisement,
            {"address": address, "connectable": False},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )


class _ScaleEntity(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, address: str, device_info: DeviceInfo, key: str) -> None:
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = device_info
        self._attr_translation_key = key


class WeightSensor(_ScaleEntity):
    """Gewicht der letzten stabilen Messung."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_suggested_display_precision = 1

    def __init__(self, address: str, device_info: DeviceInfo) -> None:
        super().__init__(address, device_info, "weight")

    @callback
    def handle_weight(self, value: float) -> None:
        self._attr_native_value = round(value, 2)
        self.async_write_ha_state()


class RawAdvertisementSensor(_ScaleEntity):
    """Letzter Roh-Frame (alle Hersteller- und Service-Daten) fuer die Protokollanalyse."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, address: str, device_info: DeviceInfo) -> None:
        super().__init__(address, device_info, "raw_frame")
        self._history: deque[dict[str, Any]] = deque(maxlen=RAW_HISTORY_SIZE)
        self._last_info: bluetooth.BluetoothServiceInfoBleak | None = None

    @callback
    def handle_frame(
        self, frame: dict[str, dict[str, str]], info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        if self._history and self._history[-1]["frame"] == frame:
            return
        self._last_info = info
        self._history.append(
            {"time": datetime.now(timezone.utc).isoformat(), "frame": frame}
        )
        summary = " ".join(
            f"{cid}:{data}" for cid, data in frame["manufacturer_data"].items()
        ) or " ".join(f"{u[4:8]}:{d}" for u, d in frame["service_data"].items())
        self._attr_native_value = summary[:255]
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self._last_info
        return {
            "name": info.name if info else None,
            "rssi": info.rssi if info else None,
            "service_uuids": list(info.service_uuids) if info else [],
            "history": list(self._history),
        }
