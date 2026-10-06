# grum-groove-tool

**Record yourself playing drums, find out exactly how your timing sits, and get
feedback plus new grooves and fills written in your style.**

You play along to a click. The tool works out every hit you made and measures:

- whether you rush or drag;
- how consistent you are;
- which drum is early or late;
- how much you swing.

Claude, Anthropic's AI model, then reads those numbers like a drum teacher
would. It explains what it hears, gives you exercises, and writes new
variations and fills based on what you actually played. Everything ends up in
one page you open in your browser, and every suggestion comes as a MIDI file
you can play in GarageBand.

```
record ─▶ find the hits ─▶ measure timing ─▶ Claude coaching ─▶ report + MIDI
```

It's made for drummers, but `--mode generic` measures timing for any
rhythmic instrument (guitar strumming, shaker, hand percussion).

---

## What you need

- A Mac with Python 3.10 or newer
- A microphone (your laptop's built-in mic works) and headphones for the click
- Optional: an Anthropic API key for Claude's coaching (see [Cost](#cost))

## Install (once)

Open a terminal (in VS Code: **Terminal → New Terminal**) and run:

```bash
git clone https://github.com/lunarfizztransport/grum-groove-tool.git
cd grum-groove-tool
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## The easy way: guided run

```bash
./run.sh
```

It walks you through everything with prompts:

1. **Demo:** analyzes a fake recording so you can see what the output looks like.
2. **Calibrate:** take headphones off. It plays clicks through your speakers to measure your computer's audio delay.
3. **Record:** headphones on. You get a 1-bar count-in, then play 8 bars.
4. **Analyze:** your report opens in the browser.

Press **Ctrl+C** at any time to stop.

## Your results

Every take is saved in its own folder inside **`takes/`**, named by the date
and time you recorded it. The recording and all of its results stay together:

```
takes/
  2026-10-06_1010/
    recording.wav
    report.html        ← start here
    patterns/          ← fills and variations as MIDI
    ...
  2026-10-06_1039/
  demo/
```

Takes stay on your computer: the `takes/` folder is never uploaded to GitHub.

The main file is **`report.html`**, which opens in your browser automatically
after each take. Double-click it to open it again later. It shows:

- **Headline numbers:** timing spread, % of hits on target, tempo start → end, distance from the click, swing feel
- **Your groove** drawn as a drum grid
- **Charts:** tempo bar by bar, early/late bar by bar, and timing by drum and by count (hover for details)
- **Moments to look at:** the hits furthest off
- **Claude's coaching:** what's working, timing problems with fixes, practice exercises
- **Variations and fills**, each drawn as a grid with ▶ links to hear them

The **MIDI files** in `patterns/` open in GarageBand (double-click, then press
Space). Start with the `_in_context` versions. They play your groove, then the
fill, then back to your groove, so you hear how it fits in a song.

| File | What it is |
|---|---|
| `report.html` | **Start here.** Everything, readable |
| `recording.wav` | Your recording |
| `patterns/*.mid` | Suggested variations and fills to listen to |
| `transcription.mid` | Your take as the tool heard it |
| `coaching.md` | Claude's feedback as plain text |
| `analysis.json`, `hits.json`, `coaching.json` | Raw data for the program. You don't need to open these |

## Running steps yourself

```bash
.venv/bin/python -m groove calibrate                          # once per computer/mic setup
.venv/bin/python -m groove record --bpm 80 --bars 8           # saves to takes/<date_time>/
.venv/bin/python -m groove analyze 2026-10-06_1039 --goal "learning drums to join an indie rock band"
.venv/bin/python -m groove report 2026-10-06_1039              # reopen / rebuild a report
```

Refer to a take by its folder name. You can also give `record` your own
name, e.g. `record verse-groove --bpm 100`, which saves to `takes/verse-groove/`.
Any tempo works; change `--bpm`, and `--bars` for longer or shorter takes.

Useful options for `analyze`:

| Option | Does |
|---|---|
| `--no-coach` | Skip Claude: free, timing analysis only |
| `--goal "..."` | Tell Claude your style and goals so suggestions fit |
| `--bpm 120` | Tempo hint for recordings made without a click |
| `--mode generic` | Any instrument: timing only, no drum labels |

You can analyze any existing WAV file, such as a rehearsal recording:
`analyze ~/Desktop/rehearsal.wav` copies it into `takes/rehearsal/` and analyzes
it there. Without a
click there's no metronome to compare against, so the tool measures you against
your own steady pulse. Speeding up, slowing down and consistency are still
accurate. Phone voice memos (`.m4a`) need `brew install ffmpeg` first, or
export them as WAV.

## Cost

Everything runs free on your computer **except Claude's coaching**, which uses
Anthropic's paid API at roughly **10–25 cents per analyzed take**. To set it up:

1. Sign in at [console.anthropic.com](https://console.anthropic.com) (separate from a Claude.ai subscription).
2. Add prepaid credit under **Settings → Billing**. $5 covers a lot of takes, and nothing renews automatically.
3. Create a key under **Settings → API Keys** and paste it when `run.sh` asks, or save it once:
   ```bash
   echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc
   ```

Keep the key private and never commit it. Use `--no-coach` (or press Enter at
the key prompt) to skip coaching entirely.

## Reading the numbers

- **Spread:** how far your hits scatter around your own groove. Under 10 ms is tight; 10–20 ms is typical for an intermediate player; over 30 ms sounds loose to a band.
- **Early / late:** negative = ahead of the beat (rushing), positive = behind (dragging, or "laid back" when intentional). Differences under about 5 ms aren't audible.
- **Swing %:** where off-beat 8ths land. 50% is straight (rock, pop), about 67% is triplet swing (shuffle, jazz).
- **Drum grid:** each column is a 16th note, counted "1 e & a 2 e & a…". Dark = hit, darkest = accent, light = ghost note.

## Testing without a drum kit

```bash
.venv/bin/python -m groove synth demo --rush 4 --snare-late 15 --swing 0.6
.venv/bin/python -m groove analyze demo --no-coach
```

`synth` creates a fake take (in `takes/demo/`) with timing flaws you choose, so you can check
that the analysis finds them.

## How it works

- **Finding hits:** [librosa](https://librosa.org) onset detection at about 3 ms resolution. Each drum's timing is refined from its own frequency range, so a laid-back snare isn't merged with the hi-hat it lands alongside.
- **Telling drums apart:** a simple frequency split (kick below 150 Hz, snare 180–2500 Hz, hi-hat above 6 kHz). It's good enough for timing, but toms and cymbals get folded into those three. A trained drum-transcription model (e.g. madmom) could replace `transcribe.label_onsets`.
- **Following your tempo:** the beat grid re-fits itself every 2 bars, so a drummer who speeds up is still matched to the right notes.
- **Coaching:** the timing numbers and your transcribed groove go to `claude-opus-5-5`, which returns structured feedback and patterns. Those are turned into MIDI using your own measured swing.
- **Limits:** assumes 16th-note grooves in 4/4 by default (`--beats-per-bar` for other meters). Triplet fills are snapped to the nearest 16th.

## Project layout

```
groove/
  transcribe.py   audio → hits (librosa)
  analyze.py      hits → timing metrics, swing, groove pattern
  coach.py        metrics → Claude feedback + patterns
  report.py       everything → report.html
  midi.py         hits/patterns → .mid files
  audio.py        click track, recording, latency calibration
  synth.py        fake takes for testing
  cli.py          the `groove` command
run.sh            guided walkthrough
takes/            your recordings and results (not uploaded)
```
