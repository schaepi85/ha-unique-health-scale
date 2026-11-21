"""Profil der Person, fuer die die Koerperwerte berechnet werden."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .bodycomp import Sex
from .const import (
    CONF_AGE,
    CONF_BIRTHDAY,
    CONF_HEIGHT,
    CONF_ID,
    CONF_NAME,
    CONF_PERSONS,
    CONF_REFERENCE_WEIGHT,
    CONF_SEX,
)


@dataclass(frozen=True)
class Profile:
    """Geschlecht, Groesse und Alter (Geburtsdatum oder festes Alter)."""

    sex: Sex
    height_cm: int
    birthday: date | None = None
    age: int | None = None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Profile | None:
        """Profil aus den Optionen lesen; None, solange es unvollstaendig ist."""
        try:
            sex = Sex[str(options[CONF_SEX]).upper()]
            height = int(options[CONF_HEIGHT])
        except (KeyError, ValueError):
            return None
        birthday = None
        if options.get(CONF_BIRTHDAY):
            try:
                birthday = date.fromisoformat(str(options[CONF_BIRTHDAY]))
            except ValueError:
                return None
        age = int(options[CONF_AGE]) if options.get(CONF_AGE) else None
        if birthday is None and age is None:
            return None
        return cls(sex, height, birthday, age)

    def age_on(self, day: date) -> int:
        """Alter in vollen Jahren am angegebenen Tag."""
        if self.birthday is None:
            assert self.age is not None
            return self.age
        had_birthday = (day.month, day.day) >= (self.birthday.month, self.birthday.day)
        return day.year - self.birthday.year - (0 if had_birthday else 1)


@dataclass(frozen=True)
class Person:
    """Eine Person, die die Waage nutzt."""

    id: str
    name: str
    profile: Profile
    reference_weight_kg: float | None = None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Person | None:
        """Person aus ihrem Optionen-Eintrag lesen; None, wenn er unvollstaendig ist."""
        profile = Profile.from_options(options)
        if profile is None or not options.get(CONF_ID) or not options.get(CONF_NAME):
            return None
        reference = options.get(CONF_REFERENCE_WEIGHT)
        return cls(
            str(options[CONF_ID]),
            str(options[CONF_NAME]),
            profile,
            float(reference) if reference else None,
        )


def persons_from_options(options: Mapping[str, Any]) -> list[Person]:
    """Alle vollstaendig konfigurierten Personen eines Config-Eintrags."""
    persons = (Person.from_options(item) for item in options.get(CONF_PERSONS, []))
    return [person for person in persons if person is not None]


def person_identifier(address: str, person_id: str) -> str:
    """Kennung des Geraets bzw. Praefix der Entitaeten einer Person."""
    return f"{address}_{person_id}"
