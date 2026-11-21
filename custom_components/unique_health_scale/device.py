"""Laufzeitobjekt einer Waage: Advertising auswerten, verbinden, FFF4 mitlesen."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
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
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from homeassistant.util import dt as dt_util

from .bodycomp import SEGMENTS, BodyComposition, BodyCompositionError, compute
from .const import (
    CONNECT_COOLDOWN,
    LEFU_SERVICE_UUID,
    NOTIFY_CHARS,
    RAW_HISTORY_SIZE,
    SESSION_TIMEOUT,
)
from .parser import ACTIVE_STATES, LOCKED_STATES, Measurement, find_cf_frame
from .profile import Profile

_LOGGER = logging.getLogger(__name__)


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
        self.profile = Profile.from_options(entry.options)
        self.body: BodyComposition | None = None
        self.body_state = "kein Profil hinterlegt" if self.profile is None else "wartet auf Messung"
        self.body_serial = 0
        self._body_input: tuple[Any, ...] | None = None

    # ------------------------------------------------------------------ Sensoren

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> Callable[[], None]:
        """Sensor anmelden; liefert die Abmeldefunktion."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _async_notify(self) -> None:
        self._async_update_body()
        for listener in list(self._listeners):
            listener()

    @callback
    def _async_update_body(self) -> None:
        """Koerperwerte berechnen, sobald Gewicht und alle Impedanzen da sind."""
        weight = self.measurement.weight_kg
        ohm = self.measurement.impedances_ohm
        if self.profile is None or not weight or ohm is None:
            return
        measured = (weight, *ohm.values())
        if measured == self._body_input:
            return
        self._body_input = measured
        try:
            self.body = compute(
                self.profile.sex,
                self.profile.age_on(dt_util.now().date()),
                self.profile.height_cm,
                weight,
                {segment: ohm[f"z20_{segment}"] for segment in SEGMENTS},
                {segment: ohm[f"z100_{segment}"] for segment in SEGMENTS},
            )
        except BodyCompositionError as err:
            self.body_state = f"Messung ausserhalb des gueltigen Bereichs: {err.reason}"
            _LOGGER.warning("Koerperwerte nicht berechenbar (%s)", err.reason)
            return
        self.body_state = "berechnet"
        self.body_serial += 1

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
        """Advertising der Waage abonnieren."""
        return bluetooth.async_register_callback(
            self.hass,
            self._async_on_advertisement,
            {"address": self.address, "connectable": False},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )

    @callback
    def _async_on_advertisement(
        self,
        info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        self.last_info = info
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
                return
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
        except BleakError as err:
            self._set_session_state(f"Fehler: {err}")
        finally:
            self.connected = False
            try:
                await client.disconnect()
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("Trennen fehlgeschlagen: %s", err)
            self._last_attempt = time.monotonic()

    def _on_notification(
        self, source: str, _char: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self.hass.loop.call_soon_threadsafe(self._async_handle_frame, source, bytes(data))

    @callback
    def _async_handle_frame(self, source: str, data: bytes) -> None:
        self._record(source, data.hex())
        understood = self.measurement.feed(data)
        _LOGGER.debug(
            "%s von %s: %s%s", source, self.address, data.hex(), "" if understood else " (unbekannt)"
        )
        self._async_notify()
