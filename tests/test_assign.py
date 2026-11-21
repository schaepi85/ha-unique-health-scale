"""Zuordnung einer Wiegung ueber das Gewicht (erfundene Werte)."""
from custom_components.unique_health_scale.assign import match_person


def test_clear_match():
    assert match_person(75.4, {"a": 75.0, "b": 58.0}, 3.0) == ("a", ["a", "b"])
    assert match_person(57.1, {"a": 75.0, "b": 58.0}, 3.0) == ("b", ["b", "a"])


def test_outside_tolerance_asks():
    assert match_person(66.0, {"a": 75.0, "b": 58.0}, 3.0) == (None, ["b", "a"])


def test_two_close_people():
    # Beide in der Toleranz und aehnlich nah: Rueckfrage
    assert match_person(76.2, {"a": 75.0, "b": 77.0}, 3.0) == (None, ["b", "a"])
    # Beide in der Toleranz, aber eine Person liegt deutlich naeher
    assert match_person(75.1, {"a": 75.0, "b": 77.0}, 3.0) == ("a", ["a", "b"])


def test_people_without_known_weight():
    assert match_person(80.0, {"a": None}, 3.0) == ("a", ["a"])
    assert match_person(80.0, {"a": None, "b": None}, 3.0) == (None, ["a", "b"])
    assert match_person(80.0, {"a": None, "b": 79.5}, 3.0) == ("b", ["b", "a"])
    assert match_person(60.0, {"a": None, "b": 79.5}, 3.0) == (None, ["b", "a"])


def test_large_family():
    family = {"p1": 82.0, "p2": 64.0, "p3": 55.5, "p4": 41.0, "p5": 28.0, "p6": 17.5}
    for person_id, weight in family.items():
        assert match_person(weight + 0.4, family, 3.0)[0] == person_id
    assert match_person(48.0, family, 3.0)[0] is None
    assert match_person(0.0, {}, 3.0) == (None, [])
