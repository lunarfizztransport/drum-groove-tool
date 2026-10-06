"""Audio -> list of hits, using librosa onset detection plus a spectral-band
heuristic to guess which drum was struck.

The band heuristic is deliberately simple (kick = low band, snare = mid band,
hi-hat = high band). It works reasonably on a single room/phone mic over a
basic kit. For better kit-piece separation you can swap `label_onsets` for a
trained drum-transcription model (e.g. madmom / ADTLib) without touching the
timing analysis, which only needs onset times.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import librosa
import numpy as np

SR = 44100
HOP = 128  # ~2.9 ms per frame at 44.1 kHz: timing resolution of the analysis
N_FFT = 2048

BANDS = {
    "kick": (30, 150),
    "snare": (180, 2500),
    "hihat": (6000, 16000),
}
RISE_DB = 6.0  # band must jump at least this much at the onset to count


@dataclass
class Hit:
    time: float  # seconds from start of file
    instrument: str  # "kick" | "snare" | "hihat" | "hit" (generic mode)
    velocity: int  # 1-127, estimated from attack loudness


@dataclass
class Transcription:
    hits: list[Hit]
    tempo_estimate: float
    duration: float
    mode: str

    def to_dict(self) -> dict:
        return {
            "tempo_estimate": self.tempo_estimate,
            "duration": self.duration,
            "mode": self.mode,
            "hits": [asdict(h) for h in self.hits],
        }


def transcribe(path: str, mode: str = "drums", start: float = 0.0) -> Transcription:
    """Detect hits in an audio file.

    mode="drums" labels each onset as kick/snare/hihat (possibly several at once).
    mode="generic" labels every onset "hit" -- use this for hand percussion,
    guitar strums, tapping, or anything else where you only care about timing.
    Hits before `start` seconds (e.g. a count-in) are dropped.
    """
    y, sr = librosa.load(path, sr=SR, mono=True)
    duration = len(y) / sr

    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP, lag=1, max_size=3)
    frames = librosa.onset.onset_detect(
        onset_envelope=env,
        sr=sr,
        hop_length=HOP,
        units="frames",
        wait=int(0.03 * sr / HOP),  # merge onsets closer than 30 ms (flams)
        pre_max=int(0.02 * sr / HOP),
        post_max=int(0.02 * sr / HOP),
    )
    tempo = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=env, sr=sr, hop_length=HOP))[0])

    times = librosa.frames_to_time(frames, sr=sr, hop_length=HOP)
    keep = times >= start
    frames, times = frames[keep], times[keep]
    if len(frames) == 0:
        return Transcription([], tempo, duration, mode)

    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
    velocities = _velocities(S, frames)

    if mode == "generic":
        hits = [Hit(round(float(t), 4), "hit", v) for t, v in zip(times, velocities)]
    else:
        labels = label_onsets(S, frames, sr)
        bands = _band_db(S, sr)
        hits = [
            Hit(round(float(_refine(bands[inst], f, t, sr)), 4), inst, v)
            for f, t, v, insts in zip(frames, times, velocities, labels)
            for inst in insts
        ]
    return Transcription(hits, tempo, duration, mode)


def _band_db(S: np.ndarray, sr: int) -> dict[str, np.ndarray]:
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    out = {}
    for name, (lo, hi) in BANDS.items():
        idx = (freqs >= lo) & (freqs < hi)
        out[name] = 10 * np.log10((S[idx] ** 2).sum(axis=0) + 1e-10)
    return out


def _refine(band: np.ndarray, frame: int, t: float, sr: int, radius: int = 10) -> float:
    """Re-time one instrument from its own band's steepest rise near the onset.

    A snare 15 ms behind the hi-hat merges into one detected onset; this
    separates them again so each instrument gets its own timing.
    """
    lo, hi = max(1, frame - radius), min(len(band), frame + radius + 1)
    if hi - lo < 2:
        return t
    rise = np.diff(band[lo - 1 : hi])  # rise[j] = band[lo+j] - band[lo+j-1]
    # A centred window's energy rises steepest about half a window before the
    # attack reaches its centre; shift so refined times line up with the
    # onset detector (and with `calibrate`, which uses the detector directly).
    return float(librosa.frames_to_time(lo + int(np.argmax(rise)), sr=sr, hop_length=HOP)) + N_FFT / 2 / sr


def label_onsets(S: np.ndarray, frames: np.ndarray, sr: int) -> list[list[str]]:
    """Guess which kit pieces sound at each onset frame."""
    bands = _band_db(S, sr)
    n = S.shape[1]
    # The STFT window spans +-8 hops around a frame, so "before" must end ~8
    # hops before the onset to avoid already containing the attack.
    pre = {b: np.array([np.median(v[max(0, f - 16) : max(1, f - 8)]) for f in frames]) for b, v in bands.items()}
    post = {b: np.array([v[f : min(n, f + 10)].max() for f in frames]) for b, v in bands.items()}
    rise = {b: post[b] - pre[b] for b in bands}
    # Reference level per band: the loud end of that band across all onsets.
    ref = {b: np.percentile(post[b], 95) for b in bands}

    labels = []
    for i in range(len(frames)):
        lo, mid, hi = post["kick"][i], post["snare"][i], post["hihat"][i]
        insts = []
        if rise["kick"][i] >= RISE_DB and lo >= ref["kick"] - 15 and lo >= mid - 3:
            insts.append("kick")
        if rise["snare"][i] >= RISE_DB and mid >= ref["snare"] - 15 and mid >= lo - 10:
            insts.append("snare")
        if rise["hihat"][i] >= RISE_DB and hi >= ref["hihat"] - 20:
            insts.append("hihat")
        if not insts:
            # Something was detected but no band rule fired: take the band
            # that is closest to its own loud reference.
            insts.append(max(bands, key=lambda b: post[b][i] - ref[b]))
        labels.append(insts)
    return labels


def _velocities(S: np.ndarray, frames: np.ndarray) -> list[int]:
    """Map each onset's peak frame energy onto MIDI velocity (40 dB range)."""
    frame_db = 10 * np.log10((S**2).sum(axis=0) + 1e-10)
    n = S.shape[1]
    peaks = np.array([frame_db[f : min(n, f + 10)].max() for f in frames])
    top = np.percentile(peaks, 98)
    v = 127 * np.clip((peaks - (top - 40)) / 40, 0, 1)
    return [int(max(1, round(x))) for x in v]
