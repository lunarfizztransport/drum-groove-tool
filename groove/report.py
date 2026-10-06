"""Build report.html: one readable page per take with the timing results,
charts, your groove, and Claude's coaching. Self-contained (no internet
needed); double-click it to open in any browser."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

INST_ORDER = ["crash", "ride", "hihat", "hihat_closed", "hihat_open", "hihat_pedal",
              "tom_high", "tom_mid", "snare", "rim", "tom_floor", "kick", "hit"]
INST_LABEL = {"hihat": "Hi-hat", "hihat_closed": "Hi-hat", "hihat_open": "Open hat", "hihat_pedal": "Hat pedal",
              "tom_high": "High tom", "tom_mid": "Mid tom", "tom_floor": "Floor tom", "hit": "Hits"}


def build_report(folder: str | Path) -> Path:
    folder = Path(folder)
    a = json.loads((folder / "analysis.json").read_text())
    coaching_file = folder / "coaching.json"
    c = json.loads(coaching_file.read_text()) if coaching_file.exists() else None
    take = _take_title(folder.name)
    out = folder / "report.html"
    out.write_text(_page(take, a, c, folder))
    return out


def _take_title(name: str) -> str:
    """'2026-10-06_1039' -> 'Oct 6, 2026 · 10:39 AM'; other names unchanged."""
    from datetime import datetime

    try:
        d = datetime.strptime(name, "%Y-%m-%d_%H%M")
    except ValueError:
        return name
    return f"{d:%b} {d.day}, {d.year} · {d.hour % 12 or 12}:{d:%M} {d:%p}"


# --- page -------------------------------------------------------------------


def _page(take: str, a: dict, c: dict | None, folder: Path) -> str:
    t, tempo, sw = a["tightness"], a["tempo"], a["swing"]
    click = a["reference"] == "click"
    spb = 4 * a["beats_per_bar"]

    tiles = [
        _tile("Timing spread", f"{t['std_ms']:.0f} ms", _spread_word(t["std_ms"]),
              "How far your hits scatter around your own groove. Under 10 ms is tight; 10–20 is typical for an intermediate player."),
        _tile("Hits on target", f"{t['pct_within_10ms']:.0f}%", f"within 10 ms · {t['pct_within_20ms']:.0f}% within 20 ms",
              "Share of hits that landed within 10 ms of where they belong."),
    ]
    if "start_bpm" in tempo:
        tiles.append(_tile("Tempo", f"{tempo['start_bpm']:.0f} → {tempo['end_bpm']:.0f} bpm",
                           f"{tempo['verdict']} · {tempo['drift_bpm_per_minute']:+.1f} bpm/min",
                           "Your tempo at the start vs the end of the take."))
    if click:
        off = tempo["mean_offset_vs_click_ms"]
        tiles.append(_tile("Vs the click", f"{abs(off):.0f} ms {'ahead' if off < 0 else 'behind'}",
                           "on average", "Average distance from the metronome. Ahead = rushing, behind = dragging."))
    tiles.append(_tile("Feel", sw["feel"].split(",")[0].replace("8ths ", "").capitalize(),
                       f"8th notes {sw['eighth_swing_pct']:.0f}% · 50% = straight, 67% = swing",
                       "Where your off-beat 8th notes land between the beats."))

    groove = a["patterns"]["main_groove"]
    n_same = a["patterns"]["main_groove_bars"]
    body = [
        f"<header><p class='eyebrow'>Groove report</p><h1>{escape(take)}</h1>"
        f"<p class='sub'>{a['n_bars']} bars · {a['grid_bpm']:.0f} bpm · "
        f"{'played to a click' if click else 'no click (measured against your own steady pulse)'}</p></header>",
        f"<section class='tiles'>{''.join(tiles)}</section>",
    ]

    if c:
        body.append(f"<section class='card lead'><h2>The short version</h2><p>{_p(c['summary'])}</p></section>")

    body.append("<section class='card'><h2>Your groove</h2>"
                f"<p class='muted'>The beat you played most often ({n_same} of {a['n_bars']} bars). "
                "Darker = harder hit, lighter = ghost note.</p>"
                f"{_grid([groove], spb)}{_midi_link(folder, 'transcription.mid', 'Hear your whole take')}</section>")

    charts = ["<section class='card'><h2>Tempo, bar by bar</h2>"]
    if tempo["bpm_by_bar"]:
        charts.append(_line_chart(tempo["bpm_by_bar"], a["target_bpm"]))
    charts.append("</section>")
    charts.append(f"<section class='card'><h2>Early or late, bar by bar</h2><p class='muted'>Average distance from the "
                  f"{'click' if click else 'steady pulse'} in each bar.</p>{_bars_chart(a['per_bar'])}</section>")
    body.append("<div class='two'>" + "".join(charts) + "</div>")

    inst_rows = [(INST_LABEL.get(k, k.capitalize()), v["mean_offset_ms_vs_groove"], v["std_ms"], v["count"])
                 for k, v in sorted(a["per_instrument"].items(), key=lambda kv: _inst_rank(kv[0]))]
    pos_rows = [(("Beats 1 2 3 4" if k == "downbeats" else f"“{k}” notes"), v["mean_offset_ms"], v["std_ms"], v["count"])
                for k, v in a["per_beat_position"].items()]
    body.append("<div class='two'>"
                "<section class='card'><h2>By drum</h2><p class='muted'>Dot = average placement inside your groove; "
                f"line = spread.</p>{_dot_chart(inst_rows)}</section>"
                "<section class='card'><h2>By count</h2><p class='muted'>Are your in-between notes rushed or dragged "
                f"compared with the beat?</p>{_dot_chart(pos_rows)}</section></div>")

    worst = a["worst_events"][:6]
    if worst:
        rows = "".join(
            f"<tr><td>{w['bar']}</td><td>{escape(w['count'])}</td><td>{escape(', '.join(INST_LABEL.get(i, i) for i in w['instruments']))}</td>"
            f"<td class='num'>{_ms(w['offset_ms'])}</td></tr>" for w in worst)
        body.append("<section class='card'><h2>Moments to look at</h2><p class='muted'>The hits furthest from where "
                    "they belonged. Clusters in one bar usually mean a fill got away from you.</p>"
                    f"<div class='scroll'><table><thead><tr><th>Bar</th><th>Count</th><th>Drum</th><th class='num'>Off by</th></tr></thead>"
                    f"<tbody>{rows}</tbody></table></div></section>")

    if c:
        body.append(_coaching(c, folder, spb))
    else:
        body.append("<section class='card'><h2>Coaching</h2><p class='muted'>No Claude feedback for this take. Run "
                    "<code>analyze</code> without <code>--no-coach</code> (and with an API key) to get feedback, exercises, and fills.</p></section>")

    body.append("<footer>Made with grum-groove-tool. Raw numbers are in analysis.json.</footer>")
    return _HTML.replace("{title}", escape(f"{take} groove report")).replace("{body}", "\n".join(body))


def _coaching(c: dict, folder: Path, spb: int) -> str:
    parts = ["<h2 class='section'>Coaching</h2>"]
    if c.get("strengths"):
        parts.append("<section class='card'><h3>What's working</h3><ul>"
                     + "".join(f"<li>{_p(s)}</li>" for s in c["strengths"]) + "</ul></section>")
    for ins in c.get("timing_insights", []):
        parts.append(f"<section class='card insight'><h3>{escape(ins['title'])}</h3>"
                     f"<p class='evidence'>{_p(ins['evidence'])}</p><p>{_p(ins['what_it_means'])}</p>"
                     f"<p class='fix'><strong>Try this:</strong> {_p(ins['fix'])}</p></section>")
    parts.append("<div class='two'>"
                 f"<section class='card'><h3>Swing &amp; feel</h3><p>{_p(c['swing_and_feel'])}</p></section>"
                 f"<section class='card'><h3>Dynamics</h3><p>{_p(c['dynamics'])}</p></section></div>")
    if c.get("exercises"):
        parts.append("<h2 class='section'>Practice exercises</h2>")
        for e in c["exercises"]:
            parts.append(f"<section class='card'><h3>{escape(e['name'])} <span class='pill'>start at {e['start_bpm']} bpm</span></h3>"
                         f"<p>{_p(e['instructions'])}</p><p class='muted'><strong>Goal:</strong> {_p(e['goal'])}</p></section>")
    for kind, title, key in (("variation", "Groove variations", "variations"), ("fill", "Fills", "fills")):
        if not c.get(key):
            continue
        parts.append(f"<h2 class='section'>{title}</h2>")
        for i, p in enumerate(c[key], 1):
            bars = _pattern_bars(p, spb)
            links = (_midi_link(folder, f"patterns/{kind}{i}_in_context.mid", "Hear it with your groove")
                     + _midi_link(folder, f"patterns/{kind}{i}.mid", "Hear it alone"))
            parts.append(f"<section class='card'><h3>{escape(p['name'])} <span class='pill'>{escape(p['difficulty'])}</span></h3>"
                         f"<p>{_p(p['why_it_fits'])}</p>{_grid(bars, spb)}"
                         f"<p class='muted'><strong>How to practice:</strong> {_p(p['how_to_practice'])}</p>"
                         f"<div class='links'>{links}</div></section>")
    return "\n".join(parts)


# --- pieces -------------------------------------------------------------------


def _tile(label, value, detail, tip) -> str:
    return (f"<div class='tile' title='{escape(tip)}'><div class='tlabel'>{escape(label)}</div>"
            f"<div class='tvalue'>{escape(value)}</div><div class='tdetail'>{escape(detail)}</div></div>")


def _spread_word(ms: float) -> str:
    return "tight" if ms < 10 else "typical" if ms < 20 else "loose" if ms < 30 else "very loose"


def _ms(v: float) -> str:
    if abs(v) < 1:
        return "on time"
    return f"{abs(v):.0f} ms {'early' if v < 0 else 'late'}"


def _p(text: str) -> str:
    return escape(text).replace("\n\n", "</p><p>").replace("\n", "<br>")


def _inst_rank(name: str) -> int:
    return INST_ORDER.index(name) if name in INST_ORDER else len(INST_ORDER)


def _pattern_bars(p: dict, spb: int) -> list[dict[str, str]]:
    n = max(1, p["bars"])
    out = [{} for _ in range(n)]
    for t in p["tracks"]:
        s = ("".join(ch for ch in t["steps"] if ch in "Xxg-") + "-" * spb * n)[: spb * n]
        for b in range(n):
            out[b][t["instrument"]] = s[b * spb : (b + 1) * spb]
    return out


def _grid(bars: list[dict[str, str]], spb: int) -> str:
    """Drum grid as an HTML table: one row per drum, one cell per 16th."""
    insts = sorted({i for bar in bars for i in bar}, key=_inst_rank)
    counts = [str(i // 4 + 1) if i % 4 == 0 else ["", "e", "&", "a"][i % 4] for i in range(spb)]
    head = "<th></th>" + "".join(
        "".join(f"<th class='{'beat' if i % 4 == 0 else ''}{' barstart' if i == 0 and b else ''}'>{c}</th>"
                for i, c in enumerate(counts)) for b in range(len(bars)))
    rows = []
    for inst in insts:
        cells = []
        for b, bar in enumerate(bars):
            steps = bar.get(inst, "-" * spb)
            for i, ch in enumerate(steps):
                cls = {"X": "hit accent", "x": "hit", "g": "hit ghost"}.get(ch, "")
                if i % 4 == 0:
                    cls += " beat"
                if i == 0 and b:
                    cls += " barstart"
                label = {"X": "accent", "x": "hit", "g": "ghost"}.get(ch, "rest")
                cells.append(f"<td class='{cls.strip()}' title='{escape(INST_LABEL.get(inst, inst))}, {counts[i] or 'beat'}: {label}'></td>")
        rows.append(f"<tr><th class='inst'>{escape(INST_LABEL.get(inst, inst.capitalize()))}</th>{''.join(cells)}</tr>")
    return f"<div class='scroll'><table class='grid'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _midi_link(folder: Path, rel: str, text: str) -> str:
    if not (folder / rel).exists():
        return ""
    return f"<a class='midi' href='{escape(rel)}'>▶ {escape(text)}</a>"


# --- charts (inline SVG) -------------------------------------------------------

W, H = 560, 220
ML, MR, MT, MB = 44, 16, 14, 30


def _line_chart(points: list[dict], target: float | None) -> str:
    xs = [p["bar"] for p in points]
    ys = [p["bpm"] for p in points]
    lo, hi = min(ys + ([target] if target else [])), max(ys + ([target] if target else []))
    pad = max(1.0, (hi - lo) * 0.25)
    lo, hi = lo - pad, hi + pad
    x0, x1 = min(xs), max(xs) if max(xs) > min(xs) else min(xs) + 1
    sx = lambda x: ML + (x - x0) / (x1 - x0) * (W - ML - MR)
    sy = lambda y: MT + (hi - y) / (hi - lo) * (H - MT - MB)
    g = [_y_ticks(lo, hi, sy, "{:.0f}")]
    if target:
        g.append(f"<line class='ref' x1='{ML}' x2='{W - MR}' y1='{sy(target):.1f}' y2='{sy(target):.1f}'/>"
                 f"<text class='reflabel' x='{W - MR}' y='{sy(target) - 6:.1f}' text-anchor='end'>click {target:.0f}</text>")
    path = " ".join(f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    g.append(f"<path class='line' d='{path}'/>")
    for x, y in zip(xs, ys):
        g.append(f"<circle class='pt' cx='{sx(x):.1f}' cy='{sy(y):.1f}' r='4.5'/>"
                 f"<circle class='hit-target' cx='{sx(x):.1f}' cy='{sy(y):.1f}' r='14' data-tip='Bar {x}: {y:.1f} bpm'/>")
        g.append(f"<text class='axis' x='{sx(x):.1f}' y='{H - 10}' text-anchor='middle'>{x}</text>")
    return _svg(g, "Tempo by bar line chart", "bar")


def _bars_chart(per_bar: list[dict]) -> str:
    vals = [b["mean_offset_ms_vs_grid"] for b in per_bar]
    m = max(20.0, max(abs(v) for v in vals) * 1.15)
    n = len(per_bar)
    band = (W - ML - MR) / n
    bw = min(36.0, band - 4)
    sy = lambda y: MT + (m - y) / (2 * m) * (H - MT - MB)
    g = [_y_ticks(-m, m, sy, "{:+.0f}", zero=True),
         f"<text class='axis' x='{ML - 6}' y='{MT + 4}' text-anchor='end'>late</text>"
         f"<text class='axis' x='{ML - 6}' y='{H - MB}' text-anchor='end'>early</text>"]
    for i, b in enumerate(per_bar):
        v = b["mean_offset_ms_vs_grid"]
        cx = ML + band * (i + 0.5)
        y0, y1 = sy(0), sy(v)
        cls = "late" if v > 0 else "early"
        g.append(f"<path class='{cls}' d='{_bar_path(cx - bw / 2, bw, y0, y1)}'/>")
        g.append(f"<rect class='hit-target' x='{cx - band / 2:.1f}' y='{MT}' width='{band:.1f}' height='{H - MT - MB}' "
                 f"data-tip='Bar {b['bar']}: {_ms(v)} on average · spread {b['std_ms']:.0f} ms · {b['events']} hits'/>")
        g.append(f"<text class='axis' x='{cx:.1f}' y='{H - 10}' text-anchor='middle'>{b['bar']}</text>")
    return _svg(g, "Average timing offset per bar", "bar")


def _bar_path(x: float, w: float, y0: float, y1: float, r: float = 4) -> str:
    """Bar from baseline y0 to y1 with the far (data) end rounded."""
    h = abs(y1 - y0)
    r = min(r, h, w / 2)
    if y1 < y0:  # grows up
        return (f"M{x:.1f},{y0:.1f} V{y1 + r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} "
                f"H{x + w - r:.1f} Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 + r:.1f} V{y0:.1f} Z")
    return (f"M{x:.1f},{y0:.1f} V{y1 - r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 - r:.1f} V{y0:.1f} Z")


def _dot_chart(rows: list[tuple[str, float, float, int]]) -> str:
    """Horizontal dot (mean) + whisker (±spread) per row around a zero line."""
    if not rows:
        return "<p class='muted'>Not enough hits.</p>"
    lw, rw = 110, 110
    row_h = 40
    h = MT + row_h * len(rows) + 26
    m = max(25.0, max(abs(mn) + sd for _, mn, sd, _ in rows) * 1.05)
    sx = lambda v: lw + (v + m) / (2 * m) * (W - lw - rw)
    g = [f"<line class='zero' x1='{sx(0):.1f}' x2='{sx(0):.1f}' y1='{MT - 4}' y2='{h - 22}'/>",
         f"<text class='axis' x='{sx(-m):.1f}' y='{h - 6}'>← early</text>",
         f"<text class='axis' x='{sx(0):.1f}' y='{h - 6}' text-anchor='middle'>on the beat</text>",
         f"<text class='axis' x='{sx(m):.1f}' y='{h - 6}' text-anchor='end'>late →</text>"]
    for i, (label, mean, sd, count) in enumerate(rows):
        y = MT + row_h * i + row_h / 2
        cls = "late" if mean > 2 else "early" if mean < -2 else "even"
        g.append(f"<text class='rowlabel' x='{lw - 12}' y='{y + 4:.1f}' text-anchor='end'>{escape(label)}</text>")
        g.append(f"<line class='whisker' x1='{sx(max(-m, mean - sd)):.1f}' x2='{sx(min(m, mean + sd)):.1f}' y1='{y:.1f}' y2='{y:.1f}'/>")
        g.append(f"<circle class='dot {cls}' cx='{sx(mean):.1f}' cy='{y:.1f}' r='6'/>")
        g.append(f"<text class='val' x='{W - rw + 12}' y='{y + 4:.1f}'>{_ms(mean)}</text>")
        g.append(f"<rect class='hit-target' x='0' y='{y - row_h / 2:.1f}' width='{W}' height='{row_h}' "
                 f"data-tip='{escape(label)}: {_ms(mean)} on average, spread ±{sd:.0f} ms ({count} hits)'/>")
    return _svg(g, "Average placement by row", "row", height=h)


def _y_ticks(lo, hi, sy, fmt, zero=False) -> str:
    out = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        cls = "zero" if zero and k == 2 else "gridline"
        out.append(f"<line class='{cls}' x1='{ML}' x2='{W - MR}' y1='{sy(v):.1f}' y2='{sy(v):.1f}'/>")
        if not (zero and k in (0, 4)):
            out.append(f"<text class='axis num' x='{ML - 6}' y='{sy(v) + 4:.1f}' text-anchor='end'>{fmt.format(0 if zero and k == 2 else v)}</text>")
    return "".join(out)


def _svg(g: list[str], label: str, _kind: str, height: int = H) -> str:
    return (f"<svg class='chart' viewBox='0 0 {W} {height}' role='img' aria-label='{escape(label)}'>"
            + "".join(g) + "</svg>")


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --early: #2a78d6; --late: #e34948; --even: #898781; --line: #2a78d6;
  --hit: #3d3c39; --hit-accent: #0b0b0b; --hit-ghost: #b9b7ae; --cell: #efeee9; --beatcell: #e4e3dc;
  --accent-bg: #eef4fc;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --early: #3987e5; --late: #e66767; --line: #3987e5;
  --hit: #d6d5cd; --hit-accent: #ffffff; --hit-ghost: #6b6a64; --cell: #242422; --beatcell: #2e2e2b;
  --accent-bg: #16202c;
}}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --early: #3987e5; --late: #e66767; --line: #3987e5;
  --hit: #d6d5cd; --hit-accent: #ffffff; --hit-ghost: #6b6a64; --cell: #242422; --beatcell: #2e2e2b;
  --accent-bg: #16202c;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 40px 20px 60px; }
header { margin-bottom: 24px; }
.eyebrow { margin: 0; color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: .08em; }
h1 { margin: 2px 0 4px; font-size: 32px; line-height: 1.15; }
h2 { font-size: 18px; margin: 0 0 6px; }
h2.section { font-size: 22px; margin: 36px 0 12px; }
h3 { font-size: 16px; margin: 0 0 6px; }
p { margin: 0 0 10px; } .sub, .muted { color: var(--ink2); }
.muted { font-size: 14px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr)); gap: 12px; margin-bottom: 16px; }
.tile, .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
.tile { padding: 14px 16px; }
.tlabel { color: var(--ink2); font-size: 13px; }
.tvalue { font-size: 26px; font-weight: 650; line-height: 1.25; margin: 2px 0; }
.tdetail { color: var(--muted); font-size: 13px; }
.card { padding: 18px 20px; margin-bottom: 14px; }
.card.lead { background: var(--accent-bg); }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(380px, 100%), 1fr)); gap: 14px; }
.two > *, .card, .tile { min-width: 0; }
.two > .card { margin-bottom: 0; } .two { margin-bottom: 14px; }
@media (max-width: 440px) { main { padding: 24px 16px 40px; } .card { padding: 16px; } .tvalue { font-size: 22px; } }
.insight .evidence { color: var(--ink2); font-size: 14px; border-left: 3px solid var(--axis); padding-left: 10px; }
.fix { margin-bottom: 0; }
.pill { display: inline-block; font-size: 12px; font-weight: 500; color: var(--ink2); border: 1px solid var(--border); border-radius: 99px; padding: 1px 9px; margin-left: 6px; vertical-align: 2px; }
ul { margin: 0; padding-left: 20px; } li { margin-bottom: 4px; }
.scroll { overflow-x: auto; margin: 10px 0; }
table { border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 6px 12px 6px 0; border-bottom: 1px solid var(--grid); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
table.grid { border-collapse: separate; border-spacing: 2px; }
.grid th, .grid td { border: 0; padding: 0; }
.grid thead th { font-size: 11px; color: var(--muted); text-align: center; font-weight: 400; width: 22px; }
.grid thead th.beat { color: var(--ink); font-weight: 650; }
.grid th.inst { font-size: 13px; color: var(--ink2); font-weight: 500; padding-right: 10px; white-space: nowrap; }
.grid td { width: 22px; height: 22px; min-width: 22px; background: var(--cell); border-radius: 4px; }
.grid td.beat { background: var(--beatcell); }
.grid .barstart { border-left: 2px solid var(--axis); }
.grid td.hit { background: var(--hit); } .grid td.accent { background: var(--hit-accent); } .grid td.ghost { background: var(--hit-ghost); }
.links { display: flex; flex-wrap: wrap; gap: 8px; }
a.midi { display: inline-block; color: var(--ink); text-decoration: none; border: 1px solid var(--border); border-radius: 8px; padding: 5px 12px; font-size: 14px; background: var(--page); margin-top: 6px; }
a.midi:hover { border-color: var(--ink2); }
code { font-size: 13px; background: var(--cell); padding: 1px 5px; border-radius: 4px; }
svg.chart { width: 100%; height: auto; display: block; margin-top: 8px; overflow: visible; }
.gridline { stroke: var(--grid); stroke-width: 1; } .zero { stroke: var(--axis); stroke-width: 1.5; }
.ref { stroke: var(--muted); stroke-width: 1.5; stroke-dasharray: 4 4; }
.reflabel, .axis { fill: var(--muted); font-size: 12px; } .rowlabel { fill: var(--ink2); font-size: 13px; }
.val { fill: var(--ink); font-size: 13px; }
.line { fill: none; stroke: var(--line); stroke-width: 2; stroke-linejoin: round; }
.pt { fill: var(--line); stroke: var(--surface); stroke-width: 2; }
path.early { fill: var(--early); } path.late { fill: var(--late); }
.dot { stroke: var(--surface); stroke-width: 2; } .dot.early { fill: var(--early); } .dot.late { fill: var(--late); } .dot.even { fill: var(--even); }
.whisker { stroke: var(--axis); stroke-width: 3; stroke-linecap: round; }
.hit-target { fill: transparent; cursor: default; }
.hit-target:hover { fill: var(--ink); fill-opacity: .04; }
#tip { position: fixed; pointer-events: none; background: var(--ink); color: var(--page); font-size: 13px; padding: 6px 10px; border-radius: 6px; max-width: 280px; z-index: 10; }
footer { margin-top: 32px; color: var(--muted); font-size: 13px; }
</style></head>
<body><main>
{body}
</main>
<div id="tip" hidden></div>
<script>
const tip = document.getElementById('tip');
document.addEventListener('mousemove', e => {
  const t = e.target.closest('[data-tip]');
  if (!t) { tip.hidden = true; return; }
  tip.textContent = t.dataset.tip; tip.hidden = false;
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + 'px'; tip.style.top = (e.clientY + 14) + 'px';
});
</script>
</body></html>
"""
