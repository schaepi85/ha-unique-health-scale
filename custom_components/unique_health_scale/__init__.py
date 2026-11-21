"""Unique Health Scale (Lefu) – lokale Home-Assistant-Integration."""

from __future__ import annotations

import logging
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    CONF_AGE,
    CONF_BIRTHDAY,
    CONF_HEIGHT,
    CONF_ID,
    CONF_NAME,
    CONF_PERSONS,
    CONF_SEX,
    DOMAIN,
)
from . import compat
from .device import ScaleDevice
from .parser import IMPEDANCE_KEYS
from .profile import Profile, person_identifier

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SELECT, Platform.SENSOR]

type ScaleConfigEntry = ConfigEntry[ScaleDevice]

# Sensoren, die auch ab Version 2 an der Waage selbst haengen
_SCALE_KEYS = ("impedance", "raw_frame", *IMPEDANCE_KEYS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Version 1 (ein Profil pro Waage) auf Version 2 (Personen) umstellen.

    Aus dem bisherigen Profil wird die erste Person. Ihre Sensoren behalten
    Entity-ID und Verlauf: In der Registry aendert sich nur die eindeutige ID,
    das Geraet der Person uebernimmt den Bereich der Waage.
    """
    if entry.version > 2:
        return False
    if entry.version == 2:
        return True

    address: str = entry.data[CONF_ADDRESS]
    prefix = f"{address}_"
    entity_registry = er.async_get(hass)
    persons: list[dict] = []

    if Profile.from_options(entry.options) is not None:
        person_id = uuid4().hex[:8]
        name = "Person 1"
        persons.append(
            {
                CONF_ID: person_id,
                CONF_NAME: name,
                **{
                    key: entry.options[key]
                    for key in (CONF_SEX, CONF_HEIGHT, CONF_BIRTHDAY, CONF_AGE)
                    if key in entry.options
                },
            }
        )
        device_registry = dr.async_get(hass)
        scale = device_registry.async_get_device(identifiers={(DOMAIN, address)})
        person_device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, person_identifier(address, person_id))},
            name=name,
            manufacturer="Lefu (PAVABA)",
        )
        if scale is not None and scale.area_id:
            device_registry.async_update_device(person_device.id, area_id=scale.area_id)

        @callback
        def _to_person(entity: er.RegistryEntry) -> dict | None:
            key = entity.unique_id.removeprefix(prefix)
            if not entity.unique_id.startswith(prefix) or key in _SCALE_KEYS:
                return None
            return {
                "new_unique_id": f"{person_identifier(address, person_id)}_{key}",
                "device_id": person_device.id,
            }

        await er.async_migrate_entries(hass, entry.entry_id, _to_person)
    else:
        # Ohne Profil gab es nur das Gewicht: Es bleibt als "Letzte Wiegung"
        # an der Waage, die leeren Koerperwert-Sensoren entfallen.
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            key = entity.unique_id.removeprefix(prefix)
            if not entity.unique_id.startswith(prefix) or key in _SCALE_KEYS:
                continue
            if key == "weight":
                entity_registry.async_update_entity(
                    entity.entity_id, new_unique_id=f"{prefix}last_weight"
                )
            else:
                entity_registry.async_remove(entity.entity_id)

    hass.config_entries.async_update_entry(entry, options={CONF_PERSONS: persons}, version=2)
    _LOGGER.info("Eintrag %s auf Version 2 umgestellt (%d Person)", entry.title, len(persons))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ScaleConfigEntry) -> bool:
    """Integration fuer eine Waage einrichten."""
    device = ScaleDevice(hass, entry, entry.data[CONF_ADDRESS])
    entry.runtime_data = device
    _async_remove_stale_devices(hass, entry, device)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_link_person_devices(hass, device)
    entry.async_on_unload(device.async_start())
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


@callback
def _async_remove_stale_devices(
    hass: HomeAssistant, entry: ScaleConfigEntry, device: ScaleDevice
) -> None:
    """Geraete (samt Sensoren) entfernter Personen loeschen."""
    valid = {(DOMAIN, device.address)} | {
        (DOMAIN, person_identifier(device.address, person_id)) for person_id in device.persons
    }
    device_registry = dr.async_get(hass)
    for entity_device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if not entity_device.identifiers & valid:
            device_registry.async_update_device(
                entity_device.id, remove_config_entry_id=entry.entry_id
            )


@callback
def _async_link_person_devices(hass: HomeAssistant, device: ScaleDevice) -> None:
    """Geraete der Personen unter die Waage haengen.

    Bewusst ueber die Geraete-ID: Die Angabe `via_device` beim Anlegen ist in
    neueren Home-Assistant-Versionen abgekuendigt und laesst dort z. B. das
    Umbenennen einer Entitaet scheitern.
    """
    device_registry = dr.async_get(hass)
    scale = device_registry.async_get_device(identifiers={(DOMAIN, device.address)})
    if scale is None:
        return
    for person_id in device.persons:
        person_device = device_registry.async_get_device(
            identifiers={(DOMAIN, person_identifier(device.address, person_id))}
        )
        if person_device is not None and person_device.via_device_id != scale.id:
            device_registry.async_update_device(person_device.id, via_device_id=scale.id)


async def _async_reload(hass: HomeAssistant, entry: ScaleConfigEntry) -> None:
    """Geaenderte Personen und Einstellungen uebernehmen."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ScaleConfigEntry) -> bool:
    """Integration entladen."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ScaleConfigEntry) -> None:
    """Gemerkte letzte Wiegung und Hinweise unter Reparaturen verwerfen."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    compat.async_clear_all(hass, entry.entry_id)
