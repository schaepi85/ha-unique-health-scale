"""Config Flow: Waage per Bluetooth finden und hinzufuegen."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AGE,
    CONF_BIRTHDAY,
    CONF_HEIGHT,
    CONF_SEX,
    DOMAIN,
    LEFU_MANUFACTURER_ID,
    LEFU_SERVICE_UUID,
)
from .parser import CF_LENGTH

PROFILE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SEX): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["male", "female"], translation_key=CONF_SEX
            )
        ),
        vol.Required(CONF_HEIGHT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=90, max=220, step=1, unit_of_measurement="cm", mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(CONF_BIRTHDAY): selector.DateSelector(),
        vol.Optional(CONF_AGE): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=6, max=99, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
    }
)


def _clean_profile(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Eingabe normalisieren; liefert (Profil, Fehler)."""
    profile: dict[str, Any] = {
        CONF_SEX: user_input[CONF_SEX],
        CONF_HEIGHT: int(user_input[CONF_HEIGHT]),
    }
    if user_input.get(CONF_BIRTHDAY):
        profile[CONF_BIRTHDAY] = user_input[CONF_BIRTHDAY]
    elif user_input.get(CONF_AGE):
        profile[CONF_AGE] = int(user_input[CONF_AGE])
    else:
        return profile, {"base": "age_required"}
    return profile, {}


def _looks_like_lefu(info: BluetoothServiceInfoBleak) -> bool:
    """Lefu-Kennung, Dienst FFF0 oder das typische 6+11-Byte-Herstellerfeld."""
    return (
        LEFU_MANUFACTURER_ID in info.manufacturer_data
        or LEFU_SERVICE_UUID in info.service_uuids
        or any(
            len(data) == 6 + CF_LENGTH and data[6] in (0x00, 0xCF)
            for data in info.manufacturer_data.values()
        )
    )


class UniqueHealthScaleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow fuer Lefu-Waagen."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, str] = {}
        self._title = ""
        self._address = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ProfileOptionsFlow:
        """Profil nachtraeglich aendern."""
        return ProfileOptionsFlow()

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
            self._title, self._address = title, self._discovery.address
            return await self.async_step_profile()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": title}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manuell aus den gerade sichtbaren Bluetooth-Geraeten waehlen."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._title = self._discovered[address].split(" (")[0].removesuffix(" [Lefu]")
            self._address = address
            return await self.async_step_profile()

        current = self._async_current_ids()
        infos = sorted(
            async_discovered_service_info(self.hass, connectable=False),
            key=lambda info: (not _looks_like_lefu(info), -(info.rssi or -999)),
        )
        for info in infos:
            if info.address in current:
                continue
            is_lefu = _looks_like_lefu(info)
            if not is_lefu and not info.name:
                continue
            marker = " [Lefu]" if is_lefu else ""
            self._discovered[info.address] = (
                f"{info.name or 'Unbekannt'}{marker} ({info.address}, {info.rssi} dBm)"
            )

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered)}
            ),
        )

    async def async_step_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Profil der Person abfragen (fuer die berechneten Koerperwerte)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            profile, errors = _clean_profile(user_input)
            if not errors:
                return self.async_create_entry(
                    title=self._title,
                    data={CONF_ADDRESS: self._address},
                    options=profile,
                )
        return self.async_show_form(
            step_id="profile",
            data_schema=self.add_suggested_values_to_schema(PROFILE_SCHEMA, user_input or {}),
            errors=errors,
        )


class ProfileOptionsFlow(OptionsFlow):
    """Geschlecht, Groesse und Alter aendern."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            profile, errors = _clean_profile(user_input)
            if not errors:
                return self.async_create_entry(data=profile)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                PROFILE_SCHEMA, user_input or self.config_entry.options
            ),
            errors=errors,
        )
