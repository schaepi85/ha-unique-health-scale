# Berechnung der Körperwerte

Die Waage liefert pro Messung:

- Gewicht (0,01 kg)
- je fünf Impedanzen bei 20 kHz und 100 kHz: rechter Arm, linker Arm, Rumpf, rechtes Bein, linkes Bein (0,1 Ω)
- Herzfrequenz

Dazu kommt das Profil aus Home Assistant: Geschlecht, Größe, Alter. Daraus berechnet `custom_components/unique_health_scale/bodycomp.py` alle weiteren Werte. Das Modul ist eine eigenständig geschriebene Nachbildung der Schätzformeln, mit denen auch die App rechnet; es enthält keinen Code des Herstellers.

## Ablauf

1. **Bereichsprüfung.** Gewicht 10–300 kg, Größe 90–220 cm, Alter 6–99 Jahre, Arm- und Beinimpedanzen 100–700 Ω, Rumpf 5–100 Ω. Außerhalb gibt es kein Ergebnis (`BodyCompositionError`, sichtbar im Attribut `body_composition` des Rohdaten-Sensors).
2. **Kalibrierung.** Die Waage misst eigentlich sechs Strompfade zwischen den vier Elektrodenpaaren (Hand–Hand, Fuß–Fuß, zwei Seiten, zwei Diagonalen). Die fünf Segmentwerte werden in diese Pfade zurückgerechnet, jeder Pfad mit einem gerätespezifischen Faktor (rund 0,92–0,93) multipliziert und wieder in Segmente zerlegt.
3. **Rumpf stabilisieren.** Der Rumpf hat nur wenige Ohm und ist über Hände und Füße schlecht messbar. Der Messwert geht zu 40 % ein, der Rest wird aus Armen und Beinen geschätzt.
4. **Körperwasser** ist der Kern: eine lineare Formel aus Größe, Gewicht, BMI und den Termen Größe²/Impedanz für Arme, Beine und Rumpf bei beiden Frequenzen, begrenzt auf 25–72,5 % des Gewichts.
5. **Fettfreie Masse** = Wasser / 0,733 (höchstens 97 % des Gewichts), **Fett** = Gewicht − fettfreie Masse.
6. **Aufteilung:** Protein ≈ 27,5 % des Wassers, Mineralien = Rest der fettfreien Masse, Muskelmasse = Wasser + Protein, Knochen ≈ 81 % der Mineralien. Intra-/extrazelluläres Wasser folgt aus dem Verhältnis der 20-kHz- zu den 100-kHz-Impedanzen.
7. **Kennzahlen:** Viszeralfett (aus Rumpfimpedanz, Fettanteil, Gewicht), Unterhautfett, Grundumsatz (aus fettfreier Masse), Taille-Hüft-Verhältnis, Körperpunktzahl, Körpertyp, Soll-Differenzen für Fett und Muskeln.
8. **Segmente:** Fett und Muskeln werden für Armpaar, Beinpaar und Rumpf aus Gewicht und Fettmasse geschätzt und nach dem Impedanzverhältnis auf links/rechts verteilt.
9. **Wie in der App angezeigt:** Fettanteile unter 10 % werden angehoben, Wasser- und Muskelanteil beziehen sich auf das genaue Gewicht, das Körperalter folgt aus dem Abstand des BMI von 22.

## Rechengenauigkeit

Damit die Zahlen zu denen der App passen, rechnet das Modul wie diese in einfacher Genauigkeit (float32) und mit ganzzahligen Zehnteln; Zwischenergebnisse werden abgeschnitten, nicht gerundet. Geprüft wurde das mit mehreren tausend zufälligen Eingaben gegen die Berechnung der App, ohne Abweichung. Die mitgelieferten Sollwerte (`tests/bodycomp_golden.json`) sind erfundene Messungen aus diesem Abgleich.

Eine bewusste Abweichung: Passen die zehn Impedanzen nicht zueinander (nach der Kalibrierung ergäbe sich ein Segment ≤ 0 Ω), liefert das Modul einen Fehler statt unsinniger Zahlen.

## Grenzen

- Schätzwerte, keine medizinischen Messwerte. Tagesform, Trinkmenge und feuchte oder trockene Haut verschieben die Impedanzen spürbar.
- Die Kalibrierfaktoren gelten für die `smart scale P1` (Lefu CF597).
- Jede Person rechnet mit ihrem eigenen Profil; die Zuordnung einer Wiegung zur Person erfolgt über das Gewicht (siehe README).
