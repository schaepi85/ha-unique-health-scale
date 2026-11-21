"""Laufzeitobjekt einer Waage: Advertising auswerten, verbinden, FFF4 mitlesen."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
import logging
import time
from typing import Any

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from homeassistant.util import dt as dt_util

from .bodycomp import SEGMENTS, BodyComposition, BodyCompositionError, compute
from .assign import match_person
from . import compat
from .const import (
    CONF_NOTIFY,
    CONF_TOLERANCE,
    CONF_UNTESTED_BODY,
    CONNECT_COOLDOWN,
    DEFAULT_TOLERANCE_KG,
    DOMAIN,
    EVENT_MOBILE_ACTION,
    LEFU_SERVICE_UUID,
    NOTIFY_CHARS,
    RAW_HISTORY_SIZE,
    SESSION_TIMEOUT,
)
from .parser import ACTIVE_STATES, LOCKED_STATES, Measurement, Status, find_cf_frame
from .profile import Person, persons_from_options

_LOGGER = logging.getLogger(__name__)

NO_PERSONS = "keine Person hinterlegt"

TEXTS = {
    "de": {
        "title": "Waage: Wer hat sich gewogen?",
        "message": (
            "Die Wiegung mit {weight} kg auf „{scale}“ konnte keiner Person eindeutig"
            " zugeordnet werden. Bitte beim Gerät „{scale}“ unter „Letzte Wiegung"
            " zuordnen“ die Person auswählen. In Frage kommen: {candidates}."
        ),
        "mobile": "{weight} kg auf „{scale}“: Wer war das?",
    },
    "en": {
        "title": "Scale: who was weighed?",
        "message": (
            "The weighing of {weight} kg on “{scale}” could not be assigned to a"
            " person. Please pick the person under “Assign last weighing” on the"
            " device “{scale}”. Candidates: {candidates}."
        ),
        "mobile": "{weight} kg on “{scale}”: who was that?",
    },
}


@dataclass
class PersonSnapshot:
    """Stand einer Person vor einer Wiegung, um eine Fehlzuordnung zurueckzunehmen."""

    weight_kg: float | None
    heart_rate: int | None
    measured_at: datetime | None
    body: BodyComposition | None
    body_state: str


@dataclass
class PersonData:
    """Letzte Werte einer Person; versorgt deren Sensoren."""

    person: Person
    weight_kg: float | None = None
    heart_rate: int | None = None
    measured_at: datetime | None = None
    body: BodyComposition | None = None
    body_state: str = "wartet auf Messung"
    body_serial: int = 0
    # Zaehlt die zugeordneten Wiegungen bzw. die zurueckgenommenen Zuordnungen
    weighing_serial: int = 0
    revert_serial: int = 0
    body_input: tuple[Any, ...] | None = None

    @property
    def reference_weight_kg(self) -> float | None:
        """Vergleichsgewicht fuer die Zuordnung: letztes Gewicht, sonst die Angabe im Profil."""
        return self.weight_kg or self.person.reference_weight_kg

    def snapshot(self) -> PersonSnapshot:
        return PersonSnapshot(
            self.weight_kg, self.heart_rate, self.measured_at, self.body, self.body_state
        )

    def restore(self, snapshot: PersonSnapshot) -> None:
        self.weight_kg = snapshot.weight_kg
        self.heart_rate = snapshot.heart_rate
        self.measured_at = snapshot.measured_at
        self.body = snapshot.body
        self.body_state = snapshot.body_state
        self.body_input = None
        self.revert_serial += 1


@dataclass
class Weighing:
    """Eine Wiegung: Messwerte und die Person, der sie zugeordnet ist."""

    id: int
    time: datetime
    weight_kg: float
    heart_rate: int | None = None
    ohm: dict[str, float] | None = None
    person_id: str | None = None
    candidates: list[str] = field(default_factory=list)
    snapshot: PersonSnapshot | None = None


class ScaleDevice:
    """Haelt den Zustand einer Waage und versorgt die Sensoren."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        self.hass = hass
        self.entry = entry
        self.address = address
        self.name = entry.title
        self.measurement = Measurement()
        self.history: deque[dict[str, str]] = deque(maxlen=RAW_HISTORY_SIZE)
        self.last_info: bluetooth.BluetoothServiceInfoBleak | None = None
        self.session_state = "idle"
        self.gatt_characteristics: list[str] = []
        self.connected = False
        self._listeners: list[CALLBACK_TYPE] = []
        self._session_task: asyncio.Task[None] | None = None
        self._last_attempt = 0.0
        self._last_adv: str | None = None
        self.persons: dict[str, PersonData] = {
            person.id: PersonData(person) for person in persons_from_options(entry.options)
        }
        self.tolerance_kg = float(entry.options.get(CONF_TOLERANCE, DEFAULT_TOLERANCE_KG))
        self.notify_services: list[str] = list(entry.options.get(CONF_NOTIFY, []))
        # Die letzte Wiegung uebersteht das Neuladen (z. B. wenn nach einer
        # Rueckfrage erst die passende Person angelegt wird), nicht den Neustart.
        self._stash: dict[str, Weighing] = hass.data.setdefault(DOMAIN, {})
        self.weighing: Weighing | None = self._stash.get(entry.entry_id)
        if self.weighing is not None and self.weighing.person_id not in self.persons:
            self.weighing.person_id = None
            self.weighing.snapshot = None
            _, self.weighing.candidates = match_person(
                self.weighing.weight_kg,
                {key: data.reference_weight_kg for key, data in self.persons.items()},
                self.tolerance_kg,
            )
        # Modell = Bluetooth-Name; bis zum ersten Advertising der Titel des Eintrags
        last = bluetooth.async_last_service_info(hass, address, connectable=False)
        self.model: str = (last.name if last and last.name else None) or entry.title
        self.body_for_untested = bool(entry.options.get(CONF_UNTESTED_BODY, False))
        self.protocol_problem: str | None = None
        self._cf_seen = False
        self._unknown_adverts = 0
        self._unknown_frames = 0
        self._session_locked = False
        self._session_impedances = False
        self.sessions_without_impedance = 0
        self._measuring_seen = False
        self._tracked_weight: float | None = None
        self._stale_ohm: dict[str, float] | None = None
        # Eine offene Rueckfrage aus der Zeit vor dem Neuladen gilt weiter
        self._asked = self.weighing is not None and self.weighing.person_id is None

    @property
    def device_info(self) -> DeviceInfo:
        """Geraeteeintrag der Waage."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            connections={(CONNECTION_BLUETOOTH, self.address)},
            name=self.name,
            manufacturer="Lefu (PAVABA)",
            model=compat.TESTED_MODELS.get(self.model.strip().casefold(), self.model),
        )

    # ------------------------------------------------------------ Kompatibilitaet

    @property
    def tested(self) -> bool:
        """True, wenn das Modell dieser Waage getestet ist."""
        return compat.is_tested(self.model)

    @callback
    def _async_check_model(self) -> None:
        """Ungetestetes Modell unter Reparaturen melden."""
        if self.tested:
            compat.async_clear_untested(self.hass, self.entry.entry_id)
            return
        _LOGGER.warning(
            "Waage %s (%s) ist mit dieser Integration nicht getestet. Gewicht und"
            " Impedanzen werden angezeigt, Koerperwerte nur, wenn das in den"
            " Einstellungen eingeschaltet ist%s. Testbericht willkommen: %s",
            self.model,
            self.address,
            " (ist eingeschaltet)" if self.body_for_untested else "",
            compat.REPORT_URL,
        )
        compat.async_report_untested(self.hass, self.entry.entry_id, self.model)

    @callback
    def _async_protocol_problem(self, reason: str) -> None:
        """Erkennbar falsches Protokoll: einmal melden."""
        if self.protocol_problem is not None:
            return
        if self.tested:
            # Ein getestetes Modell wird wegen eines einzelnen Ausreissers nicht abgestempelt
            _LOGGER.debug("Unerwartete Daten von %s (%s)", self.model, reason)
            return
        self.protocol_problem = reason
        compat.async_report_unsupported(self.hass, self.entry.entry_id, self.model, reason)

    # ------------------------------------------------------------------ Sensoren

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> Callable[[], None]:
        """Sensor anmelden; liefert die Abmeldefunktion."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _async_notify(self) -> None:
        self._async_track_weighing()
        for listener in list(self._listeners):
            listener()

    # ---------------------------------------------------------------- Zuordnung

    @property
    def assignment_state(self) -> str:
        """Zuordnung der letzten Wiegung als Text (fuer die Diagnose)."""
        if not self.persons:
            return NO_PERSONS
        if self.weighing is None:
            return "wartet auf Messung"
        if self.weighing.person_id is None:
            return "nicht zugeordnet"
        return f"zugeordnet: {self.persons[self.weighing.person_id].person.name}"

    @callback
    def _async_track_weighing(self) -> None:
        """Neue Wiegung erkennen, zuordnen und eintreffende Werte nachtragen."""
        measurement = self.measurement
        if measurement.status == Status.MEASURING:
            self._measuring_seen = True
        weight = measurement.weight_kg
        if not weight:
            return
        relocked = self._measuring_seen and measurement.status in LOCKED_STATES
        if relocked or weight != self._tracked_weight:
            self._measuring_seen = False
            self._tracked_weight = weight
            # Impedanzen, die jetzt noch anliegen, gehoeren zur vorigen Wiegung
            self._stale_ohm = measurement.impedances_ohm
            now = dt_util.utcnow()
            self.weighing = Weighing(int(now.timestamp() * 1000), now, weight)
            self._stash[self.entry.entry_id] = self.weighing
            self._async_auto_assign(self.weighing)
        weighing = self.weighing
        if weighing is None or weighing.weight_kg != self._tracked_weight:
            return
        if measurement.heart_rate:
            weighing.heart_rate = measurement.heart_rate
        ohm = measurement.impedances_ohm
        if ohm is not None and ohm != self._stale_ohm:
            weighing.ohm = ohm
        if weighing.person_id is not None:
            self._apply(weighing)

    @callback
    def _async_auto_assign(self, weighing: Weighing) -> None:
        self._async_dismiss_question()
        if not self.persons:
            return
        person_id, weighing.candidates = match_person(
            weighing.weight_kg,
            {key: data.reference_weight_kg for key, data in self.persons.items()},
            self.tolerance_kg,
        )
        if person_id is not None:
            self._assign(weighing, person_id)
            return
        _LOGGER.info(
            "Wiegung mit %.2f kg nicht eindeutig zuzuordnen, Rueckfrage", weighing.weight_kg
        )
        self._async_ask(weighing)

    def _assign(self, weighing: Weighing, person_id: str | None) -> None:
        """Wiegung einer Person geben; eine vorige Zuordnung wird zurueckgenommen."""
        if weighing.person_id == person_id:
            return
        previous = self.persons.get(weighing.person_id or "")
        if previous is not None and weighing.snapshot is not None:
            previous.restore(weighing.snapshot)
        weighing.snapshot = None
        weighing.person_id = person_id
        if person_id is not None:
            data = self.persons[person_id]
            weighing.snapshot = data.snapshot()
            data.weighing_serial += 1
            self._apply(weighing)

    def _apply(self, weighing: Weighing) -> None:
        """Werte der Wiegung bei der Person eintragen und Koerperwerte berechnen."""
        data = self.persons[weighing.person_id or ""]
        data.weight_kg = weighing.weight_kg
        data.measured_at = weighing.time
        if weighing.heart_rate:
            data.heart_rate = weighing.heart_rate
        if weighing.ohm is None:
            return
        if not self.tested and not self.body_for_untested:
            data.body_state = (
                f"nicht berechnet: Modell „{self.model}“ ist ungetestet"
                " (in den Einstellungen einschaltbar)"
            )
            return
        measured = (weighing.weight_kg, *weighing.ohm.values())
        if measured == data.body_input:
            return
        data.body_input = measured
        profile = data.person.profile
        try:
            data.body = compute(
                profile.sex,
                profile.age_on(dt_util.now().date()),
                profile.height_cm,
                weighing.weight_kg,
                {segment: weighing.ohm[f"z20_{segment}"] for segment in SEGMENTS},
                {segment: weighing.ohm[f"z100_{segment}"] for segment in SEGMENTS},
            )
        except BodyCompositionError as err:
            data.body_state = f"Messung ausserhalb des gueltigen Bereichs: {err.reason}"
            _LOGGER.warning(
                "Koerperwerte fuer %s nicht berechenbar (%s)", data.person.name, err.reason
            )
            return
        data.body_state = "berechnet"
        data.body_serial += 1

    @callback
    def async_assign(self, person_id: str | None) -> None:
        """Letzte Wiegung von Hand zuordnen (None: keiner Person)."""
        if self.weighing is None:
            raise HomeAssistantError("Es liegt keine Wiegung vor, die zugeordnet werden kann")
        if person_id is not None and person_id not in self.persons:
            raise HomeAssistantError(f"Unbekannte Person: {person_id}")
        self._assign(self.weighing, person_id)
        self._async_dismiss_question()
        for listener in list(self._listeners):
            listener()

    # ---------------------------------------------------------------- Rueckfrage

    @property
    def _notification_id(self) -> str:
        return f"{DOMAIN}_{self.entry.entry_id}"

    def _action(self, weighing: Weighing, person_id: str) -> str:
        return f"UHS_{self.entry.entry_id}_{weighing.id}_{person_id}"

    @callback
    def _async_ask(self, weighing: Weighing) -> None:
        """Nachfragen, wer sich gewogen hat: Mitteilung in HA und aufs Handy."""
        texts = TEXTS["de" if self.hass.config.language.startswith("de") else "en"]
        names = [self.persons[person_id].person.name for person_id in weighing.candidates]
        placeholders = {
            "weight": f"{weighing.weight_kg:.2f}",
            "scale": self.name,
            "candidates": ", ".join(names),
        }
        self._asked = True
        persistent_notification.async_create(
            self.hass,
            texts["message"].format(**placeholders),
            title=texts["title"],
            notification_id=self._notification_id,
        )
        # Auf dem Handy passen nur wenige Knoepfe: die drei naechstliegenden Personen
        actions = [
            {"action": self._action(weighing, person_id), "title": name}
            for person_id, name in list(zip(weighing.candidates, names))[:3]
        ]
        self._async_send_mobile(
            {
                "title": texts["title"],
                "message": texts["mobile"].format(**placeholders),
                "data": {"tag": self._notification_id, "actions": actions},
            }
        )

    @callback
    def _async_dismiss_question(self) -> None:
        if not self._asked:
            return
        self._asked = False
        persistent_notification.async_dismiss(self.hass, self._notification_id)
        self._async_send_mobile(
            {"message": "clear_notification", "data": {"tag": self._notification_id}}
        )

    @callback
    def _async_send_mobile(self, data: dict[str, Any]) -> None:
        for service in self.notify_services:
            self.entry.async_create_background_task(
                self.hass, self._async_call_notify(service, data), f"{DOMAIN} notify"
            )

    async def _async_call_notify(self, service: str, data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(
                "notify", service.removeprefix("notify."), data, blocking=True
            )
        except Exception as err:  # noqa: BLE001 - eine Mitteilung darf nie die Messung stoeren
            _LOGGER.warning("Mitteilung ueber notify.%s fehlgeschlagen: %s", service, err)

    @callback
    def _async_on_mobile_action(self, event: Event) -> None:
        """Antwort auf die Rueckfrage vom Handy."""
        weighing = self.weighing
        if weighing is None:
            return
        action = str(event.data.get("action", ""))
        for person_id in self.persons:
            if action == self._action(weighing, person_id):
                self.async_assign(person_id)
                return

    @callback
    def _record(self, source: str, data: str) -> None:
        self.history.append(
            {"time": datetime.now(timezone.utc).isoformat(), "src": source, "data": data}
        )

    @property
    def last_raw(self) -> str | None:
        """Letzter aufgezeichneter Eintrag als Text."""
        if not self.history:
            return None
        last = self.history[-1]
        return f"{last['src']}:{last['data']}"

    # --------------------------------------------------------------- Advertising

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Advertising der Waage und Antworten auf Rueckfragen abonnieren."""
        unsubscribe = [
            bluetooth.async_register_callback(
                self.hass,
                self._async_on_advertisement,
                {"address": self.address, "connectable": False},
                bluetooth.BluetoothScanningMode.ACTIVE,
            ),
            self.hass.bus.async_listen(EVENT_MOBILE_ACTION, self._async_on_mobile_action),
        ]
        self._async_check_model()

        @callback
        def _stop() -> None:
            for remove in unsubscribe:
                remove()

        return _stop

    @callback
    def _async_on_advertisement(
        self,
        info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        self.last_info = info
        if info.name and info.name != self.model:
            self.model = info.name
            self._async_check_model()
        parts = [f"0x{cid:04X}={data.hex()}" for cid, data in info.manufacturer_data.items()]
        parts += [f"{uuid[4:8]}={data.hex()}" for uuid, data in info.service_data.items()]
        if not parts:
            return
        adv = " ".join(parts)
        if adv == self._last_adv:
            return
        self._last_adv = adv
        self._record("adv", adv)
        _LOGGER.debug("Advertising %s (RSSI %s): %s", self.address, info.rssi, adv)

        frame = None
        for data in info.manufacturer_data.values():
            if frame := find_cf_frame(data):
                break
        if frame is not None:
            self._cf_seen = True
            if frame.extra:
                # Impedanz im Gewichts-Frame: andere Geraetefamilie (4 Elektroden)
                self._async_protocol_problem(compat.REASON_FOUR_ELECTRODE)
        elif not self._cf_seen and any(
            len(data) > 6 and any(data[6:]) for data in info.manufacturer_data.values()
        ):
            self._unknown_adverts += 1
            if self._unknown_adverts >= compat.UNKNOWN_ADVERTISING_LIMIT:
                self._async_protocol_problem(compat.REASON_UNKNOWN_ADVERTISING)
        if frame is not None:
            if not self.connected:
                self.measurement.feed_cf(frame)
            elif frame.status in LOCKED_STATES and frame.weight_kg > 0:
                # Waehrend einer Sitzung kommen die Daten ueber FFF4; das
                # Advertising darf dort nichts zuruecksetzen, nur das Gewicht sichern.
                self.measurement.weight_kg = frame.weight_kg
        self._async_notify()

        if frame is not None and frame.status in ACTIVE_STATES:
            self._async_maybe_start_session()

    # --------------------------------------------------------------------- GATT

    @callback
    def _async_maybe_start_session(self) -> None:
        if self._session_task is not None and not self._session_task.done():
            return
        if time.monotonic() - self._last_attempt < CONNECT_COOLDOWN:
            return
        self._last_attempt = time.monotonic()
        self._session_task = self.entry.async_create_background_task(
            self.hass, self._async_session(), f"unique_health_scale {self.address}"
        )

    @callback
    def _set_session_state(self, state: str) -> None:
        self.session_state = state
        self._record("gatt", state)
        _LOGGER.debug("Sitzung %s: %s", self.address, state)
        self._async_notify()

    async def _async_session(self) -> None:
        """Verbinden, Notifications abonnieren und mitlesen, bis die Waage trennt."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            self._set_session_state("kein verbindungsfaehiger Bluetooth-Adapter in Reichweite")
            return

        disconnected = asyncio.Event()
        loop = self.hass.loop

        def _on_disconnect(_client: Any) -> None:
            loop.call_soon_threadsafe(disconnected.set)

        self._set_session_state("verbinde")
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.name,
                disconnected_callback=_on_disconnect,
                max_attempts=2,
            )
        except (BleakError, TimeoutError) as err:
            self._set_session_state(f"Verbindung fehlgeschlagen: {err}")
            return

        # Ein fehlgeschlagener erster Verbindungsversuch meldet sich ebenfalls
        # ueber den Disconnect-Callback; fuer die neue Verbindung zaehlt er nicht.
        disconnected.clear()
        self.connected = True
        try:
            self.gatt_characteristics = [
                f"{char.uuid[4:8] if char.uuid.endswith(LEFU_SERVICE_UUID[8:]) else char.uuid}"
                f" [{','.join(char.properties)}]"
                for service in client.services
                for char in service.characteristics
            ]
            subscribed: list[str] = []
            for uuid in NOTIFY_CHARS:
                char = client.services.get_characteristic(uuid)
                if char is None or not {"notify", "indicate"} & set(char.properties):
                    continue
                try:
                    await client.start_notify(char, partial(self._on_notification, uuid[4:8]))
                except (BleakError, TimeoutError) as err:
                    self._record("gatt", f"notify {uuid[4:8]} fehlgeschlagen: {err}")
                else:
                    subscribed.append(uuid[4:8])
            if not subscribed:
                self._set_session_state("verbunden, aber keine Notify-Characteristic gefunden")
                self._async_protocol_problem(compat.REASON_NO_NOTIFY)
                return
            self._unknown_frames = 0
            self._session_locked = self.measurement.status in LOCKED_STATES
            self._session_impedances = False
            self._set_session_state(f"verbunden, lausche auf {','.join(subscribed)}")
            try:
                async with asyncio.timeout(SESSION_TIMEOUT):
                    while not disconnected.is_set():
                        if not client.is_connected:
                            break
                        try:
                            async with asyncio.timeout(2):
                                await disconnected.wait()
                        except TimeoutError:
                            continue
            except TimeoutError:
                self._set_session_state("Sitzung nach Zeitlimit beendet")
            else:
                self._set_session_state("Waage hat getrennt")
            self._async_session_finished()
        except BleakError as err:
            self._set_session_state(f"Fehler: {err}")
        finally:
            self.connected = False
            try:
                await client.disconnect()
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("Trennen fehlgeschlagen: %s", err)
            self._last_attempt = time.monotonic()

    @callback
    def _async_session_finished(self) -> None:
        """Nach einer Sitzung pruefen, ob die Koerperanalyse angekommen ist."""
        if self._session_impedances:
            self.sessions_without_impedance = 0
            compat.async_clear_no_impedance(self.hass, self.entry.entry_id)
            return
        if not self._session_locked:
            # Niemand hat sich gewogen (oder die Waage war schon fertig)
            return
        if self._unknown_frames and not self.tested:
            self._async_protocol_problem(compat.REASON_UNKNOWN_FRAMES)
            return
        self.sessions_without_impedance += 1
        _LOGGER.info(
            "Messung auf %s ohne Impedanzen (%d. in Folge)",
            self.model,
            self.sessions_without_impedance,
        )
        if self.sessions_without_impedance >= compat.NO_IMPEDANCE_LIMIT:
            compat.async_report_no_impedance(self.hass, self.entry.entry_id, self.model)

    def _on_notification(
        self, source: str, _char: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self.hass.loop.call_soon_threadsafe(self._async_handle_frame, source, bytes(data))

    @callback
    def _async_handle_frame(self, source: str, data: bytes) -> None:
        self._record(source, data.hex())
        understood = self.measurement.feed(data)
        if not understood:
            self._unknown_frames += 1
        if self.measurement.status in LOCKED_STATES:
            self._session_locked = True
        if self.measurement.impedances_ohm is not None:
            self._session_impedances = True
        _LOGGER.debug(
            "%s von %s: %s%s", source, self.address, data.hex(), "" if understood else " (unbekannt)"
        )
        self._async_notify()
