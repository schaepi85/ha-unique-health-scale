"""Sensoren der Waage."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import ScaleDevice
from .parser import IMPEDANCE_KEYS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensoren fuer eine Waage anlegen."""
    device: ScaleDevice = entry.runtime_data
    async_add_entities(
        [
            WeightSensor(device),
            HeartRateSensor(device),
            ImpedanceSensor(device),
            RawSensor(device),
        ]
    )


class _ScaleEntity(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: ScaleDevice, key: str) -> None:
        self._device = device
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            connections={(CONNECTION_BLUETOOTH, device.address)},
            name=device.name,
            manufacturer="Lefu (PAVABA)",
            model="8-Elektroden-Koerperfettwaage",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._device.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        if self._update_from_device():
            self.async_write_ha_state()

    def _update_from_device(self) -> bool:
        """Werte uebernehmen; True, wenn der Zustand geschrieben werden soll."""
        raise NotImplementedError


class WeightSensor(_ScaleEntity, RestoreSensor):
    """Gewicht der letzten Messung, sobald es auf der Waage feststeht."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_suggested_display_precision = 2

    def __init__(self, device: ScaleDevice) -> None:
        super().__init__(device, "weight")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value

    def _update_from_device(self) -> bool:
        weight = self._device.measurement.weight_kg
        if weight is None or weight == self._attr_native_value:
            return False
        self._attr_native_value = weight
        return True


class HeartRateSensor(_ScaleEntity):
    """Herzfrequenz, falls die Waage sie am Ende der Messung liefert."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, device: ScaleDevice) -> None:
        super().__init__(device, "heart_rate")

    def _update_from_device(self) -> bool:
        heart_rate = self._device.measurement.heart_rate
        if not heart_rate or heart_rate == self._attr_native_value:
            return False
        self._attr_native_value = heart_rate
        return True


class ImpedanceSensor(_ScaleEntity):
    """Kodierte Segment-Impedanzen (20/100 kHz) der letzten Koerperanalyse."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sine-wave"

    def __init__(self, device: ScaleDevice) -> None:
        super().__init__(device, "impedance")
        self._values: dict[str, int] = {}

    def _update_from_device(self) -> bool:
        values = self._device.measurement.impedances
        if not values or values == self._values:
            return False
        self._values = dict(values)
        self._attr_native_value = sum(1 for key in IMPEDANCE_KEYS if values.get(key))
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self._values,
            "weight_kg": self._device.measurement.weight_kg,
            "complete": len(self._values) == len(IMPEDANCE_KEYS),
        }


class RawSensor(_ScaleEntity):
    """Rohdaten (Advertising und FFF4) fuer die Protokollanalyse."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: ScaleDevice) -> None:
        super().__init__(device, "raw_frame")

    def _update_from_device(self) -> bool:
        raw = self._device.last_raw
        self._attr_native_value = raw[:255] if raw else None
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self._device.last_info
        return {
            "name": info.name if info else None,
            "rssi": info.rssi if info else None,
            "service_uuids": list(info.service_uuids) if info else [],
            "session": self._device.session_state,
            "status": self._device.measurement.status,
            "live_weight_kg": self._device.measurement.live_weight_kg,
            "gatt_characteristics": self._device.gatt_characteristics,
            "history": list(self._device.history),
        }
