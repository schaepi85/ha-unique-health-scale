"""Tests der Koerperwert-Berechnung mit erfundenen Messungen.

Die Sollwerte in bodycomp_golden.json wurden einmalig gegen das Verhalten
der App abgeglichen; alle Eingaben sind synthetisch (keine echten Personen).
"""
import dataclasses
import json
from datetime import date
from pathlib import Path

import pytest

from custom_components.unique_health_scale.bodycomp import (
    BODY_TYPES,
    SEGMENTS,
    BodyCompositionError,
    F,
    Sex,
    compute,
)
from custom_components.unique_health_scale.profile import Profile

GOLDEN = json.loads((Path(__file__).parent / "bodycomp_golden.json").read_text())

Z20 = dict(right_arm=310.0, left_arm=305.0, trunk=25.0, right_leg=260.0, left_leg=258.0)
Z100 = dict(right_arm=270.0, left_arm=269.0, trunk=24.0, right_leg=225.0, left_leg=227.0)


def _jsonable(value):
    """Wie nach json.load: Tupel werden zu Listen."""
    return json.loads(json.dumps(value))


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_matches_reference(name):
    case = GOLDEN[name]
    result = compute(**{**case["input"], "sex": Sex(case["input"]["sex"])})
    assert _jsonable(dataclasses.asdict(result)) == case["expected"]


def test_masses_add_up():
    body = compute(Sex.MALE, 35, 180, 75.0, Z20, Z100)
    assert body.weight_kg == 75.0
    assert round(body.body_fat_kg + body.fat_free_mass_kg, 1) == body.weight_kg
    assert round(body.water_kg + body.protein_kg, 1) == body.muscle_kg
    assert round(body.muscle_kg + body.mineral_kg, 1) == body.fat_free_mass_kg
    assert round(body.intracellular_water_kg + body.extracellular_water_kg, 1) == body.water_kg
    assert round(body.weight_kg + body.weight_control_kg, 1) == body.target_weight_kg
    assert set(body.segment_fat_kg) == set(body.segment_muscle_kg) == set(SEGMENTS)
    assert round(sum(body.segment_fat_kg.values()), 1) <= body.body_fat_kg
    assert body.body_type in BODY_TYPES
    assert body.ranges["bmi"] == (18.5, 23.0) and body.levels["bmi"] == 2
    assert set(body.levels) == set(body.ranges)


def test_sex_changes_reference_ranges():
    male = compute(Sex.MALE, 35, 170, 70.0, Z20, Z100)
    female = compute(Sex.FEMALE, 35, 170, 70.0, Z20, Z100)
    assert male.ideal_weight_kg > female.ideal_weight_kg
    assert male.ranges["body_fat_percent"] == (10.0, 20.0)
    assert female.ranges["body_fat_percent"] == (18.0, 28.0)
    # Wasser, fettfreie Masse und Fett haengen nicht vom Geschlecht ab
    assert male.water_kg == female.water_kg and male.body_fat_kg == female.body_fat_kg


def test_weight_is_truncated_to_tenths():
    assert compute(Sex.MALE, 35, 180, 75.09, Z20, Z100).weight_kg == 75.0
    assert compute(Sex.MALE, 35, 180, 75.1, Z20, Z100).weight_kg == 75.1


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"weight_kg": 9.9}, "weight"),
        ({"weight_kg": 300.1}, "weight"),
        ({"height_cm": 89}, "height"),
        ({"height_cm": 221}, "height"),
        ({"age": 5}, "age"),
        ({"age": 100}, "age"),
        ({"z20_ohm": {**Z20, "left_arm": 99.9}}, "impedance_left_arm"),
        ({"z100_ohm": {**Z100, "right_leg": 700.1}}, "impedance_right_leg"),
        ({"z20_ohm": {**Z20, "trunk": 4.9}}, "impedance_trunk"),
        ({"z100_ohm": {**Z100, "trunk": 100.1}}, "impedance_trunk"),
        (
            {"z100_ohm": dict(right_arm=687.5, left_arm=579.0, trunk=5.0, right_leg=506.5, left_leg=505.7)},
            "impedances_inconsistent",
        ),
    ],
)
def test_out_of_range(changes, reason):
    arguments = dict(sex=Sex.MALE, age=35, height_cm=180, weight_kg=75.0, z20_ohm=Z20, z100_ohm=Z100)
    with pytest.raises(BodyCompositionError) as error:
        compute(**{**arguments, **changes})
    assert error.value.reason == reason


def test_limits_are_inclusive():
    compute(Sex.FEMALE, 6, 90, 10.0, Z20, Z100)
    compute(Sex.MALE, 99, 220, 300.0, Z20, Z100)


def test_low_body_fat_is_lifted():
    """Unter 10 % zeigt die App einen angehobenen Fettanteil (hier 3 % + 5)."""
    lean = dict(right_arm=250.0, left_arm=250.0, trunk=20.0, right_leg=210.0, left_leg=210.0)
    body = compute(Sex.MALE, 30, 190, 70.0, lean, {key: value * 0.9 for key, value in lean.items()})
    assert body.fat_free_mass_kg == 67.9  # gedeckelt auf 97 % des Gewichts
    assert body.body_fat_percent == 8.0
    assert body.body_fat_kg == 5.6


def test_single_precision_number():
    assert float(F(0.1)) == 0.10000000149011612
    assert isinstance(F(1.5) * 2 + 1 - 0.5, F)
    assert float(1 - F(0.25)) == 0.75 and float(3 / F(2.0)) == 1.5


def test_profile_age():
    profile = Profile.from_options({"sex": "male", "height": 180, "birthday": "1990-06-15"})
    assert profile.sex is Sex.MALE and profile.height_cm == 180
    assert profile.age_on(date(2026, 6, 14)) == 35
    assert profile.age_on(date(2026, 6, 15)) == 36
    fixed = Profile.from_options({"sex": "female", "height": 165.0, "age": 29})
    assert fixed.sex is Sex.FEMALE and fixed.age_on(date(2030, 1, 1)) == 29
    assert Profile.from_options({}) is None
    assert Profile.from_options({"sex": "male", "height": 180}) is None
    assert Profile.from_options({"sex": "male", "height": 180, "birthday": "kaputt"}) is None
