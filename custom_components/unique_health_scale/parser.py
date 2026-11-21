"""Decoder fuer die Bluetooth-Daten der Lefu-Geraetefamilie "Ice".

Abgeleitet aus der Unique-Health-App (PPBluetoothKit,
+[PPBluetoothIceDataAnalysis analysisData:]) und echten Mitschnitten einer
PAVABA "smart scale P1". Details: docs/protocol.md.

Drei Frame-Typen, erkennbar am ersten Byte:

* 0xCF, 11 Bytes  – Gewicht, Status, Herzfrequenz (Advertising und FFF4)
* 0xBF, 23 Bytes  – fuenf Impedanzen einer Frequenz (FFF4)
* 0xDF, 17 Bytes  – Impedanzen in Teilpaketen (FFF4)

Die Impedanzen sind vom Geraet kodiert ("EnCode"); sie werden hier
unveraendert durchgereicht.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

CF_LENGTH = 11
BF_LENGTH = 23
DF_LENGTH = 17

SEGMENTS = ("right_arm", "left_arm", "trunk", "right_leg", "left_leg")
FREQUENCIES = {0: 20, 1: 100}
IMPEDANCE_KEYS = tuple(
    f"z{khz}_{segment}" for khz in FREQUENCIES.values() for segment in SEGMENTS
)


class Status(IntEnum):
    """Statusbyte (Byte 9) eines CF-Frames."""

    END = 0
    MEASURING = 1
    OVERLOAD = 2
    LOCKED = 5
    ANALYZING = 6
    LOCKED_ALT = 8


LOCKED_STATES = (Status.LOCKED, Status.LOCKED_ALT)
ACTIVE_STATES = (Status.MEASURING, Status.LOCKED, Status.ANALYZING, Status.LOCKED_ALT)


@dataclass(frozen=True)
class CfFrame:
    """Dekodierter Gewichts-/Status-Frame."""

    status: int
    weight_kg: float
    unit: int
    heart_rate: int | None
    heart_rate_measuring: bool


def _xor(data: bytes) -> int:
    result = 0
    for byte in data:
        result ^= byte
    return result


def parse_cf_frame(data: bytes) -> CfFrame | None:
    """Einen 11-Byte-CF-Frame dekodieren (Pruefsumme: XOR der Bytes 0..9)."""
    if len(data) != CF_LENGTH or data[0] != 0xCF or _xor(data[:10]) != data[10]:
        return None
    return CfFrame(
        status=data[9],
        weight_kg=int.from_bytes(data[3:5], "little") / 100,
        unit=data[8],
        heart_rate=data[1] if data[2] == 0xC0 else None,
        heart_rate_measuring=data[2] == 0x80,
    )


def find_cf_frame(data: bytes) -> CfFrame | None:
    """CF-Frame in Advertising-Daten finden (dort stehen 6 Bytes MAC davor)."""
    for offset in range(len(data) - CF_LENGTH, -1, -1):
        if data[offset] == 0xCF and (
            frame := parse_cf_frame(data[offset : offset + CF_LENGTH])
        ):
            return frame
    return None


def _int32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=True)


def parse_impedance_frame(data: bytes) -> dict[str, int] | None:
    """BF-/DF-Frame dekodieren.

    Liefert die enthaltenen Impedanzen, ein leeres Dict fuer "zuruecksetzen"
    und None, wenn es kein Impedanz-Frame ist.
    """
    if len(data) == BF_LENGTH and data[0] == 0xBF:
        if data[1] & 0x20:
            return {}
        khz = FREQUENCIES.get(data[1] & 0x0F)
        if khz is None:
            return {}
        return {
            f"z{khz}_{segment}": _int32(data, 2 + 4 * index)
            for index, segment in enumerate(SEGMENTS)
        }
    if len(data) == DF_LENGTH and data[0] == 0xDF:
        if data[1] == 0xFF:
            return {}
        khz = FREQUENCIES.get(data[3])
        if khz is None or data[2] not in (0, 1):
            return {}
        segments = SEGMENTS[:3] if data[2] == 0 else SEGMENTS[3:]
        return {
            f"z{khz}_{segment}": _int32(data, 4 + 4 * index)
            for index, segment in enumerate(segments)
        }
    return None


@dataclass
class Measurement:
    """Zustand einer laufenden bzw. der letzten Messung."""

    status: int | None = None
    live_weight_kg: float | None = None
    weight_kg: float | None = None
    heart_rate: int | None = None
    impedances: dict[str, int] = field(default_factory=dict)
    complete: bool = False

    @property
    def impedances_complete(self) -> bool:
        return all(self.impedances.get(key) for key in IMPEDANCE_KEYS)

    def feed_cf(self, frame: CfFrame) -> None:
        """CF-Frame einarbeiten (Ablauf wie in der App)."""
        self.status = frame.status
        if frame.status == Status.MEASURING:
            # Neue Messung: Gewicht schwankt noch, alte Teilwerte verwerfen
            self.live_weight_kg = frame.weight_kg
            self.heart_rate = None
            self.impedances = {}
            self.complete = False
        elif frame.status in LOCKED_STATES:
            # Gewicht steht fest, die Waage beginnt mit der Koerperanalyse
            if frame.weight_kg > 0:
                self.live_weight_kg = frame.weight_kg
                self.weight_kg = frame.weight_kg
            self.heart_rate = None
            self.impedances = {}
            self.complete = False
        elif frame.status == Status.ANALYZING:
            self.impedances = {}
            self.complete = False
        elif frame.status == Status.END:
            self.complete = True
        if frame.heart_rate:
            self.heart_rate = frame.heart_rate

    def feed_impedance(self, values: dict[str, int]) -> None:
        """Impedanzwerte einarbeiten; leeres Dict setzt zurueck."""
        if not values:
            self.impedances = {}
        else:
            self.impedances.update(values)

    def feed(self, data: bytes) -> bool:
        """Beliebigen FFF4-Frame einarbeiten. True, wenn er verstanden wurde."""
        if (frame := parse_cf_frame(data)) is not None:
            self.feed_cf(frame)
            return True
        if (values := parse_impedance_frame(data)) is not None:
            self.feed_impedance(values)
            return True
        return False
