"""Config Flow: Waage per Bluetooth finden und hinzufuegen."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

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
    CONF_ID,
    CONF_NAME,
    CONF_NOTIFY,
    CONF_PERSONS,
    CONF_REFERENCE_WEIGHT,
    CONF_SEX,
    CONF_TOLERANCE,
    CONF_UNTESTED_BODY,
    DEFAULT_TOLERANCE_KG,
    DOMAIN,
    UNASSIGNED,
    LEFU_MANUFACTURER_ID,
    LEFU_SERVICE_UUID,
)
from .parser import CF_LENGTH

PROFILE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
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
        vol.Optional(CONF_REFERENCE_WEIGHT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=250, step=0.1, unit_of_measurement="kg", mode=selector.NumberSelectorMode.BOX
            )
        ),
    }
)


def _clean_person(
    user_input: dict[str, Any], taken_names: set[str]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Eingabe normalisieren; liefert (Person ohne ID, Fehler)."""
    name = str(user_input[CONF_NAME]).strip()
    person: dict[str, Any] = {
        CONF_NAME: name,
        CONF_SEX: user_input[CONF_SEX],
        CONF_HEIGHT: int(user_input[CONF_HEIGHT]),
    }
    if user_input.get(CONF_REFERENCE_WEIGHT):
        person[CONF_REFERENCE_WEIGHT] = float(user_input[CONF_REFERENCE_WEIGHT])
    if not name or name == UNASSIGNED:
        return person, {CONF_NAME: "name_required"}
    if name.casefold() in taken_names:
        return person, {CONF_NAME: "name_exists"}
    if user_input.get(CONF_BIRTHDAY):
        person[CONF_BIRTHDAY] = user_input[CONF_BIRTHDAY]
    elif user_input.get(CONF_AGE):
        person[CONF_AGE] = int(user_input[CONF_AGE])
    else:
        return person, {"base": "age_required"}
    return person, {}


def _new_id() -> str:
    return uuid4().hex[:8]


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

    VERSION = 2

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, str] = {}
        self._title = ""
        self._address = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PersonsOptionsFlow:
        """Personen und Einstellungen nachtraeglich aendern."""
        return PersonsOptionsFlow()

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
        """Erste Person abfragen; weitere kommen spaeter ueber "Konfigurieren" dazu."""
        errors: dict[str, str] = {}
        if user_input is not None:
            person, errors = _clean_person(user_input, set())
            if not errors:
                return self.async_create_entry(
                    title=self._title,
                    data={CONF_ADDRESS: self._address},
                    options={CONF_PERSONS: [{CONF_ID: _new_id(), **person}]},
                )
        return self.async_show_form(
            step_id="profile",
            data_schema=self.add_suggested_values_to_schema(PROFILE_SCHEMA, user_input or {}),
            errors=errors,
        )


class PersonsOptionsFlow(OptionsFlow):
    """Personen hinzufuegen, bearbeiten, entfernen; Zuordnung einstellen."""

    def __init__(self) -> None:
        self._edit_id: str | None = None

    @property
    def _persons(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_PERSONS, []))

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    def _person_selector(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=person[CONF_ID], label=person[CONF_NAME])
                            for person in self._persons
                        ]
                    )
                )
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["add_person"]
        if self._persons:
            options += ["edit_person", "remove_person"]
        return self.async_show_menu(step_id="init", menu_options=[*options, "settings"])

    async def async_step_add_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            taken = {person[CONF_NAME].casefold() for person in self._persons}
            person, errors = _clean_person(user_input, taken)
            if not errors:
                return self._save(**{CONF_PERSONS: [*self._persons, {CONF_ID: _new_id(), **person}]})
        return self.async_show_form(
            step_id="add_person",
            data_schema=self.add_suggested_values_to_schema(PROFILE_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_edit_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Person waehlen, die bearbeitet werden soll."""
        if user_input is not None:
            self._edit_id = user_input[CONF_ID]
            return await self.async_step_person()
        if len(self._persons) == 1:
            self._edit_id = self._persons[0][CONF_ID]
            return await self.async_step_person()
        return self.async_show_form(step_id="edit_person", data_schema=self._person_selector())

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Gewaehlte Person bearbeiten."""
        current = next(person for person in self._persons if person[CONF_ID] == self._edit_id)
        errors: dict[str, str] = {}
        if user_input is not None:
            taken = {
                person[CONF_NAME].casefold()
                for person in self._persons
                if person[CONF_ID] != self._edit_id
            }
            changed, errors = _clean_person(user_input, taken)
            if not errors:
                persons = [
                    {CONF_ID: self._edit_id, **changed} if person[CONF_ID] == self._edit_id else person
                    for person in self._persons
                ]
                return self._save(**{CONF_PERSONS: persons})
        return self.async_show_form(
            step_id="person",
            data_schema=self.add_suggested_values_to_schema(PROFILE_SCHEMA, user_input or current),
            errors=errors,
            description_placeholders={"name": current[CONF_NAME]},
        )

    async def async_step_remove_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Person samt ihren Sensoren entfernen."""
        if user_input is not None:
            persons = [person for person in self._persons if person[CONF_ID] != user_input[CONF_ID]]
            return self._save(**{CONF_PERSONS: persons})
        return self.async_show_form(step_id="remove_person", data_schema=self._person_selector())

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Toleranz der automatischen Zuordnung und Rueckfrage aufs Handy."""
        untested = not getattr(
            getattr(self.config_entry, "runtime_data", None), "tested", True
        )
        if user_input is not None:
            changes: dict[str, Any] = {
                CONF_TOLERANCE: float(user_input[CONF_TOLERANCE]),
                CONF_NOTIFY: list(user_input.get(CONF_NOTIFY, [])),
            }
            if untested:
                changes[CONF_UNTESTED_BODY] = bool(user_input.get(CONF_UNTESTED_BODY, False))
            return self._save(**changes)
        services = sorted(
            service
            for service in self.hass.services.async_services().get("notify", {})
            if service.startswith("mobile_app_")
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_TOLERANCE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=10, step=0.5, unit_of_measurement="kg",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_NOTIFY): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=services, multiple=True, custom_value=True)
                ),
            }
        )
        if untested:
            # Nur bei ungetesteten Waagen: Koerperwerte auf eigene Verantwortung
            schema = schema.extend({vol.Optional(CONF_UNTESTED_BODY): selector.BooleanSelector()})
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_TOLERANCE: self.config_entry.options.get(CONF_TOLERANCE, DEFAULT_TOLERANCE_KG),
                    CONF_NOTIFY: self.config_entry.options.get(CONF_NOTIFY, []),
                    CONF_UNTESTED_BODY: self.config_entry.options.get(CONF_UNTESTED_BODY, False),
                },
            ),
        )
