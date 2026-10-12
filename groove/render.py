"""Turn step patterns into audio (so fill ideas can be heard in a browser,
which can't play MIDI), and make web-friendly copies of recordings."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .meter import FOUR_FOUR, Meter
from .midi import steps_tick, TPB
from .synth import VOICES
from .transcribe import SR

# Pattern instrument -> the built-in drum sound used to play it, and a level.
SOUND = {
    "kick": ("kick", 1.0), "snare": ("snare", 1.0), "rim": ("snare", 0.4),
    "hihat": ("hihat", 0.8), "hihat_closed": ("hihat", 0.8), "hihat_open": ("hihat", 1.0),
    "hihat_pedal": ("hihat", 0.5), "tom_high": ("tom_high", 0.9), "tom_mid": ("tom_mid", 0.9),
    "tom_floor": ("tom_floor", 0.9), "crash": ("crash", 0.8), "ride": ("hihat", 0.7),
}
STEP_LEVEL = {"X": 1.0, "x": 0.75, "g": 0.3}


def render_bars(bars: list[dict[str, str]], bpm: float, meter: Meter = FOUR_FOUR,
                s8: float = 0.5, s16: float = 0.5) -> np.ndarray:
    """Audio for bars of {instrument: step string}, laid end to end. bpm counts the meter's beat."""
    rng = np.random.default_rng(0)
    sec_per_tick = 60.0 / (bpm * meter.beat_quarters) / TPB
    bar_ticks = steps_tick(meter.steps_per_bar, s8, s16, meter)
    y = np.zeros(int((len(bars) * bar_ticks * sec_per_tick + 1.5) * SR))
    for b, bar in enumerate(bars):
        for inst, steps in bar.items():
            voice, level = SOUND.get(inst, ("snare", 0.6))
            for i, ch in enumerate(steps):
                if ch not in STEP_LEVEL:
                    continue
                t = (b * bar_ticks + steps_tick(i, s8, s16, meter)) * sec_per_tick
                s = VOICES[voice](rng) * level * STEP_LEVEL[ch]
                start = int(t * SR)
                y[start : start + len(s)] += s[: max(0, len(y) - start)]
    peak = np.abs(y).max()
    return (0.9 * y / peak).astype(np.float32) if peak > 0 else y.astype(np.float32)


def save_web_audio(y: np.ndarray, path: Path) -> Path:
    """Save audio as a small .m4a (AAC) on macOS, else .wav. Returns the file written."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        sf.write(wav, y, SR)
        return compress(wav, path)


def compress(wav: Path, path: Path) -> Path:
    """Web-friendly copy of a WAV: AAC .m4a via macOS afconvert (about 1 MB/minute)."""
    out = path.with_suffix(".m4a")
    if sys.platform == "darwin":
        r = subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "128000", str(wav), str(out)],
                           capture_output=True)
        if r.returncode == 0:
            return out
    out = path.with_suffix(".wav")
    if Path(wav).resolve() != out.resolve():
        out.write_bytes(Path(wav).read_bytes())
    return out
