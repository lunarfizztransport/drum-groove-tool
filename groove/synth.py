"""Synthesize a drum performance with known timing flaws, for testing the
pipeline end-to-end (and checking that the analysis finds what we planted)."""

from __future__ import annotations

import numpy as np
import soundfile as sf

from .transcribe import SR

ROCK = {  # one bar of 16ths
    "kick":  "x-----x-x-------",
    "snare": "----x-------x---",
    "hihat": "x-x-x-x-x-x-x-x-",
}
FILL = {
    "snare": "x-x-x-x-xxxx----",
    "tom":   "------------x-x-",
    "kick":  "----------------",
}


def _kick(rng):
    t = np.arange(int(0.25 * SR)) / SR
    f = 50 + 90 * np.exp(-t * 40)
    return 0.9 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14)


def _snare(rng):
    t = np.arange(int(0.2 * SR)) / SR
    body = 0.5 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
    noise = rng.standard_normal(len(t))
    noise = np.convolve(noise, [1, -0.6], "same") * np.exp(-t * 22)  # brighten slightly
    return body + 0.35 * noise


def _hihat(rng):
    t = np.arange(int(0.06 * SR)) / SR
    n = np.diff(rng.standard_normal(len(t) + 1))  # first difference = high-pass
    return 0.25 * n * np.exp(-t * 70)


def _tom(rng):
    t = np.arange(int(0.3 * SR)) / SR
    return 0.7 * np.sin(2 * np.pi * 110 * t) * np.exp(-t * 12)


VOICES = {"kick": _kick, "snare": _snare, "hihat": _hihat, "tom": _tom}


def synth(
    path: str,
    bpm: float = 96,
    bars: int = 8,
    rush_bpm: float = 4.0,
    snare_late_ms: float = 15.0,
    jitter_ms: float = 6.0,
    swing: float = 0.5,
    fill_last_bar: bool = True,
    seed: int = 0,
) -> None:
    """Tempo ramps from bpm to bpm+rush_bpm; snare sits snare_late_ms behind;
    every hit gets Gaussian jitter; swing moves offbeat 8ths (0.5 = straight)."""
    rng = np.random.default_rng(seed)
    total_beats = bars * 4
    # Integrate a linearly ramping tempo to get the time of each beat.
    tempo = np.linspace(bpm, bpm + rush_bpm, total_beats + 1)
    beat_times = np.concatenate([[0.5], 0.5 + np.cumsum(60.0 / tempo[:-1])])
    y = np.zeros(int((beat_times[-1] + 1.0) * SR))

    for b in range(bars):
        pattern = FILL if (fill_last_bar and b == bars - 1) else ROCK
        for inst, steps in pattern.items():
            for i, ch in enumerate(steps):
                if ch != "x":
                    continue
                beat, k = divmod(i, 4)
                frac = [0.0, 0.25 * swing / 0.5, swing, swing + 0.5 * (1 - swing)][k]
                g = b * 4 + beat
                t = beat_times[g] + frac * (beat_times[g + 1] - beat_times[g])
                t += rng.normal(0, jitter_ms / 1000)
                if inst == "snare":
                    t += snare_late_ms / 1000
                gain = 1.0 if inst != "hihat" or i % 4 == 0 else 0.6
                s = VOICES[inst](rng) * gain
                start = int(t * SR)
                y[start : start + len(s)] += s[: len(y) - start]
    y += rng.normal(0, 0.002, len(y))  # room noise
    sf.write(path, (0.8 * y / np.abs(y).max()).astype(np.float32), SR)
