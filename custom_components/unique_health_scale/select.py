"""Zuordnung der letzten Wiegung zu einer Person."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import UNASSIGNED
from .device import ScaleDevice


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Auswahl anlegen, sobald Personen hinterlegt sind."""
    device: ScaleDevice = entry.runtime_data
    if device.persons:
        async_add_entities([AssignSelect(device)])


class AssignSelect(SelectEntity):
    """Zeigt, wem die letzte Wiegung gehoert, und laesst sie umhaengen."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "assign"
    _attr_icon = "mdi:account-question"

    def __init__(self, device: ScaleDevice) -> None:
        self._device = device
        self._attr_unique_id = f"{device.address}_assign"
        self._attr_device_info = device.device_info
        self._ids = {data.person.name: key for key, data in device.persons.items()}
        self._attr_options = [*self._ids, UNASSIGNED]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._device.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        weighing = self._device.weighing
        if weighing is None:
            return None
        if weighing.person_id is None:
            return UNASSIGNED
        return self._device.persons[weighing.person_id].person.name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        weighing = self._device.weighing
        if weighing is None:
            return {}
        return {
            "weight_kg": weighing.weight_kg,
            "time": weighing.time.isoformat(),
            "candidates": [
                self._device.persons[person_id].person.name
                for person_id in weighing.candidates
                if person_id in self._device.persons
            ],
        }

    async def async_select_option(self, option: str) -> None:
        self._device.async_assign(self._ids.get(option))
