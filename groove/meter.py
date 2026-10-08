"""Time signatures: how a bar divides into beats and grid slots, and how to count it.

  * x/4 (2/4, 3/4, 4/4, 5/4, 7/4): quarter-note beats, 16th-note grid (4 slots per beat), "1 e & a".
  * compound x/8 (6/8, 9/8, 12/8): dotted-quarter beats, each three 8ths, 16th grid
    (6 slots per beat), counted by 8ths: "1 & 2 & 3 & 4 & 5 & 6 &".
  * other x/8 (5/8, 7/8): 8th-note beats, 16th grid (2 slots per beat).

Tempos (bpm) always count the meter's beat: quarter notes in 4/4, dotted
quarters in 6/8. `beat_bpm` converts a metronome set to another note value.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NOTE_QUARTERS = {"quarter": 1.0, "eighth": 0.5, "dotted-quarter": 1.5}


@dataclass(frozen=True)
class Meter:
    num: int
    den: int

    @staticmethod
    def parse(text: str) -> "Meter":
        try:
            num, den = (int(x) for x in text.strip().split("/"))
        except ValueError:
            raise ValueError(f"Time signature should look like 4/4 or 6/8, not '{text}'.") from None
        if den not in (4, 8) or not 2 <= num <= 15:
            raise ValueError(f"Unsupported time signature {text}: use x/4 or x/8 (e.g. 3/4, 4/4, 6/8, 7/8, 12/8).")
        return Meter(num, den)

    @property
    def name(self) -> str:
        return f"{self.num}/{self.den}"

    @property
    def compound(self) -> bool:
        return self.den == 8 and self.num % 3 == 0 and self.num >= 6

    @property
    def beats(self) -> int:
        """Felt beats per bar (6/8 has 2)."""
        return self.num // 3 if self.compound else self.num

    @property
    def slots(self) -> int:
        """16th-note grid slots per beat."""
        return 6 if self.compound else 4 if self.den == 4 else 2

    @property
    def steps_per_bar(self) -> int:
        return self.beats * self.slots

    @property
    def beat_quarters(self) -> float:
        return 1.5 if self.compound else 1.0 if self.den == 4 else 0.5

    @property
    def beat_note(self) -> str:
        return "dotted quarter" if self.compound else "quarter note" if self.den == 4 else "eighth note"

    @property
    def swingable(self) -> bool:
        """Swing % only makes sense for straight 8ths/16ths (x/4)."""
        return self.den == 4

    def template(self, s8: float = 0.5, s16: float = 0.5) -> np.ndarray:
        """Slot positions within one beat (in beats), plus 1.0 for the next beat."""
        if self.swingable:
            return np.array([0.0, s16 * s8, s8, s8 + s16 * (1 - s8), 1.0])
        return np.arange(self.slots + 1) / self.slots

    def count_labels(self) -> list[str]:
        """Count syllable for each 16th slot in a bar."""
        out = []
        for b in range(self.beats):
            for k in range(self.slots):
                if self.den == 4:
                    out.append(str(b + 1) if k == 0 else ["", "e", "&", "a"][k])
                elif self.compound:
                    out.append(str(b * 3 + k // 2 + 1) if k % 2 == 0 else "&")
                else:
                    out.append(str(b + 1) if k == 0 else "&")
        return out

    def count_name(self, slot_in_bar: int) -> str:
        """Readable position, e.g. '3', 'e of 2', '& of 4'."""
        label = self.count_labels()[slot_in_bar]
        if label.isdigit():
            return label
        # the number this syllable belongs to: nearest numbered slot before it
        prev = next(l for l in reversed(self.count_labels()[:slot_in_bar]) if l.isdigit())
        return f"{label} of {prev}"

    def position_groups(self) -> list[tuple[str, set[int]]]:
        """Groups of slot-within-beat indices for the 'by count' chart."""
        if self.den == 4:
            return [("downbeats", {0}), ("e", {1}), ("&", {2}), ("a", {3})]
        if self.compound:
            main = ", ".join(str(b * 3 + 1) for b in range(self.beats))
            return [(f"beats ({main})", {0}), ("2nd 8ths", {2}), ("3rd 8ths", {4}), ("16th &s", {1, 3, 5})]
        return [("8th notes", {0}), ("16th &s", {1})]

    def beat_bpm(self, bpm: float, note: str | None) -> float:
        """Convert a tempo counted in `note` ('quarter', 'eighth', 'dotted-quarter') to beats per minute."""
        if not note or note == "beat":
            return bpm
        return bpm * NOTE_QUARTERS[note] / self.beat_quarters


FOUR_FOUR = Meter(4, 4)
