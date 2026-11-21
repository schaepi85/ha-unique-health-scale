"""Decoder fuer die Bluetooth-Daten der Lefu-Waage.

Noch nicht implementiert: Das Frame-Format wird aus echten Mitschnitten
(Sensor "Rohdaten") und der REA-Analyse von PPBluetoothKit abgeleitet,
siehe docs/protocol.md. Bis dahin liefert parse_advertisement None und
die Integration zeichnet nur Rohdaten auf.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LefuReading:
    """Eine dekodierte Messung."""

    weight_kg: float | None = None
    impedance_ohm: int | None = None
    stable: bool = False
    extra: dict[str, float] = field(default_factory=dict)


def parse_advertisement(data: bytes) -> LefuReading | None:
    """Herstellerdaten (Company ID 0x1A10) dekodieren."""
    return None
