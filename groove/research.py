"""Published research behind the numbers the tool reports.

Every source here was checked by hand: it exists, the citation is right, and
the finding matches what the paper (or its abstract / citing papers) says.
Claude is told not to cite studies itself; the report adds these instead, so
no citation in the output can be made up. Add a source only after checking it
the same way.
"""

from __future__ import annotations

SOURCES = {
    "repp2005": {
        "cite": "Repp, B. H. (2005). Sensorimotor synchronization: A review of the tapping literature. "
                "Psychonomic Bulletin & Review, 12(6), 969–992.",
        "url": "https://doi.org/10.3758/BF03206433",
        "finding": "People playing along to a regular beat usually land tens of milliseconds early "
                   "(the 'negative mean asynchrony'), one of the most robust findings in timing research.",
    },
    "repp2010": {
        "cite": "Repp, B. H. (2010). Sensorimotor synchronization and perception of timing: Effects of music "
                "training and task experience. Human Movement Science, 29(2), 200–213.",
        "url": "https://doi.org/10.1016/j.humov.2009.08.002",
        "finding": "Trained musicians showed smaller asynchronies, lower tapping variability, and greater "
                   "sensitivity to timing deviations than students with little training.",
    },
    "friberg1995": {
        "cite": "Friberg, A., & Sundberg, J. (1995). Time discrimination in a monotonic, isochronous sequence. "
                "Journal of the Acoustical Society of America, 98(5), 2524–2531.",
        "url": "https://doi.org/10.1121/1.413218",
        "finding": "The smallest noticeable timing change is about 6 ms for notes under 240 ms apart, and about "
                   "2.5% of the gap between notes for gaps of 240–1000 ms.",
    },
    "rasanen2015": {
        "cite": "Räsänen, E., Pulkkinen, O., Virtanen, T., Zollner, M., & Hennig, H. (2015). Fluctuations of "
                "hi-hat timing and dynamics in a virtuoso drum track of a popular music recording. "
                "PLOS ONE, 10(6), e0127902.",
        "url": "https://doi.org/10.1371/journal.pone.0127902",
        "finding": "Jeff Porcaro's hi-hat on \"I Keep Forgettin'\" (96 bpm): the time between hits varied "
                   "with a standard deviation of about 8.7 ms.",
    },
    "danielsen2015": {
        "cite": "Danielsen, A., Waadeland, C. H., Sundt, H. G., & Witek, M. A. G. (2015). Effects of instructed "
                "timing and tempo on snare drum sound in drum kit performance. Journal of the Acoustical "
                "Society of America, 138(4), 2301–2316.",
        "url": "https://doi.org/10.1121/1.4930950",
        "finding": "Expert drummers asked to play laid-back, on the beat, or pushed could do so deliberately; "
                   "laid-back snare strokes were also played louder.",
    },
    "camara2022": {
        "cite": "Câmara, G. S., Sioros, G., & Danielsen, A. (2022). Mapping timing and intensity strategies in "
                "drum-kit performance of a simple back-beat pattern. Journal of New Music Research, 51(1), 3–26.",
        "url": "https://doi.org/10.1080/09298215.2022.2150649",
        "finding": "Drummers expressing laid-back or pushed feels used strategies such as playing everything "
                   "slightly early/late, or one drum early/late against another.",
    },
    "friberg2002": {
        "cite": "Friberg, A., & Sundström, A. (2002). Swing ratios and ensemble timing in jazz performance: "
                "Evidence for a common rhythmic pattern. Music Perception, 19(3), 333–349.",
        "url": "https://doi.org/10.1525/mp.2002.19.3.333",
        "finding": "Jazz drummers' ride-cymbal swing ratio fell as tempo rose, from about 3.5:1 at slow tempos "
                   "toward 1:1 at very fast ones, while the short note stayed around 100 ms.",
    },
    "fruhauf2013": {
        "cite": "Frühauf, J., Kopiez, R., & Platz, F. (2013). Music on the timing grid: The influence of "
                "microtiming on the perceived groove quality of a simple drum pattern performance. "
                "Musicae Scientiae, 17(2), 246–260.",
        "url": "https://doi.org/10.1177/1029864913486793",
        "finding": "Listeners rated a perfectly quantized rock drum pattern highest; larger timing "
                   "displacements got lower groove ratings.",
    },
    "kilchenmann2015": {
        "cite": "Kilchenmann, L., & Senn, O. (2015). Microtiming in swing and funk affects the body movement "
                "behavior of music expert listeners. Frontiers in Psychology, 6, 1232.",
        "url": "https://doi.org/10.3389/fpsyg.2015.01232",
        "finding": "Expert listeners moved more to music with human microtiming than to quantized versions, "
                   "contradicting the idea that exact timing is always best.",
    },
    "hennig2011": {
        "cite": "Hennig, H., Fleischmann, R., Fredebohm, A., Hagmayer, Y., Nagler, J., Witt, A., Theis, F. J., "
                "& Geisel, T. (2011). The nature and perception of fluctuations in human musical rhythms. "
                "PLOS ONE, 6(10), e26457.",
        "url": "https://doi.org/10.1371/journal.pone.0026457",
        "finding": "Human rhythmic performance always drifts in small, long-range-correlated ways, and "
                   "listeners prefer that over the random 'humanize' fluctuations in music software.",
    },
}

# Thresholds used in labels that are NOT from research. Kept here so the
# report can say so.
RULES_OF_THUMB = {
    "spread_bands": "The 'typical' (10–20 ms) and 'loose' (20–30 ms) spread labels are this tool's rules of "
                    "thumb, not research findings.",
}


def audible_ms(gap_ms: float) -> float:
    """Smallest noticeable timing change for notes `gap_ms` apart (Friberg & Sundberg 1995)."""
    return 6.0 if gap_ms < 240 else 0.025 * gap_ms


def notes(a: dict) -> list[tuple[str, str, list[str]]]:
    """(title, text, source ids) notes tailored to one take's analysis."""
    out = []
    bpm = a["grid_bpm"]
    slots = a.get("slots_per_beat", 4)
    beat_ms = 60000 / bpm
    six = beat_ms / slots  # ms between 16th notes
    eighth = beat_ms / (3 if slots == 6 else slots / 2)  # 6/8 beats hold three 8ths
    out.append((
        "How small a difference can anyone hear?",
        f"At this tempo your 16th notes are {six:.0f} ms apart and 8th notes {eighth:.0f} ms apart. "
        f"Research puts the smallest noticeable timing change at about {audible_ms(six):.0f} ms for 16ths and "
        f"{audible_ms(eighth):.0f} ms for 8ths at this tempo. Differences smaller than that are below what "
        "listeners can reliably hear.",
        ["friberg1995"],
    ))
    spread = a["tightness"]["std_ms"]
    out.append((
        "What does tight look like?",
        f"Your spread is {spread:.0f} ms. For a professional benchmark, Jeff Porcaro's famous hi-hat part "
        "varied by about 9 ms between hits. (That's a slightly different measure from this tool's spread, "
        "so treat it as a ballpark, not an exact target.) Research also finds trained musicians are less "
        f"variable than beginners, so this number should come down with practice. {RULES_OF_THUMB['spread_bands']}",
        ["rasanen2015", "repp2010"],
    ))
    off = a["tempo"].get("mean_offset_vs_click_ms")
    if off is not None:
        side = "ahead of" if off < 0 else "behind"
        out.append((
            "Why am I ahead of the click?",
            f"You were {abs(off):.0f} ms {side} the click on average. Landing early is one of the most "
            "consistent findings in timing research: most people play tens of milliseconds ahead of a beat "
            "they're following, and trained musicians do it less. It's normal, and it shrinks with practice.",
            ["repp2005", "repp2010"],
        ))
    out.append((
        "Behind the beat can be a choice",
        "Laid-back, on-the-beat and pushed are styles expert drummers play on purpose, for example a snare "
        "slightly behind the hi-hat. So a drum that sits late in the 'By drum' chart isn't automatically a "
        "mistake. What matters is whether it's deliberate and consistent.",
        ["danielsen2015", "camara2022"],
    ))
    if (a["swing"].get("eighth_swing_pct") or 0) >= 53:
        out.append((
            "Swing changes with tempo",
            f"Your 8th notes swing at {a['swing']['eighth_swing_pct']:.0f}%. Jazz drummers swing harder at slow "
            "tempos and flatten out as the tempo rises, so the 'right' amount depends on the tempo.",
            ["friberg2002"],
        ))
    out.append((
        "Tighter isn't automatically better",
        "Research is split here. Listeners rated a perfectly quantized drum pattern highest, but in another "
        "study expert listeners' bodies moved more to music with human timing. Every human performance drifts "
        "in small, connected ways, and listeners prefer that over machine-made randomness. Use these numbers "
        "to get control of your time, not to sound like a machine.",
        ["fruhauf2013", "kilchenmann2015", "hennig2011"],
    ))
    return out
