"""Kit profiles: learn what *your* drums sound like on *your* mic, then use
that to label hits.

The fixed frequency-band rules in transcribe.py break down when a mic
colours the sound (phones roll off bass and squash dynamics, so kick and
snare look alike). A profile stores the average onset spectrum of each
drum from a few reference hits. Each hit in a take is then explained as a
non-negative mix of those spectra (NNLS), so a kick + hi-hat together comes
out as both.

Profiles live in ~/.config/groove-tool/kits/<name>.json. Learn one per
setup (laptop mic, phone, room) with `groove learn-kit`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import librosa
import numpy as np
from scipy.optimize import nnls

from .transcribe import HOP, N_FFT, SR

KITS = Path.home() / ".config" / "groove-tool" / "kits"
DRUMS = ["kick", "snare", "hihat"]  # the default set, in the order you play them when teaching
# Every drum a profile can learn, in the usual teaching order.
ALL_DRUMS = ["kick", "snare", "hihat", "tom_high", "tom_mid", "tom_floor", "crash", "ride"]
SPOKEN = {"hihat": "closed HI-HAT", "tom_high": "HIGH TOM", "tom_mid": "MID TOM",
          "tom_floor": "FLOOR TOM", "crash": "CRASH cymbal", "ride": "RIDE cymbal"}


def parse_drums(text: str) -> list[str]:
    """'kick,snare,hihat,tom_floor,crash' -> validated list in the given order."""
    drums = [d.strip().lower().replace("-", "_") for d in text.split(",") if d.strip()]
    bad = [d for d in drums if d not in ALL_DRUMS]
    if bad:
        raise ValueError(f"Unknown drum(s): {', '.join(bad)}. Choose from: {', '.join(ALL_DRUMS)}")
    if len(set(drums)) != len(drums) or len(drums) < 2:
        raise ValueError("List at least two different drums, each once, in the order you played them.")
    return drums
N_BANDS = 24
MIN_SHARE = 0.02  # a drum must explain at least this much of a hit (filters numerical noise)
MIN_LEVEL = 0.1  # ...and be at least this loud relative to that drum's strong hits in the take
# Cymbals ring and share brightness with snare/hi-hat, so they need to be a bigger part of a hit to count.
LEVEL_FOR = {"crash": 0.35, "ride": 0.35}


def band_edges(sr: int = SR) -> np.ndarray:
    return np.geomspace(30, min(16000, sr / 2 - 1), N_BANDS + 1)


def onset_spectra(S: np.ndarray, frames: np.ndarray, sr: int = SR) -> np.ndarray:
    """Energy each onset *adds* per log-spaced band (post-onset minus pre-onset),
    so a previous hit still ringing doesn't count. Shape (n_onsets, N_BANDS)."""
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    edges = band_edges(sr)
    P = np.stack([(S[(freqs >= lo) & (freqs < hi)] ** 2).sum(axis=0) for lo, hi in zip(edges[:-1], edges[1:])])
    n = P.shape[1]
    out = []
    for f in frames:
        pre = np.median(P[:, max(0, f - 16) : max(1, f - 8)], axis=1)
        post = P[:, f : min(n, f + 10)].max(axis=1)
        out.append(np.maximum(post - pre, 0))
    return np.array(out)


def label(S: np.ndarray, frames: np.ndarray, profile: dict, sr: int = SR) -> list[list[str]]:
    """Label each onset with the drums whose learned sound explains it."""
    drums = profile.get("drums", DRUMS)
    T = np.array([profile["templates"][d] for d in drums]).T  # (bands, drums), unit-sum columns
    # Gently weight bands so quiet ranges (hi-hat) aren't drowned out by loud ones (kick).
    w = np.sqrt(T.mean(axis=1)) + 1e-12
    Tw = T / w[:, None]
    R = onset_spectra(S, frames, sr) / w
    G = np.array([nnls(Tw, r)[0] for r in R])  # (onsets, drums): how much of each drum
    # A drum counts if it's a real part of this hit AND loud relative to that
    # drum's strong hits in this take (levels differ between recordings).
    share = G / (G.sum(axis=1, keepdims=True) + 1e-12)
    strong = np.percentile(G, 90, axis=0) + 1e-12
    labels = []
    for g, sh in zip(G, share):
        hit = [d for d, gi, si, ref in zip(drums, g, sh, strong)
               if si >= MIN_SHARE and gi >= LEVEL_FOR.get(d, MIN_LEVEL) * ref]
        labels.append(hit or [drums[int(np.argmax(sh))]])
    return labels


# --- learning ---------------------------------------------------------------


HITS_PER_DRUM = 4  # how many hits you play on each drum when teaching


def _onsets(y: np.ndarray, sr: int = SR) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP, lag=1, max_size=3)
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=HOP, wait=int(0.25 * sr / HOP))
    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
    return S, frames, env[frames]


def _strongest(idx: np.ndarray, strength: np.ndarray, n: int = HITS_PER_DRUM) -> np.ndarray:
    """You played n hits; anything beyond the n strongest is ringing or echo, not a hit."""
    keep = idx[np.argsort(strength[idx])[::-1][:n]]
    return np.sort(keep)


def _template(spectra: np.ndarray) -> list[float]:
    """Typical (median) sound of a drum, so a stray extra onset barely matters."""
    norm = spectra / (spectra.sum(axis=1, keepdims=True) + 1e-12)
    t = np.median(norm, axis=0)
    return (t / t.sum()).tolist()


def learn_from_file(path: str, drums: list[str] = DRUMS) -> dict:
    """A recording of 4 hits on each drum in `drums`, in that order, with a pause between drums."""
    y, sr = librosa.load(path, sr=SR, mono=True)
    S, frames, strength = _onsets(y, sr)
    order = ", wait, ".join(f"4 {SPOKEN.get(d, d).lower()}" for d in drums)
    if len(frames) < 2 * len(drums):
        raise ValueError(f"Only heard {len(frames)} hits for {len(drums)} drums. Play {order}.")
    times = librosa.frames_to_time(frames, sr=sr, hop_length=HOP)
    gaps = np.diff(times)
    # The longest pauses separate the drums.
    split = np.sort(np.argsort(gaps)[-(len(drums) - 1):])
    groups = np.split(np.arange(len(frames)), split + 1)
    inner = [np.diff(times[g]) for g in groups if len(g) > 1]
    within = float(np.median(np.concatenate(inner))) if inner else 0.5
    if min(gaps[split]) < 1.5 * within or any(len(g) < 2 for g in groups):
        sizes = ", ".join(str(len(g)) for g in groups)
        raise ValueError(f"Couldn't find {len(drums)} separate groups of hits (heard groups of {sizes}). "
                         f"Play {order}, waiting about 3 seconds between drums.")
    spectra = onset_spectra(S, frames, sr)
    return _profile({d: spectra[_strongest(g, strength)] for d, g in zip(drums, groups)}, source=Path(path).name)


def learn_by_recording(drums: list[str] = DRUMS, seconds: float = 5.0) -> dict:
    """Guided: record each drum separately through the computer's mic."""
    import sounddevice as sd

    spectra = {}
    for d in drums:
        name = SPOKEN.get(d, d.upper())
        while True:
            input(f"\nPress Enter, then play 4 {name} hits, about one per second...")
            audio = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="float32")
            sd.wait()
            S, frames, strength = _onsets(audio[:, 0])
            if len(frames) > HITS_PER_DRUM:
                extra = len(frames) - HITS_PER_DRUM
                frames = frames[_strongest(np.arange(len(frames)), strength)]
                print(f"  (Ignored {extra} echo/ringing blip{'s' if extra > 1 else ''} after your hits.)")
            if len(frames) >= 2:
                spectra[d] = onset_spectra(S, frames)
                print(f"  Got {len(frames)} {d} hits.")
                break
            print(f"  Only heard {len(frames)}. Play a bit louder or closer to the mic, and try again.")
    return _profile(spectra, source="computer mic")


def _profile(spectra: dict[str, np.ndarray], source: str) -> dict:
    return {
        "learned": date.today().isoformat(),
        "source": source,
        "drums": list(spectra),
        "hits": {d: int(len(s)) for d, s in spectra.items()},
        "band_edges_hz": band_edges().round(1).tolist(),
        "templates": {d: _template(s) for d, s in spectra.items()},
    }


def check(profile: dict) -> list[str]:
    """Sanity-check a freshly learned profile; returns problems worth redoing it for."""
    problems = []
    for d, n in profile["hits"].items():
        if n < 3:
            problems.append(f"Only heard {n} {d} hit(s); 4 clear hits per drum work best.")
    edges = np.array(profile["band_edges_hz"])
    centers = np.sqrt(edges[:-1] * edges[1:])

    def brightness(d):  # spectral centroid on a log-frequency scale, in Hz
        t = np.array(profile["templates"][d])
        return float(np.exp((t * np.log(centers)).sum() / t.sum()))

    b = {d: brightness(d) for d in ("kick", "snare", "hihat") if d in profile["templates"]}
    if len(b) == 3 and not (b["kick"] < b["snare"] < b["hihat"]):
        problems.append(
            "The learned sounds don't line up the way real drums do (kick should be the deepest, hi-hat the "
            f"brightest; got kick ~{b['kick']:.0f} Hz, snare ~{b['snare']:.0f} Hz, hi-hat ~{b['hihat']:.0f} Hz). "
            "The mic may be missing the bass or treble, or hits were played at the wrong prompt.")
    return problems


# --- storage ----------------------------------------------------------------


def save(profile: dict, name: str) -> Path:
    KITS.mkdir(parents=True, exist_ok=True)
    path = KITS / f"{name}.json"
    path.write_text(json.dumps(profile, indent=1))
    return path


def load(name: str) -> dict:
    path = KITS / f"{name}.json"
    if not path.exists():
        have = ", ".join(sorted(p.stem for p in KITS.glob("*.json"))) or "none yet"
        raise FileNotFoundError(f"No kit profile called '{name}' (have: {have}). Make one with: groove learn-kit")
    return json.loads(path.read_text())


def names() -> list[str]:
    return sorted(p.stem for p in KITS.glob("*.json"))
