"""Timing analysis: fit a (possibly swung) 16th-note grid to the hits and
measure how the player sits against it.

Sign convention everywhere: positive ms = late (dragging / laid back),
negative ms = early (rushing / on top).

Two references are possible:
  * "click": the recording was made against our click track, so the grid's
    tempo and position are known. Deviations are absolute.
  * "self":  no click. We fit the steady pulse that best matches the playing,
    so deviations show consistency and drift, not absolute accuracy.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from .meter import FOUR_FOUR, Meter
from .transcribe import Transcription


def analyze(
    tr: Transcription,
    bpm: float | None = None,
    meter: Meter = FOUR_FOUR,
    click: dict | None = None,
) -> dict:
    """bpm counts the meter's beat (dotted quarters in 6/8).
    click: {"bpm": float, "origin": seconds of first downbeat after count-in}."""
    beats_per_bar, slots = meter.beats, meter.slots
    if len(tr.hits) < 8:
        raise ValueError(f"Only {len(tr.hits)} hits detected; record at least a few bars.")

    # Collapse simultaneous hits (e.g. kick+hihat) into one timing event.
    by_time: dict[float, list] = defaultdict(list)
    for h in tr.hits:
        by_time[h.time].append(h)
    times = np.array(sorted(by_time))
    insts = [{h.instrument for h in by_time[t]} for t in times]

    if click:
        beat = 60.0 / click["bpm"]
        origin = click["origin"]
        reference = "click"
    else:
        # Phase + downbeat from the opening bars only: a drifting player
        # makes any single global grid wrong by the end of the take.
        beat = 60.0 / (bpm or _fold_tempo(tr.tempo_estimate, meter))
        early = times < times[0] + 2 * beat * beats_per_bar
        weights = np.array([2.0 if ({"kick", "snare"} & s) else 1.0 for s in insts])
        origin, beat = _fit_phase(times[early], beat, weights[early], slots)
        origin = _pick_downbeat(times[early], [s for s, e in zip(insts, early) if e], origin, beat, meter, by_time)
        reference = "self"
    bar = beat * beats_per_bar
    origin = _first_downbeat(origin, times[0], bar, beat)

    # Quantize with a grid that follows the player's tempo, detect swing, repeat.
    s8 = s16 = 0.5
    for _ in range(2 if meter.swingable else 0):
        x, pos, slot = _track(times, origin, beat, meter.template(s8, s16), slots, window=2 * beats_per_bar)
        s8, s16 = _detect_swing(x)
    x, pos, slot = _track(times, origin, beat, meter.template(s8, s16), slots, window=2 * beats_per_bar)

    if reference == "self":
        origin, beat = _robust_fit(times, pos)  # the steady pulse that best fits the take
        bar = beat * beats_per_bar
    dev = (times - (origin + pos * beat)) * 1000.0  # vs steady grid / click: includes drift
    local = _local_residual(times, pos, beats_per_bar) * 1000.0  # placement within the groove
    keep = slot >= 0
    times, pos, dev, local, slot = times[keep], pos[keep], dev[keep], local[keep], slot[keep]
    insts = [s for s, k in zip(insts, keep) if k]

    spb = meter.steps_per_bar
    bars_idx = slot // spb
    slot_in_bar = slot % spb
    n_bars = int(bars_idx.max() + 1)

    result = {
        "reference": reference,
        "time_signature": meter.name,
        "beats_per_bar": beats_per_bar,
        "beat_note": meter.beat_note,
        "slots_per_beat": slots,
        "count_labels": meter.count_labels(),
        "grid_bpm": _r(60.0 / beat),
        "target_bpm": _r(click["bpm"]) if click else None,
        "n_events": int(len(times)),
        "n_bars": n_bars,
        "tightness": _tightness(local),
        "tempo": _tempo_report(times, pos, bars_idx, dev, reference),
        "swing": {
            "eighth_swing_pct": _r(s8 * 100),
            "sixteenth_swing_pct": _r(s16 * 100),
            "feel": _swing_word(s8, s16),
            "note": "50% = straight, 66.7% = triplet swing (MPC-style percentages).",
        } if meter.swingable else {
            "eighth_swing_pct": None,
            "sixteenth_swing_pct": None,
            "feel": f"{meter.name}: 8th notes grouped in threes" if meter.compound else f"{meter.name}: straight 8ths",
            "note": "Swing % isn't measured in this time signature.",
        },
        "per_instrument": {},
        "per_beat_position": {},
        "per_bar": [],
    }

    for name in sorted({i for s in insts for i in s}):
        m = np.array([name in s for s in insts])
        result["per_instrument"][name] = {
            "count": int(m.sum()),
            "mean_offset_ms_vs_groove": _r(local[m].mean()),
            "std_ms": _r(local[m].std()),
            "mean_offset_ms_vs_grid": _r(dev[m].mean()),
        }

    beat_pos = slot_in_bar % slots
    for label, ks in meter.position_groups():
        m = np.isin(beat_pos, list(ks))
        if m.sum() >= 3:
            result["per_beat_position"][label] = {
                "count": int(m.sum()),
                "mean_offset_ms": _r(local[m].mean()),
                "std_ms": _r(local[m].std()),
            }

    for b in range(n_bars):
        m = bars_idx == b
        if m.any():
            result["per_bar"].append(
                {"bar": b + 1, "events": int(m.sum()), "mean_offset_ms_vs_grid": _r(dev[m].mean()), "std_ms": _r(local[m].std())}
            )

    result["patterns"] = _patterns(by_time, times, bars_idx, slot_in_bar, spb, n_bars)
    result["worst_events"] = [
        {
            "time_s": round(float(times[i]), 3),
            "bar": int(bars_idx[i] + 1),
            "count": meter.count_name(int(slot_in_bar[i])),
            "instruments": sorted(insts[i]),
            "offset_ms": _r(local[i]),
        }
        for i in np.argsort(-np.abs(local))[:8]
    ]
    return result


# --- grid fitting -----------------------------------------------------------


def _fold_tempo(bpm: float, meter: Meter) -> float:
    """Bring an automatic tempo estimate into a plausible range for the meter's beat."""
    lo, hi = (40, 130) if meter.compound else (65, 180)
    if meter.compound:
        bpm *= 2 / 3  # estimates usually lock to quarter-ish pulses; convert to dotted quarters
    while bpm < lo:
        bpm *= 2
    while bpm > hi:
        bpm /= 2
    return bpm


def _first_downbeat(origin: float, t0: float, bar: float, beat: float) -> float:
    """Shift origin by whole bars so it is the last downbeat at/before the first hit."""
    return origin + np.floor((t0 - origin + beat / 8) / bar) * bar


def _fit_phase(times: np.ndarray, beat: float, weights: np.ndarray, slots: int) -> tuple[float, float]:
    """Jointly fit beat length (+-8%) and 16th-grid phase to a short stretch of
    hits, minimising a truncated squared error. Returns (phase, beat)."""
    best = (np.inf, 0.0, beat)
    t = times - times[0]
    for b in beat * np.linspace(0.92, 1.08, 81):
        step = b / slots
        phases = np.arange(0, step, 0.0005)
        d = (t[None, :] - phases[:, None] + step / 2) % step - step / 2
        cost = (np.minimum(np.abs(d), 0.03) ** 2 * weights).sum(axis=1)
        i = int(np.argmin(cost))
        if cost[i] < best[0]:
            best = (cost[i], phases[i] + times[0], b)
    return best[1], best[2]


def _pick_downbeat(times, insts, origin, beat, meter: Meter, by_time) -> float:
    """Choose which grid slot is beat 1: kick on 1, snare on the 2nd/4th beat, accents on beats."""
    step = beat / meter.slots
    best, best_score = origin, -np.inf
    for shift in range(meter.steps_per_bar):
        o = origin + shift * step
        slot = np.round((times - o) / step).astype(int) % meter.steps_per_bar
        score = 3.0 if slot[0] == 0 else 0.0  # people usually start on 1
        for t, s, sl in zip(times, insts, slot):
            on_beat = sl % meter.slots == 0
            beat_num = sl // meter.slots
            score += on_beat * max(h.velocity for h in by_time[t]) / 127
            if "kick" in s and sl == 0:
                score += 2
            if "snare" in s and on_beat and beat_num % 2 == 1:
                score += 2
        if score > best_score:
            best, best_score = o, score
    return best


def _detect_swing(x: np.ndarray) -> tuple[float, float]:
    """Median position of the offbeat 8th (s8) and of offbeat 16ths within their 8th (s16).

    x: continuous position of each event in beats, from the tracked grid."""
    frac = x % 1.0
    off8 = frac[(frac > 0.42) & (frac < 0.74)]
    s8 = float(np.median(off8)) if len(off8) >= 4 else 0.5
    e = frac[(frac > 0.15) & (frac < s8 * 0.8)] / s8
    a = (frac[(frac > s8 + (1 - s8) * 0.2) & (frac < 0.92)] - s8) / (1 - s8)
    sixteenths = np.concatenate([e, a])
    s16 = float(np.median(sixteenths)) if len(sixteenths) >= 4 else 0.5
    return min(max(s8, 0.5), 0.75), min(max(s16, 0.5), 0.75)


def _track(times, origin, beat, tpl: np.ndarray, slots: int, window: float):
    """Quantize hits in order against the (possibly swung) grid template, refit
    to the last `window` beats after every hit, so it follows tempo drift.

    Returns continuous positions x (beats), grid positions pos, and slot indices."""
    a, p = origin, beat  # current local grid: t = a + p * position
    xs, ps, idx = [], [], []
    for i, t in enumerate(times):
        x = (t - a) / p
        b = np.floor(x)
        k = int(np.argmin(np.abs(x - b - tpl)))
        xs.append(x)
        ps.append(b + tpl[k])
        idx.append(int(b) * slots + k)
        P, T = np.array(ps), times[: i + 1]
        m = P >= ps[-1] - window
        if m.sum() >= 4 and np.ptp(P[m]) >= 2:
            a_new, p_new = _robust_fit(T[m], P[m])
            if 0.85 * beat < p_new < 1.15 * beat:
                a, p = a_new, p_new
    return np.array(xs), np.array(ps), np.array(idx)


def _local_residual(times, pos, beats_per_bar) -> np.ndarray:
    """Each hit's offset (s) from a straight line fit through the hits within one bar either side."""
    out = np.zeros_like(times)
    for i, q in enumerate(pos):
        m = np.abs(pos - q) <= beats_per_bar
        if m.sum() >= 4 and np.ptp(pos[m]) > 0:
            a, p = _robust_fit(times[m], pos[m])
            out[i] = times[i] - (a + p * q)
    return out


def _robust_fit(times, pos) -> tuple[float, float]:
    """Least-squares t = origin + beat*pos, dropping >40 ms outliers once."""
    A = np.vstack([np.ones_like(pos), pos]).T
    coef, *_ = np.linalg.lstsq(A, times, rcond=None)
    m = np.abs(times - A @ coef) < 0.04
    if m.sum() >= 4:
        coef, *_ = np.linalg.lstsq(A[m], times[m], rcond=None)
    return float(coef[0]), float(coef[1])


# --- reports ----------------------------------------------------------------


def _tightness(local: np.ndarray) -> dict:
    a = np.abs(local)
    return {
        "std_ms": _r(local.std()),
        "pct_within_10ms": _r(100 * (a <= 10).mean()),
        "pct_within_20ms": _r(100 * (a <= 20).mean()),
        "note": "Measured against your own local groove (slow drift removed).",
    }


def _tempo_report(times, pos, bars_idx, dev, reference) -> dict:
    curve, mids = [], []
    for b in range(int(bars_idx.max()) + 1):
        m = (bars_idx >= b - 1) & (bars_idx <= b)  # 2-bar sliding window
        if m.sum() >= 4 and np.ptp(pos[m]) >= 1 and (bars_idx == b).any():
            slope = np.polyfit(pos[m], times[m], 1)[0]
            curve.append({"bar": b + 1, "bpm": _r(60.0 / slope)})
            mids.append(times[bars_idx == b].mean())
    out = {"bpm_by_bar": curve}
    if len(curve) >= 3:
        bpms = np.array([c["bpm"] for c in curve])
        slope_per_min = np.polyfit(np.array(mids), bpms, 1)[0] * 60
        out["start_bpm"] = _r(bpms[:2].mean())
        out["end_bpm"] = _r(bpms[-2:].mean())
        out["drift_bpm_per_minute"] = _r(slope_per_min)
        out["verdict"] = (
            "rushing (speeding up)" if slope_per_min > 1.5
            else "dragging (slowing down)" if slope_per_min < -1.5
            else "steady"
        )
    if reference == "click":
        out["mean_offset_vs_click_ms"] = _r(dev.mean())
    return out


def _swing_word(s8: float, s16: float) -> str:
    def word(s):
        if s < 0.53:
            return "straight"
        if s < 0.6:
            return "light swing"
        if s < 0.7:
            return "triplet swing"
        return "hard swing / dotted"

    return f"8ths {word(s8)}, 16ths {word(s16)}"


def _patterns(by_time, times, bars_idx, slot_in_bar, spb, n_bars) -> dict:
    """Per-bar step strings: X accent, x normal, g ghost, - rest."""
    vel_by_inst = defaultdict(list)
    for t in times:
        for h in by_time[t]:
            vel_by_inst[h.instrument].append(h.velocity)
    med = {k: np.median(v) for k, v in vel_by_inst.items()}

    names = sorted(vel_by_inst)
    bars = [{n: ["-"] * spb for n in names} for _ in range(n_bars)]
    for t, b, s in zip(times, bars_idx, slot_in_bar):
        for h in by_time[t]:
            ratio = h.velocity / med[h.instrument]
            bars[b][h.instrument][s] = "X" if ratio > 1.25 else "g" if ratio < 0.55 else "x"

    rendered = [{n: "".join(bar[n]) for n in names} for bar in bars]
    shape = [tuple(r[n].replace("X", "x").replace("g", "x") for n in names) for r in rendered]
    main_shape, main_count = Counter(shape).most_common(1)[0]
    return {
        "legend": "one char per 16th note (see count_labels); X=accent x=normal g=ghost -=rest",
        "main_groove": rendered[shape.index(main_shape)],
        "main_groove_bars": main_count,
        "bars_that_differ": [i + 1 for i, s in enumerate(shape) if s != main_shape],
        "all_bars": [{"bar": i + 1, **r} for i, r in enumerate(rendered)],
    }


def _r(x) -> float:
    return round(float(x), 1)
