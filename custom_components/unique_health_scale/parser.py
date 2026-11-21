"""Decoder fuer die Bluetooth-Daten der Lefu-Waage.

Noch nicht implementiert: Das Frame-Format haengt von der Geraetefamilie ab,
die Lefus SDK anhand des Bluetooth-Namens bestimmt (siehe docs/protocol.md).
Bis Name und Rohframes der Waage vorliegen, liefert parse_advertisement None
und die Integration zeichnet nur Rohdaten auf.
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


def parse_advertisement(
    name: str | None,
    manufacturer_data: dict[int, bytes],
    service_data: dict[str, bytes],
) -> LefuReading | None:
    """Advertising-Daten der Waage dekodieren."""
    return None
