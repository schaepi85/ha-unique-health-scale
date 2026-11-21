"""Profil der Person, fuer die die Koerperwerte berechnet werden."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .bodycomp import Sex
from .const import CONF_AGE, CONF_BIRTHDAY, CONF_HEIGHT, CONF_SEX


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
