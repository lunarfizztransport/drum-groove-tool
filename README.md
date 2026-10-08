# drum-groove-tool

**Record yourself playing drums, find out exactly how your timing sits, and get
feedback plus new grooves and fills written in your style.**

You play along to a click. The tool works out every hit you made and measures:

- whether you rush or drag;
- how consistent you are;
- which drum is early or late;
- how much you swing.

Claude, Anthropic's AI model, then reads those numbers like a drum teacher
would. It explains what it hears, gives you exercises, and suggests variation
and fill ideas based on what you actually played, as starting points for you
to change and make your own. Everything ends up in one page you open in your
browser, and every idea comes as a MIDI file you can play in GarageBand.

> **Advice, not answers.** The tool's job is to help you hear your own playing
> clearly and find your own voice. The ideas are like a teacher's examples:
> learn one, then bend it, break it, and improvise past it. See
> [About the AI suggestions](#about-the-ai-suggestions).

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
git clone https://github.com/lunarfizztransport/drum-groove-tool.git
cd drum-groove-tool
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
- **Ideas to explore:** variation and fill ideas, each drawn as a grid with ▶ links to hear them and ways to make it yours
- **Your turn:** improvisation challenges with no answers given
- **What the research says:** published studies that put your numbers in context, with sources

The **MIDI files** in `patterns/` open in GarageBand (double-click, then press
Space). Start with the `_in_context` versions. They play your groove, then the
fill, then back to your groove, so you hear how it fits in a song.

| File | What it is |
|---|---|
| `report.html` | **Start here.** Everything, readable |
| `recording.wav` | Your recording |
| `patterns/*.mid` | Variation and fill ideas to listen to |
| `transcription.mid` | Your take as the tool heard it |
| `coaching.md` | Claude's feedback as plain text |
| `analysis.json`, `hits.json`, `coaching.json` | Raw data for the program. You don't need to open these |

## About the AI suggestions

**What they're for.** Improvising is about your own ideas, reacting in the
moment. Nobody starts from nothing, though: drummers have always learned
vocabulary from teachers, records and each other, then made it their own. The
suggestions here are that kind of vocabulary, built from *your* groove and
tendencies. Every idea comes with ways to change it, and the **Your turn**
challenges give you a constraint and leave the playing to you.

**What's sent to the AI.** Only the timing numbers and your groove written as
a grid (e.g. "19 ms ahead of the click, snare on 2 and 4"). Your recording
never leaves your computer. The tool doesn't search for, sample, or copy
anyone's music, and the AI doesn't generate audio. The sounds you hear are
GarageBand's drum kit playing the grid.

**How the AI learned.** Claude is a general AI model, not a music generator.
Anthropic trains it on a mix of public web data, licensed data, and data
from users who opted in. Its general knowledge of drumming comes partly from
lessons and writing that people published online. If you'd rather not use AI
at all, run with `--no-coach`: the timing analysis, charts and groove grid all
work without it.

## Research behind the numbers

Each report has a **What the research says** section that puts your numbers in
context using published studies on timing and groove, with a source list at
the bottom. Every source was checked by hand: the citation matches the
publisher's record, and the finding matches the paper. Claude is told not to
cite studies itself, because a citation an AI writes from memory can't be
trusted. Verified research only comes from `groove/research.py`.

The research mostly covers *how to read the measurements*. The variation and
fill ideas are AI suggestions and don't come from these studies.

Some labels are this tool's rules of thumb rather than research. The spread
bands "typical" (10–20 ms) and "loose" (20–30 ms) are the main ones, and the
report marks them as such.

- Repp, B. H. (2005). Sensorimotor synchronization: A review of the tapping literature. Psychonomic Bulletin & Review, 12(6), 969–992. [doi:10.3758/BF03206433](https://doi.org/10.3758/BF03206433)  
  *People playing along to a regular beat usually land tens of milliseconds early (the 'negative mean asynchrony'), one of the most robust findings in timing research.*
- Repp, B. H. (2010). Sensorimotor synchronization and perception of timing: Effects of music training and task experience. Human Movement Science, 29(2), 200–213. [doi:10.1016/j.humov.2009.08.002](https://doi.org/10.1016/j.humov.2009.08.002)  
  *Trained musicians showed smaller asynchronies, lower tapping variability, and greater sensitivity to timing deviations than students with little training.*
- Friberg, A., & Sundberg, J. (1995). Time discrimination in a monotonic, isochronous sequence. Journal of the Acoustical Society of America, 98(5), 2524–2531. [doi:10.1121/1.413218](https://doi.org/10.1121/1.413218)  
  *The smallest noticeable timing change is about 6 ms for notes under 240 ms apart, and about 2.5% of the gap between notes for gaps of 240–1000 ms.*
- Räsänen, E., Pulkkinen, O., Virtanen, T., Zollner, M., & Hennig, H. (2015). Fluctuations of hi-hat timing and dynamics in a virtuoso drum track of a popular music recording. PLOS ONE, 10(6), e0127902. [doi:10.1371/journal.pone.0127902](https://doi.org/10.1371/journal.pone.0127902)  
  *Jeff Porcaro's hi-hat on "I Keep Forgettin'" (96 bpm): the time between hits varied with a standard deviation of about 8.7 ms.*
- Danielsen, A., Waadeland, C. H., Sundt, H. G., & Witek, M. A. G. (2015). Effects of instructed timing and tempo on snare drum sound in drum kit performance. Journal of the Acoustical Society of America, 138(4), 2301–2316. [doi:10.1121/1.4930950](https://doi.org/10.1121/1.4930950)  
  *Expert drummers asked to play laid-back, on the beat, or pushed could do so deliberately; laid-back snare strokes were also played louder.*
- Câmara, G. S., Sioros, G., & Danielsen, A. (2022). Mapping timing and intensity strategies in drum-kit performance of a simple back-beat pattern. Journal of New Music Research, 51(1), 3–26. [doi:10.1080/09298215.2022.2150649](https://doi.org/10.1080/09298215.2022.2150649)  
  *Drummers expressing laid-back or pushed feels used strategies such as playing everything slightly early/late, or one drum early/late against another.*
- Friberg, A., & Sundström, A. (2002). Swing ratios and ensemble timing in jazz performance: Evidence for a common rhythmic pattern. Music Perception, 19(3), 333–349. [doi:10.1525/mp.2002.19.3.333](https://doi.org/10.1525/mp.2002.19.3.333)  
  *Jazz drummers' ride-cymbal swing ratio fell as tempo rose, from about 3.5:1 at slow tempos toward 1:1 at very fast ones, while the short note stayed around 100 ms.*
- Frühauf, J., Kopiez, R., & Platz, F. (2013). Music on the timing grid: The influence of microtiming on the perceived groove quality of a simple drum pattern performance. Musicae Scientiae, 17(2), 246–260. [doi:10.1177/1029864913486793](https://doi.org/10.1177/1029864913486793)  
  *Listeners rated a perfectly quantized rock drum pattern highest; larger timing displacements got lower groove ratings.*
- Kilchenmann, L., & Senn, O. (2015). Microtiming in swing and funk affects the body movement behavior of music expert listeners. Frontiers in Psychology, 6, 1232. [doi:10.3389/fpsyg.2015.01232](https://doi.org/10.3389/fpsyg.2015.01232)  
  *Expert listeners moved more to music with human microtiming than to quantized versions, contradicting the idea that exact timing is always best.*
- Hennig, H., Fleischmann, R., Fredebohm, A., Hagmayer, Y., Nagler, J., Witt, A., Theis, F. J., & Geisel, T. (2011). The nature and perception of fluctuations in human musical rhythms. PLOS ONE, 6(10), e26457. [doi:10.1371/journal.pone.0026457](https://doi.org/10.1371/journal.pone.0026457)  
  *Human rhythmic performance always drifts in small, long-range-correlated ways, and listeners prefer that over the random 'humanize' fluctuations in music software.*

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
For other time signatures add `--time`, e.g. `record --time 6/8 --bpm 60`.

Useful options for `analyze`:

| Option | Does |
|---|---|
| `--no-coach` | Skip Claude: free, timing analysis only |
| `--goal "..."` | Tell Claude your style and goals so suggestions fit |
| `--bpm 120` | The tempo you played at, for recordings made without the tool's click |
| `--time 6/8` | Time signature (default 4/4). Remembered for the take after the first time |
| `--bpm-note quarter` | Which note your `--bpm` counts, if it isn't the beat (see below) |
| `--mode generic` | Any instrument: timing only, no drum labels |

### Using a recording from your phone or another mic

Laptop mics often struggle with how loud drums are. For cleaner audio, record
on your phone (Voice Memos works) or a better mic, then analyze the file:

```bash
.venv/bin/python -m groove analyze ~/Downloads/"New Recording 3.m4a" --bpm 90
```

It's converted into a new take folder (here `takes/New-Recording-3/`) and
analyzed. WAV, M4A, MP3, AIFF and FLAC all work. Tips:

- **Tempo:** pass `--bpm` with the tempo you played at, if you know it.
- **Metronome:** play along to one in headphones, so the click isn't picked up as hits.
- **Placement:** put the phone a few feet from the kit, not right next to the snare.
- **Count-in:** start recording a few seconds before you play, and say nothing over it.

Without the tool's own click track there's no metronome to compare against,
so you're measured against your own steady pulse. Speeding up, slowing down
and consistency are still accurate; only "ahead of / behind the click" is
missing.

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

## Time signatures

Use `--time` with `record` or `analyze`. Supported: any x/4 (2/4, 3/4, 4/4,
5/4…) and x/8 (5/8, 6/8, 7/8, 9/8, 12/8). 4/4 is the default.

- **x/4:** a 16th-note grid counted "1 e & a 2 e & a…". Swing % is measured.
- **6/8, 9/8, 12/8:** felt as dotted-quarter beats (two per bar in 6/8), each three 8th notes, counted "1 & 2 & 3 & 4 & 5 & 6 &". The click plays every 8th note, with an accent on 1 and a medium click on 4.
- **5/8, 7/8:** 8th-note beats.

**Tempo in 6/8:** `--bpm` counts the beat, so in 6/8 that's dotted quarters
(two per bar). If your metronome counts something else, say which with
`--bpm-note`. For example, a metronome set to 148 in quarter notes:

```bash
.venv/bin/python -m groove analyze ~/Downloads/"New Recording 2.m4a" --time 6/8 --bpm 148 --bpm-note quarter
```

That's converted to 98.7 dotted-quarter beats per minute. Use `--bpm-note eighth`
for a metronome clicking every 8th note.

## Reading the numbers

- **Spread:** how far your hits scatter around your own groove. A professional benchmark is about 9 ms (Jeff Porcaro's hi-hat; see Research). The tool's "typical" and "loose" bands are rules of thumb.
- **Early / late:** negative = ahead of the beat (rushing), positive = behind (dragging, or "laid back" when intentional). The smallest difference people can hear is about 6 ms for fast notes, more for slower ones.
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
- **Limits:** the grid is 16th notes in every time signature. In x/4, triplet fills are snapped to the nearest 16th (use 6/8 or 12/8 for triplet-based grooves). Short takes (under about 30 seconds) give shaky tempo trends.

## Project layout

```
groove/
  transcribe.py   audio → hits (librosa)
  analyze.py      hits → timing metrics, swing, groove pattern
  coach.py        metrics → Claude feedback + patterns
  report.py       everything → report.html
  research.py     verified research sources and notes
  midi.py         hits/patterns → .mid files
  audio.py        click track, recording, latency calibration
  synth.py        fake takes for testing
  cli.py          the `groove` command
run.sh            guided walkthrough
takes/            your recordings and results (not uploaded)
```
