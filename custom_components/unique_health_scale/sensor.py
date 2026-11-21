"""Sensoren der Waage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .bodycomp import BODY_TYPES, SEGMENTS, BodyComposition
from .const import DOMAIN
from .device import NO_PERSONS, PersonData, ScaleDevice
from .parser import IMPEDANCE_KEYS
from .profile import person_identifier


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensoren fuer eine Waage anlegen."""
    device: ScaleDevice = entry.runtime_data
    entities: list[SensorEntity] = [
        LastWeightSensor(device),
        ImpedanceSensor(device),
        RawSensor(device),
        *(SegmentImpedanceSensor(device, key) for key in IMPEDANCE_KEYS),
    ]
    for person in device.persons.values():
        entities += [
            WeightSensor(device, person),
            HeartRateSensor(device, person),
            LastMeasurementSensor(device, person),
            *(BodySensor(device, person, description) for description in BODY_SENSORS),
        ]
    async_add_entities(entities)


class _ScaleEntity(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: ScaleDevice, key: str) -> None:
        self._device = device
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = device.device_info

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


class _PersonEntity(_ScaleEntity):
    """Sensor einer Person; haengt an deren eigenem Geraet.

    Merkt sich den Stand vor einer Wiegung, damit eine falsche Zuordnung
    zurueckgenommen werden kann.
    """

    def __init__(self, device: ScaleDevice, person: PersonData, key: str) -> None:
        super().__init__(device, key)
        self._person = person
        identifier = person_identifier(device.address, person.person.id)
        self._attr_unique_id = f"{identifier}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=person.person.name,
            manufacturer="Lefu (PAVABA)",
            model=device.name,
            via_device=(DOMAIN, device.address),
        )
        self._revert_seen = person.revert_serial
        self._undo: tuple[int, Any, dict[str, Any] | None] | None = None

    @callback
    def _handle_update(self) -> None:
        person = self._person
        if person.revert_serial != self._revert_seen:
            self._revert_seen = person.revert_serial
            if self._undo is not None and self._undo[0] == person.weighing_serial:
                _, self._attr_native_value, attributes = self._undo
                if attributes is not None:
                    self._attr_extra_state_attributes = attributes
                self._undo = None
                self._after_revert()
                self.async_write_ha_state()
            return
        attributes = getattr(self, "_attr_extra_state_attributes", None)
        before = (
            person.weighing_serial,
            self._attr_native_value,
            dict(attributes) if attributes is not None else None,
        )
        if self._update_from_device():
            if self._undo is None or self._undo[0] != person.weighing_serial:
                self._undo = before
            self.async_write_ha_state()

    def _after_revert(self) -> None:
        """Interne Merker nach dem Zuruecknehmen angleichen."""


class LastWeightSensor(_ScaleEntity, RestoreSensor):
    """Gewicht der letzten Wiegung auf der Waage, egal von wem."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_suggested_display_precision = 2

    def __init__(self, device: ScaleDevice) -> None:
        super().__init__(device, "last_weight")

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


class WeightSensor(_PersonEntity, RestoreSensor):
    """Gewicht der letzten Wiegung der Person."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_suggested_display_precision = 2

    def __init__(self, device: ScaleDevice, person: PersonData) -> None:
        super().__init__(device, person, "weight")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
            # Das letzte Gewicht entscheidet nach einem Neustart ueber die Zuordnung
            if self._person.weight_kg is None and last.native_value is not None:
                self._person.weight_kg = float(last.native_value)
        if self._update_from_device():
            self.async_write_ha_state()

    def _update_from_device(self) -> bool:
        weight = self._person.weight_kg
        if weight is None or weight == self._attr_native_value:
            return False
        self._attr_native_value = weight
        return True


class HeartRateSensor(_PersonEntity, RestoreSensor):
    """Herzfrequenz, falls die Waage sie am Ende der Messung liefert."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, device: ScaleDevice, person: PersonData) -> None:
        super().__init__(device, person, "heart_rate")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value

    def _update_from_device(self) -> bool:
        heart_rate = self._person.heart_rate
        if not heart_rate or heart_rate == self._attr_native_value:
            return False
        self._attr_native_value = heart_rate
        return True


class LastMeasurementSensor(_PersonEntity, RestoreSensor):
    """Zeitpunkt der letzten Wiegung der Person."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, device: ScaleDevice, person: PersonData) -> None:
        super().__init__(device, person, "last_measurement")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
        if self._update_from_device():
            self.async_write_ha_state()

    def _update_from_device(self) -> bool:
        measured_at = self._person.measured_at
        if measured_at is None or measured_at == self._attr_native_value:
            return False
        self._attr_native_value = measured_at
        return True


class ImpedanceSensor(_ScaleEntity):
    """Uebersicht der letzten Koerperanalyse: alle Impedanzen in Ohm als Attribute."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sine-wave"

    def __init__(self, device: ScaleDevice) -> None:
        super().__init__(device, "impedance")
        self._raw: dict[str, int] = {}
        self._ohm: dict[str, float] = {}

    def _update_from_device(self) -> bool:
        values = self._device.measurement.impedances
        if not values or values == self._raw:
            return False
        self._raw = dict(values)
        self._ohm = self._device.measurement.impedances_ohm or {}
        self._attr_native_value = sum(1 for key in IMPEDANCE_KEYS if values.get(key))
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self._ohm,
            "weight_kg": self._device.measurement.weight_kg,
            "complete": bool(self._ohm),
            "raw": self._raw,
        }


class SegmentImpedanceSensor(_ScaleEntity, RestoreSensor):
    """Impedanz eines Koerpersegments bei 20 oder 100 kHz in Ohm."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "Ω"
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:sine-wave"

    def __init__(self, device: ScaleDevice, key: str) -> None:
        super().__init__(device, key)
        self._key = key

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value

    def _update_from_device(self) -> bool:
        ohm = self._device.measurement.impedances_ohm
        if ohm is None or ohm[self._key] == self._attr_native_value:
            return False
        self._attr_native_value = ohm[self._key]
        return True


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
            "assignment": self._device.assignment_state,
            "body_composition": {
                data.person.name: data.body_state for data in self._device.persons.values()
            }
            or NO_PERSONS,
            "gatt_characteristics": self._device.gatt_characteristics,
            "history": list(self._device.history),
        }


# ---------------------------------------------------------------------------
# Berechnete Koerperwerte
# ---------------------------------------------------------------------------

RATINGS = ("low", "normal", "high")
BALANCE = ("balanced", "slightly_unbalanced", "unbalanced")


@dataclass(frozen=True, kw_only=True)
class BodySensorDescription(SensorEntityDescription):
    """Ein berechneter Wert samt Zusatzangaben fuer die Attribute."""

    value: Callable[[BodyComposition], Any]
    attributes: Callable[[BodyComposition], dict[str, Any]] | None = None


def _rated(key: str) -> Callable[[BodyComposition], dict[str, Any]]:
    """Referenzbereich und Einstufung eines Werts als Attribute."""

    def attributes(body: BodyComposition) -> dict[str, Any]:
        low, high = body.ranges[key]
        return {"normal_min": low, "normal_max": high, "rating": RATINGS[body.levels[key]]}

    return attributes


def _with_balance(key: str, prefix: str, pairs: tuple[str, ...]):
    rated = _rated(key)

    def attributes(body: BodyComposition) -> dict[str, Any]:
        return {
            **rated(body),
            **{f"balance_{pair}": BALANCE[body.balance[f"{prefix}_{pair}"]] for pair in pairs},
        }

    return attributes


def _mass(key: str, *, rated: bool = True, icon: str | None = None, attributes=None) -> BodySensorDescription:
    return BodySensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon=icon,
        value=lambda body: getattr(body, key),
        attributes=attributes or (_rated(key) if rated else None),
    )


def _percent(key: str, *, rated: bool = False, icon: str | None = None) -> BodySensorDescription:
    return BodySensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon=icon,
        value=lambda body: getattr(body, key),
        attributes=_rated(key) if rated else None,
    )


def _number(
    key: str,
    *,
    unit: str | None = None,
    precision: int = 0,
    rated: bool = False,
    icon: str | None = None,
) -> BodySensorDescription:
    return BodySensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision,
        icon=icon,
        value=lambda body: getattr(body, key),
        attributes=_rated(key) if rated else None,
    )


def _segment(kind: str, segment: str) -> BodySensorDescription:
    """Fett- bzw. Muskelmasse eines Segments; Normwert-Anteil als Attribut."""
    return BodySensorDescription(
        key=f"{kind}_{segment}",
        translation_key=f"{kind}_{segment}",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:human",
        value=lambda body: getattr(body, f"segment_{kind}_kg")[segment],
        attributes=lambda body: {
            "percent_of_reference": getattr(body, f"segment_{kind}_percent")[segment],
            "rating": RATINGS[getattr(body, f"segment_{kind}_level")[segment]],
        },
    )


BODY_SENSORS: tuple[BodySensorDescription, ...] = (
    _number("bmi", unit="kg/m²", precision=1, rated=True, icon="mdi:human-male-height"),
    _percent("body_fat_percent", rated=True, icon="mdi:percent"),
    _mass("body_fat_kg", attributes=_with_balance("body_fat_kg", "fat", ("arms", "legs"))),
    _mass("fat_free_mass_kg"),
    _mass(
        "muscle_kg",
        icon="mdi:arm-flex",
        attributes=_with_balance("muscle_kg", "muscle", ("arms", "legs", "arms_vs_legs")),
    ),
    _percent("muscle_percent", icon="mdi:arm-flex"),
    _mass("skeletal_muscle_kg", icon="mdi:arm-flex"),
    _percent("skeletal_muscle_percent", icon="mdi:arm-flex"),
    _mass("water_kg", icon="mdi:water"),
    _percent("water_percent", icon="mdi:water-percent"),
    _mass("intracellular_water_kg", icon="mdi:water"),
    _mass("extracellular_water_kg", icon="mdi:water-outline"),
    _mass("protein_kg", icon="mdi:molecule"),
    _percent("protein_percent", icon="mdi:molecule"),
    _mass("mineral_kg", icon="mdi:diamond-stone"),
    _mass("bone_kg", icon="mdi:bone"),
    _mass("body_cell_mass_kg", icon="mdi:dots-hexagon"),
    _mass("subcutaneous_fat_kg"),
    _percent("subcutaneous_fat_percent", rated=True),
    _number("visceral_fat", rated=True, icon="mdi:stomach"),
    _number("waist_hip_ratio", precision=2, rated=True, icon="mdi:tape-measure"),
    _number("skeletal_muscle_index", unit="kg/m²", precision=1, icon="mdi:arm-flex"),
    _number("basal_metabolic_rate", unit="kcal", rated=True, icon="mdi:fire"),
    _number("daily_calorie_intake", unit="kcal", icon="mdi:food-apple"),
    _number("body_score", icon="mdi:star-circle"),
    _number("body_age", icon="mdi:account-clock"),
    _number("obesity_percent", unit=PERCENTAGE, rated=True, icon="mdi:scale-bathroom"),
    BodySensorDescription(
        key="body_type",
        translation_key="body_type",
        device_class=SensorDeviceClass.ENUM,
        options=list(BODY_TYPES.values()),
        icon="mdi:human",
        value=lambda body: BODY_TYPES.get(body.body_type),
    ),
    _mass("ideal_weight_kg", rated=False, icon="mdi:target"),
    _mass("target_weight_kg", rated=False, icon="mdi:target"),
    _number("weight_control_kg", unit=UnitOfMass.KILOGRAMS, precision=1, icon="mdi:plus-minus"),
    _number("fat_control_kg", unit=UnitOfMass.KILOGRAMS, precision=1, icon="mdi:plus-minus"),
    _number("muscle_control_kg", unit=UnitOfMass.KILOGRAMS, precision=1, icon="mdi:plus-minus"),
    *(_segment(kind, segment) for kind in ("fat", "muscle") for segment in SEGMENTS),
)


class BodySensor(_PersonEntity, RestoreSensor):
    """Ein aus Gewicht, Impedanzen und Profil berechneter Koerperwert."""

    entity_description: BodySensorDescription

    def __init__(
        self, device: ScaleDevice, person: PersonData, description: BodySensorDescription
    ) -> None:
        super().__init__(device, person, description.key)
        self.entity_description = description
        self._serial = person.body_serial
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
        if (state := await self.async_get_last_state()) is not None:
            self._attr_extra_state_attributes = {
                key: value
                for key, value in state.attributes.items()
                if key in ("normal_min", "normal_max", "rating", "percent_of_reference")
                or key.startswith("balance_")
            }
        # Falls die Messung schon vor dem Anlegen der Sensoren fertig war
        self._serial = -1
        self._update_from_device()

    def _after_revert(self) -> None:
        self._serial = self._person.body_serial

    def _update_from_device(self) -> bool:
        body = self._person.body
        if body is None or self._serial == self._person.body_serial:
            return False
        self._serial = self._person.body_serial
        description = self.entity_description
        self._attr_native_value = description.value(body)
        if description.attributes is not None:
            self._attr_extra_state_attributes = description.attributes(body)
        return True
