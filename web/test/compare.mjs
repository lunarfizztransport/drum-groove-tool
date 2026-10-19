// Checks the browser engine (groove.js) against the Python package on the
// same recordings. First write the reference with:
//   .venv/bin/python web/test/reference.py <dir>
// then:
//   node web/test/compare.mjs <dir>
import { readFileSync } from "node:fs";
import { join } from "node:path";
import * as G from "../groove.js";

const dir = process.argv[2];
const ref = JSON.parse(readFileSync(join(dir, "reference.json"), "utf8"));
const kit = JSON.parse(readFileSync(join(dir, "kit-demo.json"), "utf8"));
let failures = 0;
const check = (ok, msg) => { console.log(`${ok ? "  ok  " : "  FAIL"} ${msg}`); if (!ok) failures++; };
const near = (a, b, tol) => a === b || (a != null && b != null && Math.abs(a - b) <= tol);

const settings = {
  demo_kit_click: { kit: true, click: true },
  demo_rules_click: { click: true },
  demo_rules_self: { bpm: 80 },
  demo_generic_self: { mode: "generic" },
  synth44_self: {},
  synth68_self: { meter: "6/8", bpm: 60 },
};

for (const [name, c] of Object.entries(ref.cases)) {
  console.log(`\n${name}`);
  const s = settings[name];
  const { y, sr } = G.decodeWav(new Uint8Array(readFileSync(c.path)));
  check(sr === G.SR, `sample rate ${sr}`);
  const click = s.click ? { bpm: ref.meta.bpm, origin: ref.meta.origin } : null;
  const start = name.startsWith("demo") ? Math.max(0, ref.meta.origin - 60 / ref.meta.bpm / 2) : 0; // as reference.py

  const F = await G.spectralFeatures(y);
  const env = G.onsetStrength(F);
  let maxRel = 0;
  const peak = Math.max(...c.env_head);
  c.env_head.forEach((v, i) => { maxRel = Math.max(maxRel, Math.abs(v - env[i]) / peak); });
  check(maxRel < 1e-3, `onset envelope matches librosa (max error ${(100 * maxRel).toFixed(4)}% of peak)`);
  const frames = G.onsetDetect(env, G.SR, { wait: 10, preMax: 6, postMax: 6 });
  const same = frames.length === c.frames.length && frames.every((f, i) => f === c.frames[i]);
  check(same, `onset frames: ${frames.length} vs ${c.frames.length}${same ? "" : ` (first diff ${frames.find((f, i) => f !== c.frames[i])})`}`);
  const tempo = G.estimateTempo(env);
  check(near(tempo, c.tempo, c.tempo * 0.03) || near(tempo * 2, c.tempo, 3) || near(tempo, c.tempo * 2, 3),
    `tempo estimate ${tempo.toFixed(1)} vs ${c.tempo.toFixed(1)}`);

  const tr = await G.transcribe(y, { mode: s.mode || "drums", start, kit: s.kit ? kit : null });
  const ph = c.hits.hits;
  const key = (h) => `${h.time.toFixed(4)} ${h.instrument} ${h.velocity}`;
  const pyKeys = new Set(ph.map(key));
  const matched = tr.hits.filter((h) => pyKeys.has(key(h))).length;
  check(matched === ph.length && tr.hits.length === ph.length, `hits: ${tr.hits.length} vs ${ph.length}, ${matched} identical (time, drum, velocity)`);
  if (matched !== ph.length) {
    const jsKeys = new Set(tr.hits.map(key));
    console.log("     only python:", ph.filter((h) => !jsKeys.has(key(h))).slice(0, 6).map(key));
    console.log("     only js:    ", tr.hits.filter((h) => !pyKeys.has(key(h))).slice(0, 6).map(key));
  }
  const strip = (w) => w.replace(/ \(System Settings > Sound > Input\)/, ""); // the Mac-only hint is dropped in the browser
  check(JSON.stringify(tr.warnings) === JSON.stringify(c.hits.warnings.map(strip)), `warnings: ${tr.warnings.length} vs ${c.hits.warnings.length}`);

  // Analyze the *Python* hits too, so analysis differences show on their own.
  const meter = G.Meter.parse(s.meter || "4/4");
  const pyTr = { hits: ph, tempoEstimate: c.hits.tempo_estimate };
  const a = G.analyze(pyTr, { bpm: s.bpm || null, meter, click });
  const p = c.analysis;
  const fields = [
    ["grid_bpm", (x) => x.grid_bpm, 0.15], ["n_bars", (x) => x.n_bars, 0], ["n_events", (x) => x.n_events, 0],
    ["spread", (x) => x.tightness.std_ms, 0.15], ["within 10ms", (x) => x.tightness.pct_within_10ms, 0.15],
    ["start bpm", (x) => x.tempo.start_bpm, 0.15], ["end bpm", (x) => x.tempo.end_bpm, 0.15],
    ["drift", (x) => x.tempo.drift_bpm_per_minute, 0.15], ["vs click", (x) => x.tempo.mean_offset_vs_click_ms, 0.15],
    ["swing 8ths", (x) => x.swing.eighth_swing_pct, 0.15], ["swing 16ths", (x) => x.swing.sixteenth_swing_pct, 0.15],
  ];
  for (const [label, f, tol] of fields) check(near(f(a), f(p), tol), `${label}: ${f(a)} vs ${f(p)}`);
  check(JSON.stringify(a.patterns.main_groove) === JSON.stringify(p.patterns.main_groove), "main groove grid identical");
  check(JSON.stringify(a.per_instrument) === JSON.stringify(p.per_instrument) ||
    Object.keys(p.per_instrument).every((k) => near(a.per_instrument[k]?.mean_offset_ms_vs_groove, p.per_instrument[k].mean_offset_ms_vs_groove, 0.15)),
    "per-drum offsets");
  check(a.per_bar.length === p.per_bar.length && a.per_bar.every((b, i) => near(b.mean_offset_ms_vs_grid, p.per_bar[i].mean_offset_ms_vs_grid, 0.15)), "per-bar offsets");
  // Times are displayed to the ms; Python and JS can round x.xxx5 differently.
  const worstOk = a.worst_events.length === p.worst_events.length &&
    a.worst_events.every((w, i) => near(w.time_s, p.worst_events[i].time_s, 0.0011) && w.offset_ms === p.worst_events[i].offset_ms);
  check(worstOk, "worst moments");
}

console.log(failures ? `\n${failures} check(s) failed` : "\nAll checks passed");
process.exit(failures ? 1 : 0);
