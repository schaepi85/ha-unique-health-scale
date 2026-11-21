"""Koerperzusammensetzung aus Gewicht, Profil und den zehn Impedanzen.

Die Waage misst nur: Gewicht, Herzfrequenz und je fuenf Impedanzen bei
20 kHz und 100 kHz (rechter/linker Arm, Rumpf, rechtes/linkes Bein).
Alle weiteren Werte (Koerperfett, Muskelmasse, Wasser ...) sind
Regressionsformeln ueber diese Messwerte, Groesse, Alter und Geschlecht.

Dieses Modul ist eine eigenstaendig geschriebene Nachbildung dieser
Formeln fuer die "smart scale P1" (Lefu CF597), damit die Werte in
Home Assistant ohne Cloud und ohne App entstehen. Es enthaelt keinen
Code des Herstellers und ist nicht vom Hersteller freigegeben; die
Ergebnisse sind Schaetzwerte und keine medizinischen Messwerte.

Damit dieselben Zahlen herauskommen wie in der App, wird wie dort in
einfacher Genauigkeit (float32) und mit ganzzahligen Zehnteln gerechnet:

* Massen in 0,1 kg, Impedanzen in 0,1 Ohm, Anteile in Promille
* Zwischenergebnisse werden abgeschnitten, nicht gerundet, ausser wo
  ausdruecklich `_scaled()` (kaufmaennisch) verwendet wird
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import IntEnum

SEGMENTS = ("right_arm", "left_arm", "trunk", "right_leg", "left_leg")


class Sex(IntEnum):
    """Geschlecht, wie es in die Formeln eingeht."""

    FEMALE = 0
    MALE = 1


class BodyCompositionError(ValueError):
    """Eingabe liegt ausserhalb des Bereichs, fuer den die Formeln gelten."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Rechnen in einfacher Genauigkeit
# ---------------------------------------------------------------------------


def _single(value: float) -> float:
    """Auf die naechste float32-Zahl runden."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


class F(float):
    """float32-Zahl: jede Grundrechenart rundet auf einfache Genauigkeit.

    Die Grenzen, an denen abgeschnitten wird, liegen oft nur ein Bit von
    einem Zwischenergebnis entfernt; mit doppelter Genauigkeit kippt dann
    gelegentlich ein Zehntel.
    """

    __slots__ = ()

    def __new__(cls, value: float) -> F:
        return super().__new__(cls, _single(value))

    def __add__(self, other: float) -> F:
        return F(float(self) + float(other))

    __radd__ = __add__

    def __sub__(self, other: float) -> F:
        return F(float(self) - float(other))

    def __rsub__(self, other: float) -> F:
        return F(float(other) - float(self))

    def __mul__(self, other: float) -> F:
        return F(float(self) * float(other))

    __rmul__ = __mul__

    def __truediv__(self, other: float) -> F:
        return F(float(self) / float(other))

    def __rtruediv__(self, other: float) -> F:
        return F(float(other) / float(self))


def _scaled(value: int, factor: float) -> int:
    """value * factor, kaufmaennisch auf eine ganze Zahl gerundet."""
    return max(0, int(F(value) * F(factor) + F(0.5)))


def _u16(value: int) -> int:
    """Zehntelwerte sind vorzeichenlose 16-Bit-Zahlen."""
    return value & 0xFFFF


def _s16(value: int) -> int:
    """16-Bit-Zahl mit Vorzeichen lesen (fuer die Soll-Differenzen)."""
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _level(value: float, low: float, high: float) -> int:
    """0 = unter, 1 = im, 2 = ueber dem Referenzbereich."""
    if value < low:
        return 0
    return 1 if value < high else 2


def _level_fat(fat_rate: int, fat_rate_range: tuple[int, int]) -> int:
    """Wie _level, aber der obere Grenzwert zaehlt noch als normal."""
    if fat_rate < fat_rate_range[0]:
        return 0
    return 2 if fat_rate > fat_rate_range[1] else 1


def _shortest(value: float) -> str:
    """Kuerzeste Dezimaldarstellung, die dieselbe float32-Zahl ergibt."""
    for digits in range(1, 10):
        text = f"{value:.{digits}g}"
        if _single(float(text)) == value:
            return text
    return repr(value)


def _one_decimal(value: float) -> float:
    """float32-Wert kaufmaennisch auf eine Nachkommastelle runden."""
    rounded = Decimal(_shortest(value)).quantize(Decimal("0.1"), ROUND_HALF_UP)
    return float(rounded)


# ---------------------------------------------------------------------------
# Eingabe
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Impedances:
    """Fuenf Segment-Impedanzen einer Messfrequenz in 0,1 Ohm."""

    right_arm: int
    left_arm: int
    trunk: int
    right_leg: int
    left_leg: int

    @property
    def arms(self) -> int:
        return self.left_arm + self.right_arm

    @property
    def legs(self) -> int:
        return self.left_leg + self.right_leg

    @property
    def total(self) -> int:
        return self.arms + self.trunk + self.legs


# Die Waage misst nicht die Segmente selbst, sondern sechs Strompfade
# zwischen den vier Elektrodenpaaren. Jeder Pfad hat einen eigenen
# Kalibrierfaktor (Zeile 1: 20 kHz, Zeile 2: 100 kHz).
_PATH_GAIN = {
    20: (0.931, 0.9239, 0.9259, 0.9222, 0.9241, 0.924),
    100: (0.932, 0.9332, 0.9317, 0.9257, 0.9277, 0.9297),
}


def _calibrate(z: Impedances, gains: tuple[float, ...]) -> Impedances:
    """Segmente -> sechs Strompfade -> kalibrieren -> zurueck in Segmente."""
    paths = (
        z.right_leg + z.left_leg,  # Fuss zu Fuss
        z.right_arm + z.left_arm,  # Hand zu Hand
        z.left_arm + z.trunk + z.left_leg,  # linke Seite
        z.right_arm + z.trunk + z.right_leg,  # rechte Seite
        z.right_arm + z.trunk + z.left_leg,  # diagonal
        z.left_arm + z.trunk + z.right_leg,  # diagonal
    )
    feet, hands, left, right, diag_a, diag_b = (
        _u16(_scaled(_u16(path), gain)) for path, gain in zip(paths, gains)
    )
    calibrated = Impedances(
        right_arm=(2 * hands - left + right + diag_a - diag_b) >> 2,
        left_arm=(left + 2 * hands - right - diag_a + diag_b) >> 2,
        trunk=(left + right - hands - feet) >> 1,
        right_leg=(2 * feet - left + right - diag_a + diag_b) >> 2,
        left_leg=(left + 2 * feet - right + diag_a - diag_b) >> 2,
    )
    if min(getattr(calibrated, segment) for segment in SEGMENTS) <= 0:
        # Die zehn Werte passen nicht zueinander (z. B. Rumpf am unteren
        # Rand bei sehr hohen Arm-/Beinwerten): kein sinnvolles Ergebnis.
        raise BodyCompositionError("impedances_inconsistent")
    return calibrated


def _trunk_from_limbs(z: Impedances) -> Impedances:
    """Rumpfimpedanz stabilisieren.

    Der Rumpf hat nur wenige Ohm und ist ueber Hand- und Fusselektroden
    schlecht messbar. Der Messwert geht deshalb nur zu 40 % ein, der Rest
    wird aus Armen und Beinen geschaetzt.
    """
    trunk = (
        F(z.trunk) * F(0.4)
        + F(48.0)
        + F(z.arms) * F(0.006)
        + F(z.legs) * F(0.012)
    )
    return Impedances(z.right_arm, z.left_arm, max(0, int(trunk)), z.right_leg, z.left_leg)


def _check_ranges(age: int, z20: Impedances, z100: Impedances) -> None:
    def outside(low: int, high: int, *values: int) -> bool:
        return any(not low <= value <= high for value in values)

    if not 6 <= age <= 99:
        raise BodyCompositionError("age")
    for segment in ("right_arm", "left_arm", "right_leg", "left_leg"):
        if outside(1000, 7000, getattr(z20, segment), getattr(z100, segment)):
            raise BodyCompositionError(f"impedance_{segment}")
    if outside(50, 1000, z20.trunk, z100.trunk):
        raise BodyCompositionError("impedance_trunk")


# ---------------------------------------------------------------------------
# Ergebnis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BodyComposition:
    """Alle berechneten Werte in ueblichen Einheiten (kg, %, kcal)."""

    weight_kg: float
    bmi: float
    body_fat_percent: float
    body_fat_kg: float
    fat_free_mass_kg: float
    muscle_kg: float
    muscle_percent: float
    skeletal_muscle_kg: float
    skeletal_muscle_percent: float
    water_kg: float
    water_percent: float
    intracellular_water_kg: float
    extracellular_water_kg: float
    protein_kg: float
    protein_percent: float
    mineral_kg: float
    bone_kg: float
    body_cell_mass_kg: float
    subcutaneous_fat_kg: float
    subcutaneous_fat_percent: float
    visceral_fat: int
    waist_hip_ratio: float
    skeletal_muscle_index: float
    basal_metabolic_rate: int
    daily_calorie_intake: int
    body_score: int
    body_age: int
    body_type: int
    obesity_percent: int
    ideal_weight_kg: float
    target_weight_kg: float
    weight_control_kg: float
    fat_control_kg: float
    muscle_control_kg: float
    # je Segment: Masse in kg, Anteil am Normwert in %, Stufe 0/1/2
    segment_fat_kg: dict[str, float] = field(default_factory=dict)
    segment_fat_percent: dict[str, float] = field(default_factory=dict)
    segment_fat_level: dict[str, int] = field(default_factory=dict)
    segment_muscle_kg: dict[str, float] = field(default_factory=dict)
    segment_muscle_percent: dict[str, float] = field(default_factory=dict)
    segment_muscle_level: dict[str, int] = field(default_factory=dict)
    # Symmetrie links/rechts: 0 = ausgeglichen, 1 = leicht, 2 = deutlich
    balance: dict[str, int] = field(default_factory=dict)
    # Referenzbereiche (unten, oben) fuer Alter/Groesse/Geschlecht
    ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    # 0 = unter, 1 = im, 2 = ueber dem Referenzbereich
    levels: dict[str, int] = field(default_factory=dict)


# Koerpertyp: Fettanteil (Zeile) gegen Muskelmasse (Spalte), jeweils
# unter / im / ueber dem Referenzbereich.
BODY_TYPES = {
    1: "fat_low_muscle_low",
    2: "fat_low_muscle_normal",
    3: "fat_low_muscle_high",
    4: "fat_high_muscle_low",
    5: "fat_high_muscle_normal",
    6: "fat_high_muscle_high",
    7: "fat_normal_muscle_low",
    8: "fat_normal_muscle_normal",
    9: "fat_normal_muscle_high",
}


# Referenzbereiche als Anteil am Idealgewicht: (unten, oben) je Geschlecht.
_REFERENCE = {
    #                 Mann                Frau
    "protein": ((0.15, 0.183), (0.137, 0.1675)),
    "mineral": ((0.0512, 0.0626), (0.0463, 0.0566)),
    "muscle": ((0.722, 0.992), (0.67, 0.819)),
    "bone": ((0.043, 0.053), (0.04, 0.049)),
    "intracellular_water": ((0.3485, 0.4262), (0.3232, 0.3948)),
    "extracellular_water": ((0.2136, 0.2609), (0.199, 0.2416)),
    "body_cell_mass": ((0.4995, 0.6101), (0.4632, 0.5661)),
}


# ---------------------------------------------------------------------------
# Segmente
# ---------------------------------------------------------------------------


def _share(total: int, part: int, other: int) -> int:
    """total im Verhaeltnis part : other aufteilen (ganzzahlig)."""
    return _u16(_u16(total) * _u16(part) // (_u16(part) + _u16(other)))


def _limb_estimate(weight: int, fat: int, base: float, per_weight: float, per_fat: float) -> int:
    """Lineare Schaetzung einer Teilmasse aus Gewicht und Fettmasse."""
    estimate = int(F(base) + F(per_weight) * weight + F(per_fat) * fat)
    return max(0, _s16(estimate))


def _asymmetry(right: int, left: int) -> int:
    """Seitenunterschied als Stufe: unter 6 % / unter 12 % / darueber."""
    half_difference = abs(_s16(right) - left) // 2
    percent = _s16(half_difference * 100 // max(1, _s16(right + left)))
    return _level(percent, 6, 12)


def _percent_of_reference(masses: tuple[int, ...], references: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(
        _u16(mass * 1000 // max(1, reference))
        for mass, reference in zip(masses, references)
    )


def _segment_fat(weight: int, fat: int, z100: Impedances) -> tuple[int, ...]:
    """Fettmasse je Segment (RA, LA, Rumpf, RB, LB) in 0,1 kg.

    Arme und Beine werden als Paar geschaetzt und dann nach Impedanz
    verteilt: das Glied mit der hoeheren Impedanz traegt mehr Fett.
    """
    arms = _limb_estimate(weight, fat, -0.01, 0.008, 0.0945)
    legs = _limb_estimate(weight, fat, -2.247, 0.0004, 0.284)
    trunk = _limb_estimate(weight, fat, -3.001, 0.002, 0.522)
    left_leg = _share(legs, z100.left_leg, z100.right_leg)
    right_leg = _share(legs, z100.right_leg, z100.left_leg)
    left_arm = _share(arms, z100.left_arm, z100.right_arm)
    right_arm = _share(arms, z100.right_arm, z100.left_arm)
    remainder = _u16(fat - left_leg - right_leg - left_arm - right_arm)
    if trunk > remainder:
        trunk = _u16(remainder - 5)
    return right_arm, left_arm, trunk, right_leg, left_leg


def _segment_muscle(weight: int, fat: int, muscle: int, z100: Impedances) -> tuple[int, ...]:
    """Muskelmasse je Segment (RA, LA, Rumpf, RB, LB) in 0,1 kg.

    Verteilung umgekehrt zum Fett: das Glied mit der niedrigeren Impedanz
    (mehr leitfaehiges Gewebe) bekommt den groesseren Anteil.
    """
    arms = _limb_estimate(weight, fat, -3.078, 0.113, -0.123)
    legs = _limb_estimate(weight, fat, -0.721, 0.333, -0.369)
    trunk = _limb_estimate(weight, fat, -0.96, 0.437, -0.414)
    left_leg = _share(legs, z100.right_leg, z100.left_leg)
    right_leg = _share(legs, z100.left_leg, z100.right_leg)
    left_arm = _share(arms, z100.right_arm, z100.left_arm)
    right_arm = _share(arms, z100.left_arm, z100.right_arm)
    remainder = _u16(muscle - left_leg - right_leg - left_arm - right_arm)
    if trunk > remainder:
        trunk = _u16(remainder - 10)
    return right_arm, left_arm, trunk, right_leg, left_leg


def _reference_masses(
    typical: int, weight: int, arm: tuple[float, ...], leg: tuple[float, ...], trunk: tuple[float, ...]
) -> tuple[int, ...]:
    """Normwerte je Segment (RA, LA, Rumpf, RB, LB), mindestens 0,1 kg."""

    def reference(base: float, per_typical: float, per_weight: float) -> int:
        value = int(F(base) + F(per_typical) * typical + F(per_weight) * weight)
        return max(1, _s16(value))

    return reference(*arm), reference(*arm), reference(*trunk), reference(*leg), reference(*leg)


# ---------------------------------------------------------------------------
# Hauptrechnung
# ---------------------------------------------------------------------------


def _body_age_from_bmi(bmi: float, age: int) -> int:
    """Koerperalter, wie es die App anzeigt: Abstand des BMI von 22."""
    bmi32, base = F(bmi), F(age) - F(5.0)
    estimate: float = base
    if bmi32 < 22.0:
        estimate = base + (F(22.0) - bmi32) * F(1.4285715)
        if abs(estimate - F(age)) >= 5.0:
            estimate = F(age) + F(5.0)
    elif bmi32 > 22.0:
        estimate = (bmi32 - F(22.0)) * F(1.7241381) + base
        if abs(estimate - F(age)) >= 8.0:
            estimate = F(age) + F(8.0)
    return int(F(estimate) + F(0.005))


def _lift_low_fat(percent: float) -> float:
    """Sehr niedrige Fettanteile hebt die App an (unter 10 %)."""
    for threshold, bonus in ((10, 0), (6, 3), (5, 4), (3, 5), (2, 6), (1, 7)):
        if percent >= threshold:
            return round(percent + bonus, 1)
    return round(percent + 8, 1)


def compute(
    sex: Sex,
    age: int,
    height_cm: int,
    weight_kg: float,
    z20_ohm: dict[str, float],
    z100_ohm: dict[str, float],
) -> BodyComposition:
    """Koerperzusammensetzung fuer eine vollstaendige Messung berechnen.

    z20_ohm / z100_ohm: Impedanzen in Ohm je Segment (Schluessel wie
    SEGMENTS). Wirft BodyCompositionError, wenn ein Wert ausserhalb des
    Bereichs liegt, fuer den die Formeln gedacht sind.
    """
    male = Sex(sex) is Sex.MALE
    pick = (lambda pair: pair[0]) if male else (lambda pair: pair[1])
    height = int(height_cm)
    weight = int(F(weight_kg) * F(10.0))  # 0,1 kg, abgeschnitten

    if not 100 <= weight <= 3000:
        raise BodyCompositionError("weight")
    if not 90 <= height <= 220:
        raise BodyCompositionError("height")
    z20 = Impedances(*(round(z20_ohm[segment] * 10) for segment in SEGMENTS))
    z100 = Impedances(*(round(z100_ohm[segment] * 10) for segment in SEGMENTS))
    _check_ranges(age, z20, z100)

    z20 = _trunk_from_limbs(_calibrate(z20, _PATH_GAIN[20]))
    z100 = _trunk_from_limbs(_calibrate(z100, _PATH_GAIN[100]))

    height_m2 = F(height) * F(height) / F(10000.0)
    bmi = max(0, int(F(weight) / height_m2))  # 0,1 kg/m2
    ideal = _scaled(220 if male else 210, height_m2)  # BMI 22 bzw. 21
    weight_low = _scaled(ideal, 0.85)
    weight_high = 2 * ideal - weight_low

    # --- Koerperwasser: Kern des Modells -------------------------------
    # Leitfaehig ist im Koerper vor allem Wasser; Groesse^2 / Impedanz ist
    # das klassische Mass fuer das leitfaehige Volumen eines Segments.
    estimate = (
        F(542.736)
        - F(6.152) * height
        + F(0.246) * weight
        + height_m2 * F(-3350.0) / z20.trunk
        + height_m2 * F(8560.0) / z100.trunk
        + height_m2 * F(-35040.0) / z20.arms
        + height_m2 * F(-822210.0) / z20.legs
        + height_m2 * F(266460.0) / z100.arms
        + height_m2 * F(807250.0) / z100.legs
        + height_m2 * F(201.221)
    )
    estimate = estimate - F(0.445) * bmi
    # plausibel halten: zwischen 25 % und 72,5 % des Gewichts
    estimate = min(estimate, F(_scaled(weight, 0.725)))
    estimate = max(estimate, F(_scaled(weight, 0.25)))
    water = _u16(int(estimate + F(0.5)))

    # --- Fettfreie Masse (73,3 % davon sind Wasser) und Fett ------------
    fat_free = min(_u16(int(estimate / F(0.733) + F(0.5))), _scaled(weight, 0.97))
    fat = _u16(weight - fat_free)
    fat_rate = _u16(fat * 1000 // weight)
    if male:
        fat_low = _scaled(ideal, 0.12)
        fat_high = 2 * fat_low
        fat_rate_range = (100, 200)
    else:
        fat_low, fat_high = _scaled(ideal, 0.2), _scaled(ideal, 0.32)
        fat_rate_range = (180, 280)

    # --- Aufteilung der fettfreien Masse --------------------------------
    protein = _u16(int(F(_u16(_scaled(water, 0.275))) + F(-1.36)))
    mineral = _u16(weight - water - fat - protein)
    muscle = _u16(water + protein)
    bone = _u16(int(F(mineral) * F(0.812) + F(-0.24)))
    skeletal_muscle = _u16(
        int(F(0.64763) * fat_free + F(10.554) - F(0.01407) * weight - F(0.2786) * height)
    )
    # Bei 100 kHz dringt der Strom in die Zellen ein, bei 20 kHz kaum:
    # das Verhaeltnis der Impedanzen trennt Zell- und Aussenwasser.
    cell_share = F(z20.total) / F(z100.total) * F(0.87)
    intracellular = _u16(int(cell_share * F(0.631) * F(water)))
    extracellular = _u16(water - intracellular)
    cell_mass = _u16(int(F(water) * F(0.905) + F(-1.96)))

    # --- Viszerales und subkutanes Fett ---------------------------------
    if male:
        visceral_estimate = (
            F(0.809)
            + F(-0.074) * z20.trunk
            + F(0.0652) * z100.trunk
            + F(0.026) * fat_rate
            + F(0.0067) * weight
        )
    else:
        visceral_estimate = (
            F(-7.215)
            + F(-0.013) * z20.trunk
            + F(-0.003) * z100.trunk
            + F(0.031) * fat_rate
            + F(0.0174) * weight
        )
    visceral = int(visceral_estimate) & 0xFF if visceral_estimate >= 1.0 else 1
    subcutaneous = _u16(int(F(fat) + F(visceral) * F(-2.7647)))
    subcutaneous_rate = _u16(subcutaneous * 1000 // weight)
    subcutaneous_rate_range = (86, 167) if male else (185, 267)

    # --- Energie, Kennzahlen --------------------------------------------
    metabolic_rate = _u16(int(F(fat_free) * F(2.16) + F(370.0)))
    calorie_intake = _u16(int(F(metabolic_rate) * F(1.3)))
    obesity = _u16(weight * 100 // ideal)
    score = 0xFF & int(
        F(weight) * F(0.137)
        + F(44.998)
        + F(fat_rate) * F(0.076)
        + F(weight_low) * F(-0.096)
        + F(fat) * F(-0.3)
        + F(fat_rate_range[0]) * F(0.057)
        + F(fat_low) * F(0.12)
    )
    waist_hip = 0xFF & int(F(0.206) * bmi + F(1.129) + F(0.158) * z100.trunk)

    muscle_low = _scaled(ideal, pick(_REFERENCE["muscle"])[0])
    muscle_high = _scaled(ideal, pick(_REFERENCE["muscle"])[1])
    fat_row = {0: 0, 1: 6, 2: 3}[_level_fat(fat_rate, fat_rate_range)]
    body_type = fat_row + 1 + _level(muscle, muscle_low, muscle_high)

    # --- Empfehlungen: wie viel Fett ab-, wie viel Muskel aufbauen? ------
    if male:
        fat_free_goal = _s16(int(F(ideal) * F(0.8487) + F(0.837)))
        target_fat_share = F(0.15)
    else:
        fat_free_goal = _s16(int(F(ideal) * F(0.7581) + F(6.5651)))
        target_fat_share = F(0.23)
    muscle_control = fat_free_goal - fat_free if fat_free <= fat_free_goal else 0
    fat_control = _s16(
        int(
            (target_fat_share * F(weight + muscle_control) - F(fat))
            / (F(1.0) - target_fat_share)
        )
    )
    weight_control = _s16(muscle_control + fat_control)
    target_weight = _u16(weight + weight_control)

    # --- Segmente --------------------------------------------------------
    seg_fat = _segment_fat(weight, fat, z100)
    seg_fat_pct = _percent_of_reference(
        seg_fat,
        _reference_masses(
            _u16((fat_low + fat_high) // 2),
            weight,
            arm=(-4.33, 0.109, -0.003),
            leg=(-6.73, 0.231, -0.005),
            trunk=(-3.22, 0.393, -0.002),
        ),
    )
    seg_muscle = _segment_muscle(weight, fat, muscle, z100)
    fat_free_low, fat_free_high = _u16(weight_low - fat_low), _u16(weight_high - fat_high)
    seg_muscle_pct = _percent_of_reference(
        seg_muscle,
        _reference_masses(
            _u16((fat_free_low + fat_free_high) // 2),
            weight,
            arm=(-13.86, 0.057, 0.019),
            leg=(-15.96, 0.109, 0.059),
            trunk=(-45.25, 0.316, 0.166),
        ),
    )
    seg_fat_level = tuple(_level(value, 800, 1600) for value in seg_fat_pct)
    seg_muscle_level = tuple(
        _level(value, *((800, 1200) if index < 2 else (900, 1100)))
        for index, value in enumerate(seg_muscle_pct)
    )
    limb_muscle = seg_muscle[0] + seg_muscle[1] + seg_muscle[3] + seg_muscle[4]
    muscle_index = 0xFF & int(float(_u16(limb_muscle)) / float(height_m2))
    arms_vs_legs = seg_muscle_level[0] + seg_muscle_level[1] - seg_muscle_level[3] - seg_muscle_level[4]

    # --- Ausgabe in ueblichen Einheiten ----------------------------------
    def tenths(value: int) -> float:
        return value / 10

    weight_exact = F(weight_kg)
    fat_percent = _lift_low_fat(tenths(fat_rate))
    shown_bmi = max(10.0, tenths(bmi))

    def ideal_range(name: str) -> tuple[float, float]:
        low, high = pick(_REFERENCE[name])
        return tenths(_scaled(ideal, low)), tenths(_scaled(ideal, high))

    water_mid = _scaled(ideal, 0.6234 if male else 0.5655)
    water_low = _scaled(water_mid, 0.9)
    if male:
        skeletal_range = (_scaled(ideal, 0.453) - 17, _scaled(ideal, 0.551) - 19)
        metabolic_range = (_scaled(weight, 1.6524) + 370, _scaled(weight, 2.0195) + 370)
    else:
        skeletal_range = (_scaled(ideal, 0.4) - 13, _scaled(ideal, 0.49) - 16)
        metabolic_range = (_scaled(weight, 1.4968) + 370, _scaled(weight, 1.8295) + 370)

    ranges: dict[str, tuple[float, float]] = {
        "bmi": (18.5, 23.0),
        "weight_kg": (tenths(weight_low), tenths(weight_high)),
        "body_fat_percent": (tenths(fat_rate_range[0]), tenths(fat_rate_range[1])),
        "body_fat_kg": (tenths(fat_low), tenths(fat_high)),
        "fat_free_mass_kg": (tenths(fat_free_low), tenths(fat_free_high)),
        "water_kg": (tenths(water_low), tenths(2 * water_mid - water_low)),
        "protein_kg": ideal_range("protein"),
        "mineral_kg": ideal_range("mineral"),
        "muscle_kg": ideal_range("muscle"),
        "bone_kg": ideal_range("bone"),
        "skeletal_muscle_kg": (tenths(skeletal_range[0]), tenths(skeletal_range[1])),
        "intracellular_water_kg": ideal_range("intracellular_water"),
        "extracellular_water_kg": ideal_range("extracellular_water"),
        "body_cell_mass_kg": ideal_range("body_cell_mass"),
        "subcutaneous_fat_percent": (
            tenths(subcutaneous_rate_range[0]),
            tenths(subcutaneous_rate_range[1]),
        ),
        "subcutaneous_fat_kg": (
            tenths(subcutaneous_rate_range[0] * ideal // 1000),
            tenths(subcutaneous_rate_range[1] * ideal // 1000),
        ),
        "visceral_fat": (1, 9),
        "waist_hip_ratio": (0.8, 0.9) if male else (0.75, 0.85),
        "basal_metabolic_rate": (float(metabolic_range[0]), float(metabolic_range[1])),
        "obesity_percent": (90, 110),
    }
    values = {
        "bmi": tenths(bmi),
        "weight_kg": tenths(weight),
        "body_fat_percent": tenths(fat_rate),
        "body_fat_kg": tenths(fat),
        "fat_free_mass_kg": tenths(fat_free),
        "water_kg": tenths(water),
        "protein_kg": tenths(protein),
        "mineral_kg": tenths(mineral),
        "muscle_kg": tenths(muscle),
        "bone_kg": tenths(bone),
        "skeletal_muscle_kg": tenths(skeletal_muscle),
        "intracellular_water_kg": tenths(intracellular),
        "extracellular_water_kg": tenths(extracellular),
        "body_cell_mass_kg": tenths(cell_mass),
        "subcutaneous_fat_percent": tenths(subcutaneous_rate),
        "subcutaneous_fat_kg": tenths(subcutaneous),
        "visceral_fat": visceral,
        "waist_hip_ratio": waist_hip / 100,
        "basal_metabolic_rate": metabolic_rate,
        "obesity_percent": obesity,
    }
    levels = {name: _level(values[name], *ranges[name]) for name in ranges}

    return BodyComposition(
        weight_kg=tenths(weight),
        bmi=shown_bmi,
        body_fat_percent=fat_percent,
        body_fat_kg=tenths(fat)
        if fat_rate >= 100
        else _one_decimal(F(fat_percent) * weight_exact * F(0.01)),
        fat_free_mass_kg=tenths(fat_free),
        muscle_kg=tenths(muscle),
        muscle_percent=_one_decimal(F(tenths(muscle)) / weight_exact * F(100.0)),
        skeletal_muscle_kg=tenths(skeletal_muscle),
        skeletal_muscle_percent=tenths(_u16(skeletal_muscle * 1000 // weight)),
        water_kg=tenths(water),
        water_percent=_one_decimal(F(tenths(water)) / weight_exact * F(100.0)),
        intracellular_water_kg=tenths(intracellular),
        extracellular_water_kg=tenths(extracellular),
        protein_kg=tenths(protein),
        protein_percent=tenths(_u16(protein * 1000 // weight)),
        mineral_kg=tenths(mineral),
        bone_kg=tenths(bone),
        body_cell_mass_kg=tenths(cell_mass),
        subcutaneous_fat_kg=tenths(subcutaneous),
        subcutaneous_fat_percent=tenths(subcutaneous_rate),
        visceral_fat=visceral,
        waist_hip_ratio=waist_hip / 100,
        skeletal_muscle_index=tenths(muscle_index),
        basal_metabolic_rate=metabolic_rate,
        daily_calorie_intake=calorie_intake,
        body_score=score,
        body_age=_body_age_from_bmi(shown_bmi, age),
        body_type=body_type,
        obesity_percent=obesity,
        ideal_weight_kg=tenths(ideal),
        target_weight_kg=tenths(target_weight),
        weight_control_kg=tenths(weight_control),
        fat_control_kg=tenths(fat_control),
        muscle_control_kg=tenths(muscle_control),
        segment_fat_kg=dict(zip(SEGMENTS, map(tenths, seg_fat))),
        segment_fat_percent=dict(zip(SEGMENTS, map(tenths, seg_fat_pct))),
        segment_fat_level=dict(zip(SEGMENTS, seg_fat_level)),
        segment_muscle_kg=dict(zip(SEGMENTS, map(tenths, seg_muscle))),
        segment_muscle_percent=dict(zip(SEGMENTS, map(tenths, seg_muscle_pct))),
        segment_muscle_level=dict(zip(SEGMENTS, seg_muscle_level)),
        balance={
            "muscle_arms": _asymmetry(seg_muscle[0], seg_muscle[1]),
            "muscle_legs": _asymmetry(seg_muscle[3], seg_muscle[4]),
            "muscle_arms_vs_legs": _level(arms_vs_legs, 3, 4),
            "fat_arms": _asymmetry(seg_fat[0], seg_fat[1]),
            "fat_legs": _asymmetry(seg_fat[3], seg_fat[4]),
        },
        ranges=ranges,
        levels=levels,
    )
