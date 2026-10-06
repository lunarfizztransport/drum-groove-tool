"""Recording with an optional click track, and round-trip latency calibration.

Wear headphones for the click when recording: if the click comes out of
speakers the mic picks it up and it gets transcribed as hits.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from .transcribe import SR, transcribe

CONFIG = Path.home() / ".config" / "groove-tool" / "latency.json"


def click_track(bpm: float, beats: int, beats_per_bar: int = 4, tail: float = 1.0) -> np.ndarray:
    beat = 60.0 / bpm
    y = np.zeros(int((beats * beat + tail) * SR), dtype=np.float32)
    t = np.arange(int(0.03 * SR)) / SR
    for i in range(beats):
        freq = 1600 if i % beats_per_bar == 0 else 1000
        blip = 0.6 * np.sin(2 * np.pi * freq * t) * np.exp(-t * 120)
        start = int(round(i * beat * SR))
        y[start : start + len(blip)] += blip
    return y


def load_latency() -> float:
    try:
        return json.loads(CONFIG.read_text())["latency_s"]
    except (OSError, KeyError, ValueError):
        return 0.0


def record(path: str, bpm: float | None, bars: int, beats_per_bar: int = 4, count_in_bars: int = 1) -> dict:
    """Record to `path`. With bpm set, plays a click and writes `path`.json with the grid."""
    import sounddevice as sd

    if bpm:
        beat = 60.0 / bpm
        click = click_track(bpm, (bars + count_in_bars) * beats_per_bar, beats_per_bar)
        print(f"Count-in: {count_in_bars} bar(s) at {bpm} bpm, then play {bars} bars. Headphones on!")
        audio = sd.playrec(click, samplerate=SR, channels=1, dtype="float32")
    else:
        beat = None
        seconds = bars * beats_per_bar * 0.6 + 2  # ~100 bpm guess when no tempo given
        print(f"Recording {seconds:.0f}s without a click. Go!")
        audio = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    sf.write(path, audio[:, 0], SR)

    meta = {"beats_per_bar": beats_per_bar}
    if bpm:
        latency = load_latency()
        meta.update(
            bpm=bpm,
            # Where beat 1 of the first real bar lands in the file, after latency.
            origin=count_in_bars * beats_per_bar * beat + latency,
            latency_s=latency,
        )
        Path(path + ".json").write_text(json.dumps(meta, indent=2))
    print(f"Saved {path}")
    return meta


def calibrate(bpm: float = 100, beats: int = 12) -> float:
    """Play clicks through the speakers and record them with the mic.

    The measured offset includes audio output + input latency and the onset
    detector's own bias, which is exactly what needs subtracting when you
    play along to the click. Turn speaker volume up; no headphones.
    """
    import sounddevice as sd

    click = click_track(bpm, beats)
    print("Calibrating: playing clicks through the speakers. Stay quiet...")
    audio = sd.playrec(click, samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    tmp = CONFIG.with_name("calibration.wav")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    sf.write(tmp, audio[:, 0], SR)

    onsets = np.array(sorted({h.time for h in transcribe(str(tmp), mode="generic").hits}))
    expected = np.arange(beats) * 60.0 / bpm
    diffs = []
    for e in expected:
        later = onsets[(onsets >= e) & (onsets < e + 0.25)]
        if len(later):
            diffs.append(later[0] - e)
    if len(diffs) < beats // 2:
        raise RuntimeError(f"Only heard {len(diffs)}/{beats} clicks; turn the volume up and try again.")
    latency = float(np.median(diffs))
    CONFIG.write_text(json.dumps({"latency_s": latency, "clicks_heard": len(diffs)}, indent=2))
    print(f"Round-trip latency: {latency * 1000:.1f} ms (spread {np.std(diffs) * 1000:.1f} ms). Saved to {CONFIG}")
    return latency
