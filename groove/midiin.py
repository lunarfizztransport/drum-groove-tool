"""E-kits over MIDI: exact hits instead of guessing from audio.

An e-kit's module (e.g. Alesis Nitro) sends a MIDI note for every pad hit
over USB: which pad, how hard, and exactly when. That skips onset detection
and drum labelling entirely. Recording here also plays the click from the
same computer clock, so "ahead of / behind the click" is measured exactly.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import mido

from .meter import FOUR_FOUR, Meter
from .transcribe import SR, Hit

# Pad note numbers -> drum names. Alesis Nitro defaults (Nitro Max user guide,
# section 5.2 "Pad MIDI Note Numbers"), which also match General MIDI drums,
# so most other e-kits work too.
NOTE_MAP = {
    35: "kick", 36: "kick",
    38: "snare", 40: "snare",  # head, rim
    37: "rim",  # cross-stick
    48: "tom_high", 50: "tom_high",  # tom 1 head, rim
    45: "tom_mid", 47: "tom_mid",  # tom 2
    43: "tom_floor", 58: "tom_floor",  # tom 3
    41: "tom_floor", 39: "tom_floor",  # tom 4
    42: "hihat", 22: "hihat",  # closed
    46: "hihat_open", 23: "hihat_open", 26: "hihat_open",  # open, half-open
    44: "hihat_pedal", 21: "hihat_pedal",  # pedal chick, splash
    49: "crash", 57: "crash", 55: "crash", 52: "crash",
    51: "ride", 59: "ride", 53: "ride",  # ride, bell
}


def hits_from_midi(path: str) -> tuple[list[Hit], dict[int, int]]:
    """Hits from a MIDI file (seconds from the start). Also returns counts of
    note numbers that aren't in NOTE_MAP, so a custom pad map can be spotted."""
    hits, unknown, t = [], {}, 0.0
    for msg in mido.MidiFile(path):  # iterating a MidiFile yields msg.time in seconds
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            name = NOTE_MAP.get(msg.note)
            if name:
                hits.append(Hit(round(t, 4), name, msg.velocity))
            else:
                unknown[msg.note] = unknown.get(msg.note, 0) + 1
    return hits, unknown


def find_port(name: str | None = None) -> str:
    """The e-kit's MIDI input: one matching `name`, else the most drum-like connected device."""
    names = mido.get_input_names()
    if name:
        match = [p for p in names if name.lower() in p.lower()]
        if not match:
            raise RuntimeError(f"No MIDI input matching '{name}'. Connected: {', '.join(names) or 'none'}")
        return match[0]
    real = [p for p in names if "virtual" not in p.lower()]  # skip e.g. GarageBand's virtual port
    drums = [p for p in real if any(k in p.lower() for k in ("nitro", "alesis", "drum", "td-", "dtx"))]
    if drums or real:
        return (drums or real)[0]
    raise RuntimeError("No e-kit found over MIDI. Connect the drum module's USB port to the Mac, "
                       "switch the module on, and try again.")


def record_midi(path: str, bpm: float, bars: int, meter: Meter = FOUR_FOUR, count_in_bars: int = 1,
                port: str | None = None) -> dict:
    """Play a click and record pad hits to `path` (.mid), with `path`.json describing the grid.

    The click can come out of the speakers: there's no microphone involved."""
    import sounddevice as sd

    from .audio import click_track

    import rtmidi

    port_name = find_port(port)
    click = click_track(bpm, (bars + count_in_bars) * meter.beats, meter)
    raw: list[tuple[float, float, list[int]]] = []  # (wall clock when handled, MIDI-driver clock, bytes)
    state = {"pos": 0, "t0": None, "clock": 0.0}
    done = threading.Event()

    def on_midi(event, _data):
        msg, delta = event  # delta: seconds since the previous message, timed by the MIDI driver
        state["clock"] += delta
        raw.append((time.perf_counter(), state["clock"], msg))

    def on_audio(outdata, frames, time_info, status):
        if state["t0"] is None:  # when the first click sample actually leaves the speakers
            state["t0"] = time.perf_counter() + (time_info.outputBufferDacTime - time_info.currentTime)
        chunk = click[state["pos"] : state["pos"] + frames]
        outdata[: len(chunk), 0] = chunk
        outdata[len(chunk) :, 0] = 0
        state["pos"] += frames
        if state["pos"] >= len(click):
            raise sd.CallbackStop

    unit = "" if meter.den == 4 else f" ({meter.beat_note}s)"
    print(f"Listening to {port_name}. Count-in: {count_in_bars} bar(s) of {meter.name} at {bpm:g} bpm{unit}, "
          f"then play {bars} bars.")
    midi_in = rtmidi.MidiIn()
    midi_in.open_port(midi_in.get_ports().index(port_name))
    midi_in.set_callback(on_midi)
    try:
        with sd.OutputStream(samplerate=SR, channels=1, dtype="float32", callback=on_audio,
                             finished_callback=done.set):
            done.wait()
    finally:
        midi_in.close_port()

    # Python may handle a hit a little late, but never early, so the smallest
    # gap between the wall clock and the driver's clock is the true offset.
    offset = min((w - c for w, c, _ in raw), default=0.0)
    events = [(offset + c, mido.Message.from_bytes(m)) for _, c, m in raw if (m[0] & 0xF0) in (0x80, 0x90)]
    t0 = state["t0"]
    _save_midi(path, [(t - t0, m) for t, m in events if t >= t0], bpm, meter)
    meta = {"time": meter.name, "beats_per_bar": meter.beats, "bpm": bpm,
            "origin": count_in_bars * meter.beats * 60.0 / bpm, "source": "midi", "port": port_name}
    Path(path + ".json").write_text(json.dumps(meta, indent=2))
    n = sum(1 for _, m in events if m.type == "note_on" and m.velocity > 0)
    print(f"Saved {n} hits to {path}")
    return meta


def _save_midi(path: str, events: list[tuple[float, mido.Message]], bpm: float, meter: Meter) -> None:
    tpb = 480
    quarter_bpm = bpm * meter.beat_quarters
    mid = mido.MidiFile(ticks_per_beat=tpb)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(quarter_bpm), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=meter.num, denominator=meter.den, time=0))
    last = 0
    for t, msg in sorted(events, key=lambda e: e[0]):
        tick = int(round(t * quarter_bpm / 60 * tpb))
        track.append(msg.copy(channel=9, time=max(0, tick - last)))
        last = max(last, tick)
    mid.save(path)
