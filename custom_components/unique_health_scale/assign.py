"""Zuordnung einer Wiegung zu einer Person ueber das Gewicht."""

from __future__ import annotations

from collections.abc import Mapping

from .const import MIN_GAP_KG


def match_person(
    weight_kg: float,
    references: Mapping[str, float | None],
    tolerance_kg: float,
    min_gap_kg: float = MIN_GAP_KG,
) -> tuple[str | None, list[str]]:
    """Person zu einem Gewicht finden.

    ``references`` enthaelt je Person das letzte bekannte Gewicht (oder None).
    Liefert (Person, Kandidaten): Die Person ist gesetzt, wenn die Zuordnung
    eindeutig ist; die Kandidaten sind nach Naehe sortiert, Personen ohne
    bekanntes Gewicht stehen am Ende.

    Eindeutig heisst: Das Gewicht liegt innerhalb der Toleranz um das letzte
    Gewicht genau einer Person – oder mehrerer, wenn die naechste Person
    mindestens ``min_gap_kg`` naeher liegt als die uebernaechste. Eine einzige
    Person ohne bekanntes Gewicht bekommt ihre erste Wiegung ohne Rueckfrage.
    """
    known = sorted(
        (abs(reference - weight_kg), person_id)
        for person_id, reference in references.items()
        if reference is not None
    )
    candidates = [person_id for _, person_id in known] + [
        person_id for person_id, reference in references.items() if reference is None
    ]
    if len(references) == 1 and not known:
        return candidates[0], candidates
    if known and known[0][0] <= tolerance_kg:
        runner_up = known[1][0] if len(known) > 1 else None
        if (
            runner_up is None
            or runner_up > tolerance_kg
            or runner_up - known[0][0] >= min_gap_kg
        ):
            return known[0][1], candidates
    return None, candidates
