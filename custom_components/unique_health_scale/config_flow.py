"""Config Flow: Waage per Bluetooth finden und hinzufuegen."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, LEFU_MANUFACTURER_ID


class UniqueHealthScaleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow fuer Lefu-Waagen."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Automatisch per Bluetooth entdeckt."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Gefundene Waage bestaetigen."""
        assert self._discovery is not None
        title = self._discovery.name or self._discovery.address
        if user_input is not None:
            return self.async_create_entry(
                title=title, data={CONF_ADDRESS: self._discovery.address}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": title}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manuell aus den gerade sichtbaren Lefu-Geraeten waehlen."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered[address], data={CONF_ADDRESS: address}
            )

        current = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=False):
            if info.address in current:
                continue
            if LEFU_MANUFACTURER_ID not in info.manufacturer_data:
                continue
            self._discovered[info.address] = (
                f"{info.name or 'Lefu-Waage'} ({info.address})"
            )

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered)}
            ),
        )
