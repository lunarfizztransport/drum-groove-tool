"""MIDI export for transcriptions and suggested patterns (General MIDI drums,
channel 10). Open the .mid files in GarageBand / any DAW to hear them."""

from __future__ import annotations

import mido

from .meter import FOUR_FOUR, Meter

TPB = 480  # ticks per beat
GM = {
    "kick": 36, "snare": 38, "rim": 37, "hihat": 42, "hihat_closed": 42,
    "hihat_open": 46, "hihat_pedal": 44, "ride": 51, "crash": 49,
    "tom_high": 50, "tom_mid": 47, "tom_floor": 43, "hit": 37,
}
STEP_VELOCITY = {"X": 118, "x": 92, "g": 40}


def _write(events: list[tuple[int, int, int]], quarter_bpm: float, path: str, meter: Meter) -> None:
    """events: (tick, note, velocity). Writes note-on + short note-off pairs."""
    mid = mido.MidiFile(ticks_per_beat=TPB)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(quarter_bpm), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=meter.num, denominator=meter.den, time=0))
    msgs = []
    for tick, note, vel in events:
        msgs.append((tick, 1, mido.Message("note_on", channel=9, note=note, velocity=vel)))
        msgs.append((tick + TPB // 8, 0, mido.Message("note_off", channel=9, note=note, velocity=0)))
    msgs.sort(key=lambda m: (m[0], m[1]))
    last = 0
    for tick, _, msg in msgs:
        track.append(msg.copy(time=tick - last))
        last = tick
    mid.save(path)


def hits_to_midi(hits, bpm: float, path: str, meter: Meter = FOUR_FOUR) -> None:
    """Transcribed hits at their real (unquantized) times. bpm counts the meter's beat."""
    q = bpm * meter.beat_quarters
    events = [(int(round(h.time * q / 60 * TPB)), GM.get(h.instrument, 37), h.velocity) for h in hits]
    _write(events, q, path, meter)


def steps_tick(step: int, s8: float = 0.5, s16: float = 0.5, meter: Meter = FOUR_FOUR) -> int:
    """16th step index -> tick, applying the player's measured swing (x/4 only)."""
    if not meter.swingable:
        return step * TPB // 4  # straight 16ths
    beat, k = divmod(step, 4)
    frac = [0.0, s16 * s8, s8, s8 + s16 * (1 - s8)][k]
    return int(round((beat + frac) * TPB))


def patterns_to_midi(bars: list[dict[str, str]], bpm: float, path: str, s8=0.5, s16=0.5,
                     meter: Meter = FOUR_FOUR) -> None:
    """bars: list of {instrument: step string}; each bar is laid end to end. bpm counts the meter's beat."""
    events, offset = [], 0
    for bar in bars:
        for inst, steps in bar.items():
            for i, ch in enumerate(steps):
                if ch in STEP_VELOCITY:
                    events.append((offset + steps_tick(i, s8, s16, meter), GM.get(inst, 37), STEP_VELOCITY[ch]))
        offset += steps_tick(meter.steps_per_bar, s8, s16, meter)
    _write(events, bpm * meter.beat_quarters, path, meter)
