"""Unique Health Scale (Lefu) – lokale Home-Assistant-Integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .device import ScaleDevice

PLATFORMS: list[Platform] = [Platform.SENSOR]

type ScaleConfigEntry = ConfigEntry[ScaleDevice]


async def async_setup_entry(hass: HomeAssistant, entry: ScaleConfigEntry) -> bool:
    """Integration fuer eine Waage einrichten."""
    device = ScaleDevice(hass, entry, entry.data[CONF_ADDRESS])
    entry.runtime_data = device
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(device.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ScaleConfigEntry) -> bool:
    """Integration entladen."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
