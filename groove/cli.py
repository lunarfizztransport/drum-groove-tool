"""groove: record yourself, transcribe the hits, analyze your timing, and get
coaching + new variations/fills from Claude.

  python -m groove calibrate
  python -m groove record take1.wav --bpm 90 --bars 8
  python -m groove analyze take1.wav --goal "joining an indie rock band"
  python -m groove synth demo.wav            # fake take with known flaws
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anthropic


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="groove", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="record a take (with click if --bpm is given)")
    r.add_argument("out")
    r.add_argument("--bpm", type=float, help="play a click at this tempo (recommended)")
    r.add_argument("--bars", type=int, default=8)
    r.add_argument("--beats-per-bar", type=int, default=4)
    r.add_argument("--count-in", type=int, default=1, help="bars of count-in")

    sub.add_parser("calibrate", help="measure audio round-trip latency (speakers, not headphones)")

    a = sub.add_parser("analyze", help="transcribe + analyze a take, then ask Claude for coaching")
    a.add_argument("audio")
    a.add_argument("--bpm", type=float, help="tempo hint when there's no click sidecar file")
    a.add_argument("--beats-per-bar", type=int, default=4)
    a.add_argument("--mode", choices=["drums", "generic"], default="drums",
                   help="generic = any percussive instrument; timing only, no kit labels")
    a.add_argument("--goal", help="what you're working toward / style, passed to Claude")
    a.add_argument("--no-coach", action="store_true", help="skip the Claude step")
    a.add_argument("--out", help="output folder (default: <audio>_groove/)")
    a.add_argument("--no-open", action="store_true", help="don't open the report in a browser")

    rp = sub.add_parser("report", help="rebuild report.html for an analyzed take and open it")
    rp.add_argument("folder", help="e.g. take_groove")
    rp.add_argument("--no-open", action="store_true")

    s = sub.add_parser("synth", help="generate a fake take with known timing flaws")
    s.add_argument("out")
    s.add_argument("--bpm", type=float, default=96)
    s.add_argument("--bars", type=int, default=8)
    s.add_argument("--rush", type=float, default=4.0, help="bpm gained over the take")
    s.add_argument("--snare-late", type=float, default=15.0, help="ms the snare sits behind")
    s.add_argument("--jitter", type=float, default=6.0, help="random timing spread, ms")
    s.add_argument("--swing", type=float, default=0.5, help="offbeat 8th position, 0.5-0.75")

    args = ap.parse_args(argv)

    if args.cmd == "record":
        from .audio import record
        record(args.out, args.bpm, args.bars, args.beats_per_bar, args.count_in)
    elif args.cmd == "calibrate":
        from .audio import calibrate
        calibrate()
    elif args.cmd == "synth":
        from .synth import synth
        synth(args.out, args.bpm, args.bars, args.rush, args.snare_late, args.jitter, args.swing)
        print(f"Wrote {args.out}")
    elif args.cmd == "analyze":
        return run_analyze(args)
    elif args.cmd == "report":
        _report(Path(args.folder), args.no_open)
    return 0


def run_analyze(args) -> int:
    from .analyze import analyze
    from .coach import coach, pattern_bars, render_grid, to_markdown
    from .midi import hits_to_midi, patterns_to_midi
    from .transcribe import transcribe

    audio = Path(args.audio)
    out = Path(args.out or f"{audio.with_suffix('')}_groove")
    out.mkdir(parents=True, exist_ok=True)

    sidecar = Path(str(audio) + ".json")
    click, bpb = None, args.beats_per_bar
    if sidecar.exists():
        meta = json.loads(sidecar.read_text())
        click = {"bpm": meta["bpm"], "origin": meta["origin"]}
        bpb = meta.get("beats_per_bar", bpb)
        print(f"Using click grid from {sidecar.name}: {meta['bpm']} bpm")

    # Drop anything in the count-in (minus a beat of slack for early hits).
    start = max(0.0, click["origin"] - 60.0 / click["bpm"] / 2) if click else 0.0
    tr = transcribe(str(audio), mode=args.mode, start=start)
    print(f"Detected {len(tr.hits)} hits ({len({h.time for h in tr.hits})} onsets)")
    (out / "hits.json").write_text(json.dumps(tr.to_dict(), indent=1))

    result = analyze(tr, bpm=args.bpm, beats_per_bar=bpb, click=click)
    (out / "analysis.json").write_text(json.dumps(result, indent=1))
    bpm = result["grid_bpm"]
    hits_to_midi(tr.hits, bpm, str(out / "transcription.mid"))
    print_summary(result)
    print("\nMain groove as heard:")
    print(render_grid([result["patterns"]["main_groove"]]))

    if args.no_coach:
        _report(out, args.no_open)
        return 0

    print("\nAsking Claude for feedback (this can take a minute)...")
    try:
        c = coach(result, goal=args.goal)
    except anthropic.AuthenticationError:
        err = ("No valid Anthropic credentials. Set ANTHROPIC_API_KEY (or run `ant auth login`), "
               "or pass --no-coach.")
    except anthropic.APIConnectionError:
        err = "Couldn't reach the Anthropic API; check your connection."
    except (anthropic.APIStatusError, RuntimeError) as e:
        err = f"Coaching failed: {e}"
    else:
        err = None
    if err:
        print(err, file=sys.stderr)
        _report(out, args.no_open)  # still give them the timing report
        return 1

    spb = 4 * bpb
    s8 = result["swing"]["eighth_swing_pct"] / 100
    s16 = result["swing"]["sixteenth_swing_pct"] / 100
    groove = _kit_names(result["patterns"]["main_groove"])
    pdir = out / "patterns"
    pdir.mkdir(exist_ok=True)
    for kind, pats in (("variation", c.variations), ("fill", c.fills)):
        for i, p in enumerate(pats, 1):
            bars = pattern_bars(p, spb)
            patterns_to_midi(bars, bpm, str(pdir / f"{kind}{i}.mid"), s8, s16)
            # Hear it in context: 3 bars of your groove, then the pattern, then back to 1.
            in_ctx = [groove] * (3 if kind == "fill" else 2) + bars + [groove]
            patterns_to_midi(in_ctx, bpm, str(pdir / f"{kind}{i}_in_context.mid"), s8, s16)

    (out / "coaching.json").write_text(c.model_dump_json(indent=1))
    md = to_markdown(c, spb)
    (out / "coaching.md").write_text(md)
    print("\n" + md)
    _report(out, args.no_open)
    return 0


def _report(folder: Path, no_open: bool) -> None:
    import subprocess

    from .report import build_report

    path = build_report(folder)
    print(f"\nReport: {path}  (opens in your browser; double-click it any time)")
    if not no_open and sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)


def _kit_names(bar: dict[str, str]) -> dict[str, str]:
    """Transcription labels -> pattern instrument names."""
    return {("hihat_closed" if k == "hihat" else k): v for k, v in bar.items() if k != "hit"} or {"rim": bar.get("hit", "")}


def print_summary(r: dict) -> None:
    t, sw, tempo = r["tightness"], r["swing"], r["tempo"]
    ref = "vs click" if r["reference"] == "click" else "vs your own pulse (no click)"
    print(f"\n== {r['n_bars']} bars at ~{r['grid_bpm']} bpm, timing {ref} ==")
    print(f"Tightness: spread {t['std_ms']} ms, {t['pct_within_10ms']}% of hits within 10 ms")
    if "verdict" in tempo:
        print(f"Tempo: {tempo['start_bpm']} -> {tempo['end_bpm']} bpm "
              f"({tempo['drift_bpm_per_minute']:+} bpm/min, {tempo['verdict']})")
    if "mean_offset_vs_click_ms" in tempo:
        print(f"Average vs click: {tempo['mean_offset_vs_click_ms']:+} ms (+ = behind)")
    print(f"Swing: {sw['feel']} (8ths {sw['eighth_swing_pct']}%, 16ths {sw['sixteenth_swing_pct']}%)")
    for name, s in r["per_instrument"].items():
        print(f"  {name:>6}: {s['mean_offset_ms_vs_groove']:+6.1f} ms vs groove, spread {s['std_ms']} ms ({s['count']} hits)")


if __name__ == "__main__":
    sys.exit(main())
