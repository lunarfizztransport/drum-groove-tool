"""Write reference outputs from the Python package for test/compare.mjs.

  .venv/bin/python web/test/reference.py <out_dir>
"""
import json, sys
from pathlib import Path

import librosa, numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from groove import kit as kitmod
from groove.analyze import analyze
from groove.meter import Meter
from groove.synth import synth
from groove.transcribe import HOP, SR, transcribe

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
demo = ROOT / "takes" / "demo" / "recording.wav"
meta = json.loads((ROOT / "takes" / "demo" / "recording.wav.json").read_text())
profile = kitmod.load("demo")
(out / "kit-demo.json").write_text(json.dumps(profile))
for name, m, swing in (("synth44", "4/4", 0.62), ("synth68", "6/8", 0.5)):
    synth(str(out / f"{name}.wav"), bpm=96 if m == "4/4" else 60, meter=Meter.parse(m), swing=swing)

def frames_of(path):
    y, sr = librosa.load(path, sr=SR, mono=True)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP, lag=1, max_size=3)
    f = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=HOP, units="frames",
        wait=int(0.03 * sr / HOP), pre_max=int(0.02 * sr / HOP), post_max=int(0.02 * sr / HOP))
    t = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=env, sr=sr, hop_length=HOP))[0])
    return {"frames": f.tolist(), "env_head": env[:4000].tolist(), "tempo": t}

cases = {}
click = {"bpm": meta["bpm"], "origin": meta["origin"]}
start = max(0.0, click["origin"] - 60.0 / click["bpm"] / 2)
for name, path, kw, an in [
    ("demo_kit_click", demo, dict(start=start, kit=profile), dict(click=click)),
    ("demo_rules_click", demo, dict(start=start), dict(click=click)),
    ("demo_rules_self", demo, dict(start=start), dict(bpm=80.0)),
    ("demo_generic_self", demo, dict(mode="generic", start=start), dict()),
    ("synth44_self", out / "synth44.wav", dict(), dict()),
    ("synth68_self", out / "synth68.wav", dict(), dict(meter=Meter.parse("6/8"), bpm=60.0)),
]:
    tr = transcribe(str(path), **kw)
    cases[name] = {"path": str(path), "hits": tr.to_dict(), "analysis": analyze(tr, **an), **frames_of(path)}
(out / "reference.json").write_text(json.dumps({"meta": meta, "cases": cases}))
print("wrote", out)
