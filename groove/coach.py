"""Send the timing analysis to Claude and get back structured coaching:
timing feedback, practice exercises, and groove variations / fills written
as 16th-note step patterns that we can render to MIDI."""

from __future__ import annotations

import json
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"

Instrument = Literal[
    "kick", "snare", "rim", "hihat_closed", "hihat_open", "hihat_pedal",
    "ride", "crash", "tom_high", "tom_mid", "tom_floor",
]


class Track(BaseModel):
    instrument: Instrument
    steps: str = Field(description="One char per 16th note across all bars of the pattern: X accent, x normal, g ghost, - rest.")


class Pattern(BaseModel):
    name: str
    bars: int
    difficulty: Literal["easier", "same level", "stretch"]
    why_it_fits: str = Field(description="How this builds on what the player actually did.")
    how_to_practice: str
    tracks: list[Track]


class TimingInsight(BaseModel):
    title: str
    evidence: str = Field(description="The numbers from the analysis this is based on.")
    what_it_means: str
    fix: str


class Exercise(BaseModel):
    name: str
    instructions: str
    start_bpm: int
    goal: str


class Coaching(BaseModel):
    summary: str
    strengths: list[str]
    timing_insights: list[TimingInsight]
    swing_and_feel: str
    dynamics: str
    exercises: list[Exercise]
    variations: list[Pattern] = Field(description="Variations on the main groove, each 1-2 bars.")
    fills: list[Pattern] = Field(description="Fills, each 1-2 bars, played straight after the main groove.")


SYSTEM = """You are a drum teacher and working band drummer. Your student is learning drums so they can join a band. You'll get a machine analysis of a recording of them playing and should give them feedback and new material.

How to read the analysis:
- Offsets are in milliseconds; positive = late (behind the beat), negative = early (ahead). "vs_groove" numbers have slow tempo drift removed, so they show where a hit sits inside the groove; "vs_grid" numbers include drift.
- reference "self" means no click was used: the grid is the steady pulse that best fits their playing, so drift and consistency are meaningful but absolute accuracy is not. reference "click" means offsets are against a real metronome.
- Swing is given as MPC-style percentages: 50% straight, ~66.7% triplet swing.
- The transcription is a heuristic onset detector on one microphone. Kit-piece labels can be wrong (e.g. a snare hit also tagged as hi-hat), and occasional hits are missed or doubled. Build feedback on patterns across many hits, not on one odd event, and say so when a number may be an artifact.
- For scale: differences under ~5 ms aren't audible; a spread (std) of 10-20 ms is typical for an intermediate player; under 10 ms is tight.

What to give back:
- Feedback that is specific, cites the numbers, and is honest about both strengths and problems. Explain what each issue will sound like to bandmates.
- Exercises that target the biggest timing issues.
- Variations and fills in this player's style: start from their actual main groove, the instruments and density they use, and their tendencies, and pitch most at or slightly above their current level. Variations should be usable in a song verse or chorus; fills should lead naturally back into their groove.

Pattern format: each track's steps string has exactly 16 characters per bar of 4/4 (bars x 16 total, more for other meters as noted in the analysis), one per 16th note starting on beat 1. Use X accent, x normal, g ghost, - rest. Only include tracks that play."""


def coach(analysis: dict, goal: str | None = None) -> Coaching:
    """Call Claude. Credentials come from ANTHROPIC_API_KEY or an `ant auth login` profile."""
    client = anthropic.Anthropic()
    user = ""
    if goal:
        user += f"About me / what I'm working toward: {goal}\n\n"
    user += "Here is the analysis of my recording:\n\n" + json.dumps(_trim(analysis), indent=1)

    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "high"},
        output_format=Coaching,
        messages=[{"role": "user", "content": user}],
        # If a safety classifier declines, re-run on Anthropic's recommended fallback model.
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to answer this request.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError(f"Incomplete response from Claude (stop_reason={response.stop_reason}).")
    return response.parsed_output


def _trim(analysis: dict) -> dict:
    """Drop bulky fields Claude doesn't need; keep per-bar patterns only for bars that differ."""
    a = {k: v for k, v in analysis.items() if k != "patterns"}
    p = analysis["patterns"]
    a["patterns"] = {
        "legend": p["legend"],
        "main_groove": p["main_groove"],
        "main_groove_bars": p["main_groove_bars"],
        "bars_that_differ": [b for b in p["all_bars"] if b["bar"] in p["bars_that_differ"]],
    }
    return a


def pattern_bars(p: Pattern, steps_per_bar: int = 16) -> list[dict[str, str]]:
    """Split a pattern into per-bar {instrument: steps}, padding/trimming to length."""
    total = steps_per_bar * max(1, p.bars)
    tracks = {}
    for t in p.tracks:
        s = "".join(ch for ch in t.steps if ch in "Xxg-")
        tracks[t.instrument] = (s + "-" * total)[:total]
    return [
        {inst: s[i * steps_per_bar : (i + 1) * steps_per_bar] for inst, s in tracks.items()}
        for i in range(max(1, p.bars))
    ]


def to_markdown(c: Coaching, steps_per_bar: int = 16) -> str:
    out = [f"# Groove feedback\n\n{c.summary}\n", "## What's working\n"]
    out += [f"- {s}" for s in c.strengths]
    out.append("\n## Timing\n")
    for t in c.timing_insights:
        out.append(f"### {t.title}\n\n*Evidence:* {t.evidence}\n\n{t.what_it_means}\n\n**Fix:** {t.fix}\n")
    out.append(f"## Swing & feel\n\n{c.swing_and_feel}\n\n## Dynamics\n\n{c.dynamics}\n\n## Exercises\n")
    for e in c.exercises:
        out.append(f"### {e.name} (start at {e.start_bpm} bpm)\n\n{e.instructions}\n\n*Goal:* {e.goal}\n")
    for title, pats in (("Variations", c.variations), ("Fills", c.fills)):
        out.append(f"## {title}\n")
        for p in pats:
            out.append(f"### {p.name} ({p.difficulty}, {p.bars} bar{'s' if p.bars > 1 else ''})\n\n{p.why_it_fits}\n")
            out.append("```\n" + render_grid(pattern_bars(p, steps_per_bar)) + "\n```\n")
            out.append(f"*Practice:* {p.how_to_practice}\n")
    return "\n".join(out)


def render_grid(bars: list[dict[str, str]]) -> str:
    """ASCII drum grid with a count line, bars separated by |."""
    steps = len(next(iter(bars[0].values()))) if bars and bars[0] else 16
    count = "".join(f"{b + 1}e&a" for b in range(steps // 4))
    insts = list(dict.fromkeys(i for bar in bars for i in bar))
    width = max(len(i) for i in insts + ["count"])
    lines = [f"{'count':>{width}} |" + "|".join(count for _ in bars) + "|"]
    for inst in insts:
        lines.append(f"{inst:>{width}} |" + "|".join(bar.get(inst, "-" * steps) for bar in bars) + "|")
    return "\n".join(lines)
