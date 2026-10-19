// Drum Groove Tool, browser edition: the analysis engine.
//
// A port of the Python package in ../groove (transcribe.py, analyze.py,
// kit.py, meter.py, research.py, midi.py, synth.py, coach.py). It has no DOM
// code, so it runs in the browser and in Node (see test/compare.mjs, which
// checks it against the Python version on the same recordings).
//
// Sign convention everywhere: positive ms = late (dragging / laid back),
// negative ms = early (rushing / on top).

export const SR = 44100;
export const HOP = 128; // ~2.9 ms per frame: timing resolution of the analysis
export const N_FFT = 2048;
const N_BINS = N_FFT / 2 + 1;
const N_MELS = 128;

const BANDS = { kick: [30, 150], snare: [180, 2500], hihat: [6000, 16000] };
const RISE_DB = 6.0; // band must jump at least this much at the onset to count
// Where to look for each drum's attack when fine-tuning its hit time.
const TIMING_BANDS = {
  ...BANDS, tom_high: [100, 600], tom_mid: [80, 500], tom_floor: [50, 400],
  crash: [3000, 16000], ride: [2000, 12000],
};

// --- small numeric helpers (numpy equivalents) ------------------------------

const sum = (a) => { let s = 0; for (const v of a) s += v; return s; };
const mean = (a) => (a.length ? sum(a) / a.length : NaN);
function std(a) { // population std, like numpy
  const m = mean(a);
  let s = 0;
  for (const v of a) s += (v - m) ** 2;
  return Math.sqrt(s / a.length);
}
function percentile(a, q) { // numpy's default linear interpolation
  const s = Float64Array.from(a).sort();
  if (!s.length) return NaN;
  const pos = (q / 100) * (s.length - 1);
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}
const median = (a) => percentile(a, 50);
const ptp = (a) => Math.max(...a) - Math.min(...a);
const mod = (x, m) => ((x % m) + m) % m;
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
export const r1 = (x) => Math.round(x * 10) / 10;
const argmax = (a) => { let b = 0; for (let i = 1; i < a.length; i++) if (a[i] > a[b]) b = i; return b; };

/** Least squares t = a + b*pos. Returns [a, b]. */
function linfit(pos, t) {
  const n = pos.length;
  const mp = mean(pos), mt = mean(t);
  let sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) { sxy += (pos[i] - mp) * (t[i] - mt); sxx += (pos[i] - mp) ** 2; }
  if (sxx === 0) return [mt, 0];
  const b = sxy / sxx;
  return [mt - b * mp, b];
}

// --- time signatures (meter.py) ----------------------------------------------

const NOTE_QUARTERS = { quarter: 1.0, eighth: 0.5, "dotted-quarter": 1.5 };

export class Meter {
  constructor(num, den) { this.num = num; this.den = den; }
  static parse(text) {
    const m = /^\s*(\d+)\s*\/\s*(\d+)\s*$/.exec(text || "");
    if (!m) throw new Error(`Time signature should look like 4/4 or 6/8, not '${text}'.`);
    const num = +m[1], den = +m[2];
    if (![4, 8].includes(den) || num < 2 || num > 15)
      throw new Error(`Unsupported time signature ${text}: use x/4 or x/8 (e.g. 3/4, 4/4, 6/8, 7/8, 12/8).`);
    return new Meter(num, den);
  }
  get name() { return `${this.num}/${this.den}`; }
  get compound() { return this.den === 8 && this.num % 3 === 0 && this.num >= 6; }
  /** Felt beats per bar (6/8 has 2). */
  get beats() { return this.compound ? this.num / 3 : this.num; }
  /** 16th-note grid slots per beat. */
  get slots() { return this.compound ? 6 : this.den === 4 ? 4 : 2; }
  get stepsPerBar() { return this.beats * this.slots; }
  get beatQuarters() { return this.compound ? 1.5 : this.den === 4 ? 1.0 : 0.5; }
  get beatNote() { return this.compound ? "dotted quarter" : this.den === 4 ? "quarter note" : "eighth note"; }
  /** Swing % only makes sense for straight 8ths/16ths (x/4). */
  get swingable() { return this.den === 4; }
  /** Slot positions within one beat (in beats), plus 1.0 for the next beat. */
  template(s8 = 0.5, s16 = 0.5) {
    if (this.swingable) return [0, s16 * s8, s8, s8 + s16 * (1 - s8), 1];
    return Array.from({ length: this.slots + 1 }, (_, i) => i / this.slots);
  }
  countLabels() {
    const out = [];
    for (let b = 0; b < this.beats; b++)
      for (let k = 0; k < this.slots; k++) {
        if (this.den === 4) out.push(k === 0 ? String(b + 1) : ["", "e", "&", "a"][k]);
        else if (this.compound) out.push(k % 2 === 0 ? String(b * 3 + k / 2 + 1) : "&");
        else out.push(k === 0 ? String(b + 1) : "&");
      }
    return out;
  }
  /** Readable position, e.g. '3', 'e of 2', '& of 4'. */
  countName(slotInBar) {
    const labels = this.countLabels();
    const label = labels[slotInBar];
    if (/^\d+$/.test(label)) return label;
    const prev = labels.slice(0, slotInBar).reverse().find((l) => /^\d+$/.test(l));
    return `${label} of ${prev}`;
  }
  /** Groups of slot-within-beat indices for the 'by count' chart. */
  positionGroups() {
    if (this.den === 4) return [["downbeats", [0]], ["e", [1]], ["&", [2]], ["a", [3]]];
    if (this.compound) {
      const main = Array.from({ length: this.beats }, (_, b) => b * 3 + 1).join(", ");
      return [[`beats (${main})`, [0]], ["2nd 8ths", [2]], ["3rd 8ths", [4]], ["16th &s", [1, 3, 5]]];
    }
    return [["8th notes", [0]], ["16th &s", [1]]];
  }
  /** Convert a tempo counted in `note` to beats per minute. */
  beatBpm(bpm, note) {
    if (!note || note === "beat") return bpm;
    return (bpm * NOTE_QUARTERS[note]) / this.beatQuarters;
  }
}
export const FOUR_FOUR = new Meter(4, 4);

// --- FFT ---------------------------------------------------------------------

const fftCache = new Map();
function fftTables(n) {
  if (fftCache.has(n)) return fftCache.get(n);
  const rev = new Uint32Array(n);
  const bits = Math.log2(n);
  for (let i = 0; i < n; i++) {
    let r = 0;
    for (let b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b);
    rev[i] = r;
  }
  const cos = new Float64Array(n / 2), sin = new Float64Array(n / 2);
  for (let i = 0; i < n / 2; i++) { cos[i] = Math.cos((2 * Math.PI * i) / n); sin[i] = -Math.sin((2 * Math.PI * i) / n); }
  const t = { rev, cos, sin };
  fftCache.set(n, t);
  return t;
}

/** In-place complex FFT (radix 2). re/im: Float64Array of length n (a power of 2). */
export function fft(re, im, inverse = false) {
  const n = re.length;
  const { rev, cos, sin } = fftTables(n);
  for (let i = 0; i < n; i++) {
    const j = rev[i];
    if (j > i) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  const sgn = inverse ? -1 : 1;
  for (let size = 2; size <= n; size *= 2) {
    const half = size / 2, step = n / size;
    for (let i = 0; i < n; i += size)
      for (let j = 0, k = 0; j < half; j++, k += step) {
        const wr = cos[k], wi = sgn * sin[k];
        const a = i + j, b = a + half;
        const tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
        re[b] = re[a] - tr; im[b] = im[a] - ti;
        re[a] += tr; im[a] += ti;
      }
  }
  if (inverse) for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n; }
}

/** |X[k]|^2 for k = 0..N/2 of a real frame of length N, via an N/2 complex FFT. */
function makeRealPower(N) {
  const M = N / 2;
  const re = new Float64Array(M), im = new Float64Array(M);
  const wc = new Float64Array(M + 1), ws = new Float64Array(M + 1);
  for (let k = 0; k <= M; k++) { wc[k] = Math.cos((2 * Math.PI * k) / N); ws[k] = -Math.sin((2 * Math.PI * k) / N); }
  return function (x, out) {
    for (let n = 0; n < M; n++) { re[n] = x[2 * n]; im[n] = x[2 * n + 1]; }
    fft(re, im);
    for (let k = 0; k <= M; k++) {
      const a = k % M, b = (M - k) % M;
      const zr = re[a], zi = im[a], cr = re[b], ci = -im[b]; // Z[k], conj(Z[M-k])
      const er = (zr + cr) / 2, ei = (zi + ci) / 2; // even part
      const dr = (zr - cr) / 2, di = (zi - ci) / 2; // odd part = d / i
      const or = di, oi = -dr;
      const xr = er + wc[k] * or - ws[k] * oi;
      const xi = ei + wc[k] * oi + ws[k] * or;
      out[k] = xr * xr + xi * xi;
    }
  };
}

// --- mel filterbank (librosa.filters.mel, Slaney) -----------------------------

function hzToMel(f) {
  const fsp = 200 / 3, minLogHz = 1000, minLogMel = minLogHz / fsp, logstep = Math.log(6.4) / 27;
  return f >= minLogHz ? minLogMel + Math.log(f / minLogHz) / logstep : f / fsp;
}
function melToHz(m) {
  const fsp = 200 / 3, minLogHz = 1000, minLogMel = minLogHz / fsp, logstep = Math.log(6.4) / 27;
  return m >= minLogMel ? minLogHz * Math.exp(logstep * (m - minLogMel)) : fsp * m;
}
function melBasis(sr) {
  const fmax = sr / 2;
  const fft = Array.from({ length: N_BINS }, (_, k) => (k * sr) / N_FFT);
  const lo = hzToMel(0), hi = hzToMel(fmax);
  const melf = Array.from({ length: N_MELS + 2 }, (_, i) => melToHz(lo + ((hi - lo) * i) / (N_MELS + 1)));
  const filters = [];
  for (let i = 0; i < N_MELS; i++) {
    const enorm = 2 / (melf[i + 2] - melf[i]);
    const w = [];
    let start = -1;
    for (let k = 0; k < N_BINS; k++) {
      const lower = (fft[k] - melf[i]) / (melf[i + 1] - melf[i]);
      const upper = (melf[i + 2] - fft[k]) / (melf[i + 2] - melf[i + 1]);
      const v = Math.max(0, Math.min(lower, upper)) * enorm;
      if (v > 0) { if (start < 0) start = k; w.push(v); } else if (start >= 0) break;
    }
    filters.push({ start: Math.max(start, 0), w: Float64Array.from(w) });
  }
  return filters;
}

function binRange(lo, hi, sr) { // bins with lo <= freq < hi
  let a = Math.ceil((lo * N_FFT) / sr), b = Math.ceil((hi * N_FFT) / sr);
  return [clamp(a, 0, N_BINS), clamp(b, 0, N_BINS)];
}

export const KIT_N_BANDS = 24;
export function bandEdges(sr = SR) {
  const lo = 30, hi = Math.min(16000, sr / 2 - 1);
  return Array.from({ length: KIT_N_BANDS + 1 }, (_, i) => lo * (hi / lo) ** (i / KIT_N_BANDS));
}

/**
 * One pass of a centred STFT (n_fft 2048, hop 128, Hann) over `y`, keeping
 * only what the analysis needs per frame: mel power (for onset strength),
 * the power in each drum's band, total power, and the 24 kit bands.
 */
export async function spectralFeatures(y, sr = SR, onProgress) {
  const nFrames = 1 + Math.floor(y.length / HOP);
  const win = new Float64Array(N_FFT);
  for (let n = 0; n < N_FFT; n++) win[n] = 0.5 - 0.5 * Math.cos((2 * Math.PI * n) / N_FFT);
  const power = makeRealPower(N_FFT);
  const mels = melBasis(sr);
  const bandNames = Object.keys(TIMING_BANDS);
  const bandBins = bandNames.map((b) => binRange(...TIMING_BANDS[b], sr));
  const edges = bandEdges(sr);
  const kitBins = edges.slice(0, -1).map((lo, i) => binRange(lo, edges[i + 1], sr));
  const lowBins = binRange(40, 150, sr), midBins = binRange(150, 2000, sr);

  const mel = new Float32Array(nFrames * N_MELS);
  const bands = Object.fromEntries(bandNames.map((b) => [b, new Float64Array(nFrames)]));
  const total = new Float64Array(nFrames);
  const kit = new Float64Array(nFrames * KIT_N_BANDS);
  let low = 0, mid = 0;

  const frame = new Float64Array(N_FFT), P = new Float64Array(N_BINS);
  const rangeSum = ([a, b]) => { let s = 0; for (let k = a; k < b; k++) s += P[k]; return s; };
  for (let t = 0; t < nFrames; t++) {
    const c = t * HOP - N_FFT / 2;
    for (let n = 0; n < N_FFT; n++) {
      const i = c + n;
      frame[n] = i >= 0 && i < y.length ? y[i] * win[n] : 0;
    }
    power(frame, P);
    for (let m = 0; m < N_MELS; m++) {
      const { start, w } = mels[m];
      let s = 0;
      for (let j = 0; j < w.length; j++) s += w[j] * P[start + j];
      mel[t * N_MELS + m] = s;
    }
    bandNames.forEach((b, i) => { bands[b][t] = rangeSum(bandBins[i]); });
    let tot = 0;
    for (let k = 0; k < N_BINS; k++) tot += P[k];
    total[t] = tot;
    for (let i = 0; i < KIT_N_BANDS; i++) kit[t * KIT_N_BANDS + i] = rangeSum(kitBins[i]);
    low += rangeSum(lowBins); mid += rangeSum(midBins);
    if (onProgress && t % 2000 === 1999) { onProgress(t / nFrames); await new Promise((r) => setTimeout(r)); }
  }
  return { sr, nFrames, mel, bands, total, kit, low, mid };
}

// --- onsets (librosa.onset) -------------------------------------------------------

/** librosa.onset.onset_strength(lag=1, max_size=3) on the mel spectrogram. */
export function onsetStrength(F) {
  const { nFrames, mel } = F;
  const db = new Float32Array(mel.length);
  let top = -Infinity;
  for (let i = 0; i < mel.length; i++) { db[i] = 10 * Math.log10(Math.max(1e-10, mel[i])); if (db[i] > top) top = db[i]; }
  for (let i = 0; i < db.length; i++) db[i] = Math.max(db[i], top - 80);
  const raw = new Float64Array(Math.max(0, nFrames - 1));
  for (let t = 1; t < nFrames; t++) {
    let s = 0;
    for (let m = 0; m < N_MELS; m++) {
      const p = (t - 1) * N_MELS;
      // reference: max over neighbouring mel bands (edges reflect, i.e. repeat)
      const ref = Math.max(db[p + Math.max(0, m - 1)], db[p + m], db[p + Math.min(N_MELS - 1, m + 1)]);
      s += Math.max(0, db[t * N_MELS + m] - ref);
    }
    raw[t - 1] = s / N_MELS;
  }
  const pad = 1 + N_FFT / (2 * HOP); // lag + centring compensation, as librosa does
  const env = new Float64Array(nFrames);
  for (let t = pad; t < nFrames; t++) env[t] = raw[t - pad];
  return env;
}

/** librosa.util.peak_pick, exactly as its numba kernel. */
function peakPick(x, { preMax, postMax, preAvg, postAvg, delta, wait }) {
  const n = x.length, peaks = [];
  if (!n) return peaks;
  const maxOf = (a, b) => { let m = -Infinity; for (let i = a; i < b; i++) if (x[i] > m) m = x[i]; return m; };
  const meanOf = (a, b) => { let s = 0; for (let i = a; i < b; i++) s += x[i]; return s / (b - a); };
  let first = x[0] >= maxOf(0, Math.min(postMax, n)) && x[0] >= meanOf(0, Math.min(postAvg, n)) + delta;
  if (first) peaks.push(0);
  let i = first ? wait + 1 : 1;
  while (i < n) {
    if (x[i] !== maxOf(Math.max(0, i - preMax), Math.min(i + postMax, n))) { i++; continue; }
    if (!(x[i] >= meanOf(Math.max(0, i - preAvg), Math.min(i + postAvg, n)) + delta)) { i++; continue; }
    peaks.push(i);
    i += wait + 1;
  }
  return peaks;
}

/** librosa.onset.onset_detect(onset_envelope=env, ...): returns frame indices. */
export function onsetDetect(env, sr, opts = {}) {
  let lo = Infinity, hi = -Infinity;
  for (const v of env) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  if (!(hi > lo)) return [];
  const x = Float64Array.from(env, (v) => (v - lo) / (hi - lo + 1e-300));
  const f = (s) => Math.floor((s * sr) / HOP);
  return peakPick(x, {
    preMax: opts.preMax ?? f(0.03), postMax: opts.postMax ?? 1,
    preAvg: f(0.1), postAvg: f(0.1) + 1, delta: 0.07, wait: opts.wait ?? f(0.03),
  });
}

/** A tempo estimate (bpm) from the onset envelope, like librosa.feature.tempo. */
export function estimateTempo(env, sr = SR) {
  const win = Math.floor((8 * sr) / HOP);
  const n = env.length;
  if (n < 16) return 120;
  // linear-ramp padding by win/2 on each side, then Hann-windowed local
  // autocorrelations, averaged (sampled every 32 frames)
  const half = Math.floor(win / 2);
  const padded = new Float64Array(n + 2 * half);
  for (let i = 0; i < half; i++) { padded[i] = (env[0] * i) / half; padded[n + 2 * half - 1 - i] = (env[n - 1] * i) / half; }
  padded.set(env, half);
  const size = 2 ** Math.ceil(Math.log2(2 * win));
  const hann = Float64Array.from({ length: win }, (_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / win));
  const acc = new Float64Array(win);
  let count = 0;
  const re = new Float64Array(size), im = new Float64Array(size);
  for (let t = 0; t + win <= padded.length; t += 32) {
    re.fill(0); im.fill(0);
    for (let i = 0; i < win; i++) re[i] = padded[t + i] * hann[i];
    fft(re, im);
    for (let k = 0; k < size; k++) { re[k] = re[k] * re[k] + im[k] * im[k]; im[k] = 0; }
    fft(re, im, true);
    const norm = Math.abs(re[0]) || 1;
    for (let l = 0; l < win; l++) acc[l] += re[l] / norm;
    count++;
  }
  let best = 120, bestScore = -Infinity;
  for (let lag = 1; lag < win; lag++) {
    const bpm = (60 * sr) / (HOP * lag);
    if (bpm > 320) continue;
    const prior = -0.5 * ((Math.log2(bpm) - Math.log2(120)) / 1.0) ** 2;
    const score = Math.log1p(1e6 * Math.max(0, acc[lag] / count)) + prior;
    if (score > bestScore) { bestScore = score; best = bpm; }
  }
  return best;
}

const toDb = (arr) => Float64Array.from(arr, (v) => 10 * Math.log10(v + 1e-10));
const framesToTime = (f, sr = SR) => (f * HOP) / sr;

// --- transcription (transcribe.py) -------------------------------------------------

/**
 * Detect hits in mono audio at 44.1 kHz.
 * mode "drums" labels each onset kick/snare/hihat (possibly several at once);
 * "generic" labels every onset "hit". Hits before `start` seconds are dropped.
 * kit: a learned kit profile (much better labels than the band rules).
 */
export async function transcribe(y, { mode = "drums", start = 0, kit = null, onProgress } = {}) {
  const sr = SR;
  const duration = y.length / sr;
  const F = await spectralFeatures(y, sr, onProgress);
  const warnings = audioChecks(y, F, mode);
  const env = onsetStrength(F);
  let frames = onsetDetect(env, sr, {
    wait: Math.floor((0.03 * sr) / HOP), preMax: Math.floor((0.02 * sr) / HOP), postMax: Math.floor((0.02 * sr) / HOP),
  });
  const tempo = estimateTempo(env, sr);
  frames = frames.filter((f) => framesToTime(f) >= start);
  if (!frames.length) return { hits: [], tempoEstimate: tempo, duration, mode, warnings };

  const velocities = onsetVelocities(F, frames);
  let hits;
  if (mode === "generic") {
    hits = frames.map((f, i) => ({ time: round4(framesToTime(f)), instrument: "hit", velocity: velocities[i] }));
  } else {
    const labels = kit ? kitLabel(F, frames, kit) : labelOnsets(F, frames);
    const bands = Object.fromEntries(Object.entries(F.bands).map(([k, v]) => [k, toDb(v)]));
    hits = [];
    frames.forEach((f, i) => {
      for (const inst of labels[i])
        hits.push({ time: round4(refine(bands[inst], f, framesToTime(f), sr)), instrument: inst, velocity: velocities[i] });
    });
  }
  return { hits, tempoEstimate: tempo, duration, mode, warnings };
}
const round4 = (x) => Math.round(x * 1e4) / 1e4;
const roundHalfEven = (x) => { const f = Math.floor(x), d = x - f; return d > 0.5 || (d === 0.5 && f % 2) ? f + 1 : f; };

/** Recording problems that make results unreliable, in plain language. */
function audioChecks(y, F, mode) {
  const out = [];
  let peak = 0;
  for (const v of y) peak = Math.max(peak, Math.abs(v));
  let clipped = 0;
  if (peak > 0) for (const v of y) if (Math.abs(v) >= 0.99 * peak) clipped++;
  if (peak >= 0.98 && clipped / y.length > 0.0003)
    out.push("The recording is distorting: the drums were too loud for the mic. Move it further from the kit or turn the input volume down.");
  if (mode === "drums" && F.low < F.mid * 10 ** (-10 / 10))
    out.push("The recording has very little bass, so the kick drum is hard to hear. Laptop mics often miss it; a phone placed a few feet in front of the kick usually works better.");
  return out;
}

/** Re-time one instrument from its own band's steepest rise near the onset. */
function refine(band, frame, t, sr, radius = 10) {
  const lo = Math.max(1, frame - radius), hi = Math.min(band.length, frame + radius + 1);
  if (hi - lo < 2) return t;
  let best = 0, bestRise = -Infinity;
  for (let j = 0; j < hi - lo; j++) {
    const rise = band[lo + j] - band[lo + j - 1];
    if (rise > bestRise) { bestRise = rise; best = j; }
  }
  return framesToTime(lo + best, sr) + N_FFT / 2 / sr;
}

/** Guess which kit pieces sound at each onset frame (built-in band rules). */
function labelOnsets(F, frames) {
  const bands = Object.fromEntries(Object.keys(BANDS).map((b) => [b, toDb(F.bands[b])]));
  const n = F.nFrames;
  const pre = {}, post = {}, rise = {}, ref = {};
  for (const [b, v] of Object.entries(bands)) {
    pre[b] = frames.map((f) => median(v.slice(Math.max(0, f - 16), Math.max(1, f - 8))));
    post[b] = frames.map((f) => Math.max(...v.slice(f, Math.min(n, f + 10))));
    rise[b] = post[b].map((p, i) => p - pre[b][i]);
    ref[b] = percentile(post[b], 95);
  }
  return frames.map((_, i) => {
    const lo = post.kick[i], mid = post.snare[i], hi = post.hihat[i];
    const insts = [];
    if (rise.kick[i] >= RISE_DB && lo >= ref.kick - 15 && lo >= mid - 3) insts.push("kick");
    if (rise.snare[i] >= RISE_DB && mid >= ref.snare - 15 && mid >= lo - 10) insts.push("snare");
    if (rise.hihat[i] >= RISE_DB && hi >= ref.hihat - 20) insts.push("hihat");
    if (!insts.length) {
      // Something was detected but no band rule fired: take the band that is
      // closest to its own loud reference.
      const names = Object.keys(bands);
      insts.push(names[argmax(names.map((b) => post[b][i] - ref[b]))]);
    }
    return insts;
  });
}

/** Map each onset's peak frame energy onto MIDI velocity (40 dB range). */
function onsetVelocities(F, frames) {
  const db = toDb(F.total);
  const n = F.nFrames;
  const peaks = frames.map((f) => Math.max(...db.slice(f, Math.min(n, f + 10))));
  const top = percentile(peaks, 98);
  return peaks.map((p) => Math.max(1, roundHalfEven(127 * clamp((p - (top - 40)) / 40, 0, 1))));
}

// --- kit profiles (kit.py) -------------------------------------------------------------

export const DRUMS = ["kick", "snare", "hihat"];
export const ALL_DRUMS = ["kick", "snare", "hihat", "tom_high", "tom_mid", "tom_floor", "crash", "ride"];
export const SPOKEN = { kick: "KICK", snare: "SNARE", hihat: "closed HI-HAT", tom_high: "HIGH TOM", tom_mid: "MID TOM",
  tom_floor: "FLOOR TOM", crash: "CRASH cymbal", ride: "RIDE cymbal" };
const MIN_SHARE = 0.02; // a drum must explain at least this much of a hit
const MIN_LEVEL = 0.1; // ...and be at least this loud relative to that drum's strong hits
const LEVEL_FOR = { crash: 0.35, ride: 0.35 }; // cymbals ring, so they need a bigger part to count
export const HITS_PER_DRUM = 4;

/** Energy each onset adds per log-spaced band (post minus pre), shape [onsets][24]. */
function onsetSpectra(F, frames) {
  const n = F.nFrames, B = KIT_N_BANDS;
  return frames.map((f) => {
    const out = new Array(B);
    for (let b = 0; b < B; b++) {
      const preVals = [];
      for (let t = Math.max(0, f - 16); t < Math.max(1, f - 8); t++) preVals.push(F.kit[t * B + b]);
      let post = -Infinity;
      for (let t = f; t < Math.min(n, f + 10); t++) post = Math.max(post, F.kit[t * B + b]);
      out[b] = Math.max(post - median(preVals), 0);
    }
    return out;
  });
}

/** Label each onset with the drums whose learned sound explains it. */
function kitLabel(F, frames, profile) {
  const drums = profile.drums || DRUMS;
  const T = drums.map((d) => profile.templates[d]); // [drum][band]
  const B = KIT_N_BANDS;
  // Gently weight bands so quiet ranges (hi-hat) aren't drowned out by loud ones (kick).
  const w = Array.from({ length: B }, (_, b) => Math.sqrt(mean(T.map((t) => t[b]))) + 1e-12);
  const A = Array.from({ length: B }, (_, b) => T.map((t) => t[b] / w[b])); // [band][drum]
  const R = onsetSpectra(F, frames).map((r) => r.map((v, b) => v / w[b]));
  const G = R.map((r) => nnls(A, r));
  const strong = drums.map((_, j) => percentile(G.map((g) => g[j]), 90) + 1e-12);
  return G.map((g) => {
    const tot = sum(g) + 1e-12;
    const share = g.map((v) => v / tot);
    const hit = drums.filter((d, j) => share[j] >= MIN_SHARE && g[j] >= (LEVEL_FOR[d] ?? MIN_LEVEL) * strong[j]);
    return hit.length ? hit : [drums[argmax(share)]];
  });
}

/** Non-negative least squares (Lawson-Hanson): min |A x - b|, x >= 0. A: [m][n]. */
export function nnls(A, b) {
  const m = A.length, n = A[0].length;
  const x = new Array(n).fill(0);
  const passive = new Array(n).fill(false);
  const grad = () => Array.from({ length: n }, (_, j) => {
    let s = 0;
    for (let i = 0; i < m; i++) { let ax = 0; for (let k = 0; k < n; k++) ax += A[i][k] * x[k]; s += A[i][j] * (b[i] - ax); }
    return s;
  });
  const solve = (P) => { // unconstrained least squares on columns P
    const p = P.length;
    const M = Array.from({ length: p }, () => new Array(p + 1).fill(0));
    for (let a = 0; a < p; a++) {
      for (let c = 0; c < p; c++) { let s = 0; for (let i = 0; i < m; i++) s += A[i][P[a]] * A[i][P[c]]; M[a][c] = s; }
      let s = 0; for (let i = 0; i < m; i++) s += A[i][P[a]] * b[i]; M[a][p] = s;
    }
    for (let c = 0; c < p; c++) { // Gaussian elimination with partial pivoting
      let piv = c;
      for (let r = c + 1; r < p; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
      [M[c], M[piv]] = [M[piv], M[c]];
      const d = M[c][c] || 1e-300;
      for (let r = 0; r < p; r++) if (r !== c) { const f = M[r][c] / d; for (let k = c; k <= p; k++) M[r][k] -= f * M[c][k]; }
    }
    return M.map((row, i) => row[p] / (row[i] || 1e-300));
  };
  const tol = 1e-12;
  for (let iter = 0; iter < 3 * n + 10; iter++) {
    const g = grad();
    let j = -1, best = tol;
    for (let k = 0; k < n; k++) if (!passive[k] && g[k] > best) { best = g[k]; j = k; }
    if (j < 0) break;
    passive[j] = true;
    for (let inner = 0; inner < 3 * n + 10; inner++) {
      const P = passive.map((v, k) => (v ? k : -1)).filter((k) => k >= 0);
      const z = solve(P);
      if (z.every((v) => v > 0)) { P.forEach((k, i) => { x[k] = z[i]; }); break; }
      let alpha = Infinity;
      P.forEach((k, i) => { if (z[i] <= 0) alpha = Math.min(alpha, x[k] / (x[k] - z[i])); });
      P.forEach((k, i) => { x[k] += alpha * (z[i] - x[k]); if (x[k] <= tol) { x[k] = 0; passive[k] = false; } });
    }
  }
  return x;
}

async function kitOnsets(y) {
  const F = await spectralFeatures(y, SR);
  const env = onsetStrength(F);
  const frames = onsetDetect(env, SR, { wait: Math.floor((0.25 * SR) / HOP) });
  return { F, frames, strength: frames.map((f) => env[f]) };
}

/** You played n hits; anything beyond the n strongest is ringing or echo, not a hit. */
function strongest(idx, strength, n = HITS_PER_DRUM) {
  return [...idx].sort((a, b) => strength[b] - strength[a]).slice(0, n).sort((a, b) => a - b);
}

/** Typical (median) sound of a drum, so a stray extra onset barely matters. */
function template(spectra) {
  const norm = spectra.map((s) => { const t = sum(s) + 1e-12; return s.map((v) => v / t); });
  const t = norm[0].map((_, b) => median(norm.map((s) => s[b])));
  const tot = sum(t) || 1;
  return t.map((v) => v / tot);
}

function makeProfile(spectra, source) {
  const drums = Object.keys(spectra);
  return {
    learned: new Date().toISOString().slice(0, 10),
    source,
    drums,
    hits: Object.fromEntries(drums.map((d) => [d, spectra[d].length])),
    band_edges_hz: bandEdges().map(r1),
    templates: Object.fromEntries(drums.map((d) => [d, template(spectra[d])])),
  };
}

/**
 * Learn one drum from its own short recording (the guided, one-drum-at-a-time
 * flow). Returns {spectra, n, extra} or throws if fewer than 2 hits were heard.
 */
export async function learnDrumClip(y) {
  const { F, frames: all, strength } = await kitOnsets(y);
  let frames = all;
  let extra = 0;
  if (all.length > HITS_PER_DRUM) {
    extra = all.length - HITS_PER_DRUM;
    frames = strongest(all.map((_, i) => i), strength).map((i) => all[i]);
  }
  if (frames.length < 2) throw new Error(`Only heard ${frames.length}. Play a bit louder or closer to the mic, and try again.`);
  return { spectra: onsetSpectra(F, frames), n: frames.length, extra };
}
export const profileFromClips = (spectraByDrum, source = "computer mic") => makeProfile(spectraByDrum, source);

/** A recording of 4 hits on each drum in `drums`, in that order, with a pause between drums. */
export async function learnFromRecording(y, drums = DRUMS, source = "recording") {
  const { F, frames, strength } = await kitOnsets(y);
  const order = drums.map((d) => `4 ${SPOKEN[d].toLowerCase()}`).join(", wait, ");
  if (frames.length < 2 * drums.length) throw new Error(`Only heard ${frames.length} hits for ${drums.length} drums. Play ${order}.`);
  const times = frames.map((f) => framesToTime(f));
  const gaps = times.slice(1).map((t, i) => t - times[i]);
  // The longest pauses separate the drums.
  const split = gaps.map((g, i) => i).sort((a, b) => gaps[b] - gaps[a]).slice(0, drums.length - 1).sort((a, b) => a - b);
  const groups = [];
  let s = 0;
  for (const i of split) { groups.push(range(s, i + 1)); s = i + 1; }
  groups.push(range(s, frames.length));
  const inner = groups.filter((g) => g.length > 1).flatMap((g) => g.slice(1).map((i) => times[i] - times[i - 1]));
  const within = inner.length ? median(inner) : 0.5;
  if (Math.min(...split.map((i) => gaps[i])) < 1.5 * within || groups.some((g) => g.length < 2)) {
    throw new Error(`Couldn't find ${drums.length} separate groups of hits (heard groups of ${groups.map((g) => g.length).join(", ")}). ` +
      `Play ${order}, waiting about 3 seconds between drums.`);
  }
  const spectra = onsetSpectra(F, frames);
  const clips = {};
  const byDrum = {};
  drums.forEach((d, k) => {
    const g = groups[k];
    const t0 = Math.max(0, times[g[0]] - 0.3), t1 = Math.min(y.length / SR, times[g[g.length - 1]] + 0.9);
    clips[d] = y.slice(Math.floor(t0 * SR), Math.floor(t1 * SR));
    byDrum[d] = strongest(g, strength).map((i) => spectra[i]);
  });
  return { profile: makeProfile(byDrum, source), clips };
}
const range = (a, b) => Array.from({ length: b - a }, (_, i) => a + i);

/** Sanity-check a freshly learned profile; returns problems worth redoing it for. */
export function checkProfile(profile) {
  const problems = [];
  for (const [d, n] of Object.entries(profile.hits))
    if (n < 3) problems.push(`Only heard ${n} ${d} hit(s); 4 clear hits per drum work best.`);
  const b = {};
  for (const d of ["kick", "snare", "hihat"]) if (profile.templates[d]) b[d] = brightness(profile, d);
  if (Object.keys(b).length === 3 && !(b.kick < b.snare && b.snare < b.hihat))
    problems.push("The learned sounds don't line up the way real drums do (kick should be the deepest, hi-hat the " +
      `brightest; got kick ~${b.kick.toFixed(0)} Hz, snare ~${b.snare.toFixed(0)} Hz, hi-hat ~${b.hihat.toFixed(0)} Hz). ` +
      "The mic may be missing the bass or treble, or hits were played at the wrong prompt.");
  return problems;
}
/** Spectral centroid on a log-frequency scale, in Hz. */
export function brightness(profile, d) {
  const e = profile.band_edges_hz;
  const t = profile.templates[d];
  let s = 0;
  t.forEach((v, i) => { s += v * Math.log(Math.sqrt(e[i] * e[i + 1])); });
  return Math.exp(s / sum(t));
}

// --- timing analysis (analyze.py) ------------------------------------------------------

/**
 * tr: {hits, tempoEstimate}. bpm counts the meter's beat (dotted quarters in 6/8).
 * click: {bpm, origin: seconds of first downbeat after count-in}.
 */
export function analyze(tr, { bpm = null, meter = FOUR_FOUR, click = null } = {}) {
  const beatsPerBar = meter.beats, slots = meter.slots;
  if (tr.hits.length < 8) throw new Error(`Only ${tr.hits.length} hits detected; record at least a few bars.`);

  // Collapse simultaneous hits (e.g. kick+hihat) into one timing event.
  const byTime = new Map();
  for (const h of tr.hits) { if (!byTime.has(h.time)) byTime.set(h.time, []); byTime.get(h.time).push(h); }
  let times = [...byTime.keys()].sort((a, b) => a - b);
  let insts = times.map((t) => new Set(byTime.get(t).map((h) => h.instrument)));

  let beat, origin, reference;
  if (click) {
    beat = 60 / click.bpm; origin = click.origin; reference = "click";
  } else {
    // Phase + downbeat from the opening bars only: a drifting player makes
    // any single global grid wrong by the end of the take.
    beat = 60 / (bpm || foldTempo(tr.tempoEstimate, meter));
    const early = times.map((t) => t < times[0] + 2 * beat * beatsPerBar);
    const weights = insts.map((s) => (s.has("kick") || s.has("snare") ? 2 : 1));
    const et = times.filter((_, i) => early[i]);
    [origin, beat] = fitPhase(et, beat, weights.filter((_, i) => early[i]), slots);
    origin = pickDownbeat(et, insts.filter((_, i) => early[i]), origin, beat, meter, byTime);
    reference = "self";
  }
  let bar = beat * beatsPerBar;
  origin = firstDownbeat(origin, times[0], bar, beat);

  // Quantize with a grid that follows the player's tempo, detect swing, repeat.
  let s8 = 0.5, s16 = 0.5;
  let tracked;
  for (let i = 0; i < (meter.swingable ? 2 : 0); i++) {
    tracked = track(times, origin, beat, meter.template(s8, s16), slots, 2 * beatsPerBar);
    [s8, s16] = detectSwing(tracked.xs);
  }
  tracked = track(times, origin, beat, meter.template(s8, s16), slots, 2 * beatsPerBar);
  let { ps: pos, idx: slot } = tracked;

  if (reference === "self") { [origin, beat] = robustFit(times, pos); bar = beat * beatsPerBar; }
  let dev = times.map((t, i) => (t - (origin + pos[i] * beat)) * 1000); // vs steady grid / click
  let local = localResidual(times, pos, beatsPerBar).map((v) => v * 1000); // placement in the groove
  const keep = slot.map((s) => s >= 0);
  const k = (a) => a.filter((_, i) => keep[i]);
  times = k(times); pos = k(pos); dev = k(dev); local = k(local); slot = k(slot); insts = k(insts);

  const spb = meter.stepsPerBar;
  const barsIdx = slot.map((s) => Math.floor(s / spb));
  const slotInBar = slot.map((s) => mod(s, spb));
  const nBars = Math.max(...barsIdx) + 1;

  const result = {
    reference,
    time_signature: meter.name,
    beats_per_bar: beatsPerBar,
    beat_note: meter.beatNote,
    slots_per_beat: slots,
    count_labels: meter.countLabels(),
    grid_bpm: r1(60 / beat),
    target_bpm: click ? r1(click.bpm) : null,
    n_events: times.length,
    n_bars: nBars,
    tightness: tightness(local),
    tempo: tempoReport(times, pos, barsIdx, dev, reference),
    swing: meter.swingable ? {
      eighth_swing_pct: r1(s8 * 100), sixteenth_swing_pct: r1(s16 * 100), feel: swingWord(s8, s16),
      note: "50% = straight, 66.7% = triplet swing (MPC-style percentages).",
    } : {
      eighth_swing_pct: null, sixteenth_swing_pct: null,
      feel: meter.compound ? `${meter.name}: 8th notes grouped in threes` : `${meter.name}: straight 8ths`,
      note: "Swing % isn't measured in this time signature.",
    },
    per_instrument: {},
    per_beat_position: {},
    per_bar: [],
  };

  for (const name of [...new Set(insts.flatMap((s) => [...s]))].sort()) {
    const l = local.filter((_, i) => insts[i].has(name)), d = dev.filter((_, i) => insts[i].has(name));
    result.per_instrument[name] = { count: l.length, mean_offset_ms_vs_groove: r1(mean(l)), std_ms: r1(std(l)), mean_offset_ms_vs_grid: r1(mean(d)) };
  }
  const beatPos = slotInBar.map((s) => s % slots);
  for (const [label, ks] of meter.positionGroups()) {
    const l = local.filter((_, i) => ks.includes(beatPos[i]));
    if (l.length >= 3) result.per_beat_position[label] = { count: l.length, mean_offset_ms: r1(mean(l)), std_ms: r1(std(l)) };
  }
  for (let b = 0; b < nBars; b++) {
    const m = barsIdx.map((x) => x === b);
    if (!m.some(Boolean)) continue;
    const d = dev.filter((_, i) => m[i]), l = local.filter((_, i) => m[i]);
    result.per_bar.push({ bar: b + 1, start_s: Math.round((origin + b * bar) * 1000) / 1000, events: d.length,
      mean_offset_ms_vs_grid: r1(mean(d)), std_ms: r1(std(l)) });
  }

  result.patterns = patterns(byTime, times, barsIdx, slotInBar, spb, nBars);
  result.worst_events = local.map((v, i) => i).sort((a, b) => Math.abs(local[b]) - Math.abs(local[a])).slice(0, 8).map((i) => ({
    time_s: Math.round(times[i] * 1000) / 1000,
    bar: barsIdx[i] + 1,
    count: meter.countName(slotInBar[i]),
    instruments: [...insts[i]].sort(),
    offset_ms: r1(local[i]),
  }));
  return result;
}

/** Bring an automatic tempo estimate into a plausible range for the meter's beat. */
function foldTempo(bpm, meter) {
  const [lo, hi] = meter.compound ? [40, 130] : [65, 180];
  if (meter.compound) bpm *= 2 / 3;
  while (bpm < lo) bpm *= 2;
  while (bpm > hi) bpm /= 2;
  return bpm;
}

/** Shift origin by whole bars so it is the last downbeat at/before the first hit. */
const firstDownbeat = (origin, t0, bar, beat) => origin + Math.floor((t0 - origin + beat / 8) / bar) * bar;

/** Jointly fit beat length (+-8%) and 16th-grid phase to a short stretch of hits. */
function fitPhase(times, beat, weights, slots) {
  let best = [Infinity, 0, beat];
  const t = times.map((x) => x - times[0]);
  for (let s = 0; s < 81; s++) {
    const b = beat * (0.92 + (0.16 * s) / 80);
    const step = b / slots;
    for (let ph = 0; ph < step; ph += 0.0005) {
      let cost = 0;
      for (let i = 0; i < t.length; i++) {
        const d = mod(t[i] - ph + step / 2, step) - step / 2;
        cost += Math.min(Math.abs(d), 0.03) ** 2 * weights[i];
      }
      if (cost < best[0]) best = [cost, ph + times[0], b];
    }
  }
  return [best[1], best[2]];
}

/** Choose which grid slot is beat 1: kick on 1, snare on the 2nd/4th beat, accents on beats. */
function pickDownbeat(times, insts, origin, beat, meter, byTime) {
  const step = beat / meter.slots;
  let best = origin, bestScore = -Infinity;
  for (let shift = 0; shift < meter.stepsPerBar; shift++) {
    const o = origin + shift * step;
    const slot = times.map((t) => mod(Math.round((t - o) / step), meter.stepsPerBar));
    let score = slot[0] === 0 ? 3 : 0; // people usually start on 1
    times.forEach((t, i) => {
      const sl = slot[i], s = insts[i];
      const onBeat = sl % meter.slots === 0;
      const beatNum = Math.floor(sl / meter.slots);
      if (onBeat) score += Math.max(...byTime.get(t).map((h) => h.velocity)) / 127;
      if (s.has("kick") && sl === 0) score += 2;
      if (s.has("snare") && onBeat && beatNum % 2 === 1) score += 2;
    });
    if (score > bestScore) { best = o; bestScore = score; }
  }
  return best;
}

/** Median position of the offbeat 8th (s8) and of offbeat 16ths within their 8th (s16). */
function detectSwing(x) {
  const frac = x.map((v) => mod(v, 1));
  const off8 = frac.filter((f) => f > 0.42 && f < 0.74);
  const s8 = off8.length >= 4 ? median(off8) : 0.5;
  const e = frac.filter((f) => f > 0.15 && f < s8 * 0.8).map((f) => f / s8);
  const a = frac.filter((f) => f > s8 + (1 - s8) * 0.2 && f < 0.92).map((f) => (f - s8) / (1 - s8));
  const sixteenths = [...e, ...a];
  const s16 = sixteenths.length >= 4 ? median(sixteenths) : 0.5;
  return [clamp(s8, 0.5, 0.75), clamp(s16, 0.5, 0.75)];
}

/** Quantize hits in order against the grid template, refitting to the last `window` beats after every hit. */
function track(times, origin, beat, tpl, slots, window) {
  let a = origin, p = beat;
  const xs = [], ps = [], idx = [];
  times.forEach((t, i) => {
    const x = (t - a) / p;
    const b = Math.floor(x);
    let kk = 0;
    for (let j = 1; j < tpl.length; j++) if (Math.abs(x - b - tpl[j]) < Math.abs(x - b - tpl[kk])) kk = j;
    xs.push(x); ps.push(b + tpl[kk]); idx.push(b * slots + kk);
    const sel = [];
    for (let j = 0; j <= i; j++) if (ps[j] >= ps[i] - window) sel.push(j);
    if (sel.length >= 4) {
      const P = sel.map((j) => ps[j]);
      if (ptp(P) >= 2) {
        const [an, pn] = robustFit(sel.map((j) => times[j]), P);
        if (0.85 * beat < pn && pn < 1.15 * beat) { a = an; p = pn; }
      }
    }
  });
  return { xs, ps, idx };
}

/** Each hit's offset (s) from a straight line through the hits within one bar either side. */
function localResidual(times, pos, beatsPerBar) {
  return pos.map((q, i) => {
    const sel = [];
    pos.forEach((p, j) => { if (Math.abs(p - q) <= beatsPerBar) sel.push(j); });
    if (sel.length < 4) return 0;
    const P = sel.map((j) => pos[j]);
    if (ptp(P) <= 0) return 0;
    const [a, p] = robustFit(sel.map((j) => times[j]), P);
    return times[i] - (a + p * q);
  });
}

/** Least squares t = origin + beat*pos, dropping >40 ms outliers once. */
function robustFit(times, pos) {
  let [a, b] = linfit(pos, times);
  const m = times.map((t, i) => Math.abs(t - (a + b * pos[i])) < 0.04);
  if (m.filter(Boolean).length >= 4) [a, b] = linfit(pos.filter((_, i) => m[i]), times.filter((_, i) => m[i]));
  return [a, b];
}

function tightness(local) {
  const a = local.map(Math.abs);
  return {
    std_ms: r1(std(local)),
    pct_within_10ms: r1((100 * a.filter((v) => v <= 10).length) / a.length),
    pct_within_20ms: r1((100 * a.filter((v) => v <= 20).length) / a.length),
    note: "Measured against your own local groove (slow drift removed).",
  };
}

function tempoReport(times, pos, barsIdx, dev, reference) {
  const curve = [], mids = [];
  const nb = Math.max(...barsIdx) + 1;
  for (let b = 0; b < nb; b++) {
    const sel = barsIdx.map((x, i) => (x >= b - 1 && x <= b ? i : -1)).filter((i) => i >= 0); // 2-bar window
    const here = barsIdx.map((x, i) => (x === b ? i : -1)).filter((i) => i >= 0);
    if (sel.length >= 4 && ptp(sel.map((i) => pos[i])) >= 1 && here.length) {
      const slope = linfit(sel.map((i) => pos[i]), sel.map((i) => times[i]))[1];
      curve.push({ bar: b + 1, bpm: r1(60 / slope) });
      mids.push(mean(here.map((i) => times[i])));
    }
  }
  const out = { bpm_by_bar: curve };
  if (curve.length >= 3) {
    const bpms = curve.map((c) => c.bpm);
    const perMin = linfit(mids, bpms)[1] * 60;
    out.start_bpm = r1(mean(bpms.slice(0, 2)));
    out.end_bpm = r1(mean(bpms.slice(-2)));
    out.drift_bpm_per_minute = r1(perMin);
    out.verdict = perMin > 1.5 ? "rushing (speeding up)" : perMin < -1.5 ? "dragging (slowing down)" : "steady";
  }
  if (reference === "click") out.mean_offset_vs_click_ms = r1(mean(dev));
  return out;
}

function swingWord(s8, s16) {
  const word = (s) => (s < 0.53 ? "straight" : s < 0.6 ? "light swing" : s < 0.7 ? "triplet swing" : "hard swing / dotted");
  return `8ths ${word(s8)}, 16ths ${word(s16)}`;
}

/** Per-bar step strings: X accent, x normal, g ghost, - rest. */
function patterns(byTime, times, barsIdx, slotInBar, spb, nBars) {
  const velBy = {};
  for (const t of times) for (const h of byTime.get(t)) (velBy[h.instrument] ||= []).push(h.velocity);
  const med = Object.fromEntries(Object.entries(velBy).map(([k, v]) => [k, median(v)]));
  const names = Object.keys(velBy).sort();
  const bars = Array.from({ length: nBars }, () => Object.fromEntries(names.map((n) => [n, new Array(spb).fill("-")])));
  times.forEach((t, i) => {
    for (const h of byTime.get(t)) {
      const ratio = h.velocity / med[h.instrument];
      bars[barsIdx[i]][h.instrument][slotInBar[i]] = ratio > 1.25 ? "X" : ratio < 0.55 ? "g" : "x";
    }
  });
  const rendered = bars.map((b) => Object.fromEntries(names.map((n) => [n, b[n].join("")])));
  const shape = rendered.map((r) => names.map((n) => r[n].replace(/[Xg]/g, "x")).join("|"));
  const counts = new Map();
  for (const s of shape) counts.set(s, (counts.get(s) || 0) + 1);
  let main = shape[0], mainCount = 0;
  for (const [s, c] of counts) if (c > mainCount) { main = s; mainCount = c; }
  return {
    legend: "one char per 16th note (see count_labels); X=accent x=normal g=ghost -=rest",
    main_groove: rendered[shape.indexOf(main)],
    main_groove_bars: mainCount,
    bars_that_differ: shape.map((s, i) => (s !== main ? i + 1 : 0)).filter(Boolean),
    all_bars: rendered.map((r, i) => ({ bar: i + 1, ...r })),
  };
}

// --- click track and latency (audio.py) ---------------------------------------------------

/** Click on every beat; compound meters also click each 8th note, softer. */
export function clickTrack(bpm, beats, meter = FOUR_FOUR, sr = SR, tail = 1.0) {
  const beat = 60 / bpm;
  const sub = meter.compound ? 3 : 1;
  const y = new Float32Array(Math.floor((beats * beat + tail) * sr));
  const len = Math.floor(0.03 * sr);
  for (let i = 0; i < beats * sub; i++) {
    let freq = 1000, amp = 0.6;
    if (i % (meter.beats * sub) === 0) freq = 1600; // bar start
    else if (i % sub !== 0) amp = 0.25; // 8th-note subdivision
    const start = Math.round(((i * beat) / sub) * sr);
    for (let n = 0; n < len && start + n < y.length; n++) {
      const t = n / sr;
      y[start + n] += amp * Math.sin(2 * Math.PI * freq * t) * Math.exp(-t * 120);
    }
  }
  return y;
}

/** Latency (s) from a recording of `beats` clicks at `bpm` starting at `t0` seconds. */
export async function measureLatency(y, bpm, beats, t0) {
  const tr = await transcribe(y, { mode: "generic" });
  const onsets = [...new Set(tr.hits.map((h) => h.time))].sort((a, b) => a - b);
  const diffs = [];
  for (let i = 0; i < beats; i++) {
    const e = t0 + (i * 60) / bpm;
    const later = onsets.find((o) => o >= e && o < e + 0.25);
    if (later !== undefined) diffs.push(later - e);
  }
  if (diffs.length < Math.floor(beats / 2))
    throw new Error(`Only heard ${diffs.length}/${beats} clicks; turn the volume up and try again.`);
  return { latency: median(diffs), spread: std(diffs), heard: diffs.length };
}

// --- research notes (research.py) -------------------------------------------------------------

export const SOURCES = {
  repp2005: {
    cite: "Repp, B. H. (2005). Sensorimotor synchronization: A review of the tapping literature. Psychonomic Bulletin & Review, 12(6), 969–992.",
    url: "https://doi.org/10.3758/BF03206433",
    finding: "People playing along to a regular beat usually land tens of milliseconds early (the 'negative mean asynchrony'), one of the most robust findings in timing research.",
  },
  repp2010: {
    cite: "Repp, B. H. (2010). Sensorimotor synchronization and perception of timing: Effects of music training and task experience. Human Movement Science, 29(2), 200–213.",
    url: "https://doi.org/10.1016/j.humov.2009.08.002",
    finding: "Trained musicians showed smaller asynchronies, lower tapping variability, and greater sensitivity to timing deviations than students with little training.",
  },
  friberg1995: {
    cite: "Friberg, A., & Sundberg, J. (1995). Time discrimination in a monotonic, isochronous sequence. Journal of the Acoustical Society of America, 98(5), 2524–2531.",
    url: "https://doi.org/10.1121/1.413218",
    finding: "The smallest noticeable timing change is about 6 ms for notes under 240 ms apart, and about 2.5% of the gap between notes for gaps of 240–1000 ms.",
  },
  rasanen2015: {
    cite: "Räsänen, E., Pulkkinen, O., Virtanen, T., Zollner, M., & Hennig, H. (2015). Fluctuations of hi-hat timing and dynamics in a virtuoso drum track of a popular music recording. PLOS ONE, 10(6), e0127902.",
    url: "https://doi.org/10.1371/journal.pone.0127902",
    finding: "Jeff Porcaro's hi-hat on \"I Keep Forgettin'\" (96 bpm): the time between hits varied with a standard deviation of about 8.7 ms.",
  },
  danielsen2015: {
    cite: "Danielsen, A., Waadeland, C. H., Sundt, H. G., & Witek, M. A. G. (2015). Effects of instructed timing and tempo on snare drum sound in drum kit performance. Journal of the Acoustical Society of America, 138(4), 2301–2316.",
    url: "https://doi.org/10.1121/1.4930950",
    finding: "Expert drummers asked to play laid-back, on the beat, or pushed could do so deliberately; laid-back snare strokes were also played louder.",
  },
  camara2022: {
    cite: "Câmara, G. S., Sioros, G., & Danielsen, A. (2022). Mapping timing and intensity strategies in drum-kit performance of a simple back-beat pattern. Journal of New Music Research, 51(1), 3–26.",
    url: "https://doi.org/10.1080/09298215.2022.2150649",
    finding: "Drummers expressing laid-back or pushed feels used strategies such as playing everything slightly early/late, or one drum early/late against another.",
  },
  friberg2002: {
    cite: "Friberg, A., & Sundström, A. (2002). Swing ratios and ensemble timing in jazz performance: Evidence for a common rhythmic pattern. Music Perception, 19(3), 333–349.",
    url: "https://doi.org/10.1525/mp.2002.19.3.333",
    finding: "Jazz drummers' ride-cymbal swing ratio fell as tempo rose, from about 3.5:1 at slow tempos toward 1:1 at very fast ones, while the short note stayed around 100 ms.",
  },
  fruhauf2013: {
    cite: "Frühauf, J., Kopiez, R., & Platz, F. (2013). Music on the timing grid: The influence of microtiming on the perceived groove quality of a simple drum pattern performance. Musicae Scientiae, 17(2), 246–260.",
    url: "https://doi.org/10.1177/1029864913486793",
    finding: "Listeners rated a perfectly quantized rock drum pattern highest; larger timing displacements got lower groove ratings.",
  },
  kilchenmann2015: {
    cite: "Kilchenmann, L., & Senn, O. (2015). Microtiming in swing and funk affects the body movement behavior of music expert listeners. Frontiers in Psychology, 6, 1232.",
    url: "https://doi.org/10.3389/fpsyg.2015.01232",
    finding: "Expert listeners moved more to music with human microtiming than to quantized versions, contradicting the idea that exact timing is always best.",
  },
  hennig2011: {
    cite: "Hennig, H., Fleischmann, R., Fredebohm, A., Hagmayer, Y., Nagler, J., Witt, A., Theis, F. J., & Geisel, T. (2011). The nature and perception of fluctuations in human musical rhythms. PLOS ONE, 6(10), e26457.",
    url: "https://doi.org/10.1371/journal.pone.0026457",
    finding: "Human rhythmic performance always drifts in small, long-range-correlated ways, and listeners prefer that over the random 'humanize' fluctuations in music software.",
  },
};
const SPREAD_RULE = "The 'typical' (10–20 ms) and 'loose' (20–30 ms) spread labels are this tool's rules of thumb, not research findings.";

/** Smallest noticeable timing change for notes `gapMs` apart (Friberg & Sundberg 1995). */
const audibleMs = (gapMs) => (gapMs < 240 ? 6 : 0.025 * gapMs);

/** [title, text, source ids] notes tailored to one take's analysis. */
export function researchNotes(a) {
  const out = [];
  const slots = a.slots_per_beat || 4;
  const beatMs = 60000 / a.grid_bpm;
  const six = beatMs / slots;
  const eighth = beatMs / (slots === 6 ? 3 : slots / 2);
  out.push(["How small a difference can anyone hear?",
    `At this tempo your 16th notes are ${six.toFixed(0)} ms apart and 8th notes ${eighth.toFixed(0)} ms apart. ` +
    `Research puts the smallest noticeable timing change at about ${audibleMs(six).toFixed(0)} ms for 16ths and ` +
    `${audibleMs(eighth).toFixed(0)} ms for 8ths at this tempo. Differences smaller than that are below what listeners can reliably hear.`,
    ["friberg1995"]]);
  out.push(["What does tight look like?",
    `Your spread is ${a.tightness.std_ms.toFixed(0)} ms. For a professional benchmark, Jeff Porcaro's famous hi-hat part ` +
    "varied by about 9 ms between hits. (That's a slightly different measure from this tool's spread, so treat it as a " +
    "ballpark, not an exact target.) Research also finds trained musicians are less variable than beginners, so this number " +
    `should come down with practice. ${SPREAD_RULE}`, ["rasanen2015", "repp2010"]]);
  const off = a.tempo.mean_offset_vs_click_ms;
  if (off !== undefined && off !== null)
    out.push(["Why am I ahead of the click?",
      `You were ${Math.abs(off).toFixed(0)} ms ${off < 0 ? "ahead of" : "behind"} the click on average. Landing early is one of the most ` +
      "consistent findings in timing research: most people play tens of milliseconds ahead of a beat they're following, and " +
      "trained musicians do it less. It's normal, and it shrinks with practice.", ["repp2005", "repp2010"]]);
  out.push(["Behind the beat can be a choice",
    "Laid-back, on-the-beat and pushed are styles expert drummers play on purpose, for example a snare slightly behind the " +
    "hi-hat. So a drum that sits late in the 'By drum' chart isn't automatically a mistake. What matters is whether it's " +
    "deliberate and consistent.", ["danielsen2015", "camara2022"]]);
  if ((a.swing.eighth_swing_pct || 0) >= 53)
    out.push(["Swing changes with tempo",
      `Your 8th notes swing at ${a.swing.eighth_swing_pct.toFixed(0)}%. Jazz drummers swing harder at slow tempos and ` +
      "flatten out as the tempo rises, so the 'right' amount depends on the tempo.", ["friberg2002"]]);
  out.push(["Tighter isn't automatically better",
    "Research is split here. Listeners rated a perfectly quantized drum pattern highest, but in another study expert " +
    "listeners' bodies moved more to music with human timing. Every human performance drifts in small, connected ways, and " +
    "listeners prefer that over machine-made randomness. Use these numbers to get control of your time, not to sound like a machine.",
    ["fruhauf2013", "kilchenmann2015", "hennig2011"]]);
  return out;
}

// --- coaching (coach.py) -------------------------------------------------------------------------

export const MODEL = "claude-opus-5-5";
const INSTRUMENTS = ["kick", "snare", "rim", "hihat_closed", "hihat_open", "hihat_pedal", "ride", "crash", "tom_high", "tom_mid", "tom_floor"];

const obj = (properties, descriptions = {}) => ({
  type: "object", additionalProperties: false, required: Object.keys(properties),
  properties: Object.fromEntries(Object.entries(properties).map(([k, v]) => [k, descriptions[k] ? { ...v, description: descriptions[k] } : v])),
});
const str = { type: "string" }, int = { type: "integer" };
const list = (items) => ({ type: "array", items });
const PATTERN = obj({
  name: str, bars: int, difficulty: { type: "string", enum: ["easier", "same level", "stretch"] },
  why_it_fits: str, how_to_practice: str, make_it_yours: list(str),
  tracks: list(obj({ instrument: { type: "string", enum: INSTRUMENTS }, steps: str },
    { steps: "One char per 16th note across all bars of the pattern: X accent, x normal, g ghost, - rest." })),
}, {
  why_it_fits: "How this builds on what the player actually did.",
  make_it_yours: "2-3 specific ways the player could change this idea so it becomes their own.",
});
/** JSON schema for Claude's structured output (the Coaching model in coach.py). */
export const COACHING_SCHEMA = obj({
  summary: str,
  strengths: list(str),
  timing_insights: list(obj({ title: str, evidence: str, what_it_means: str, fix: str },
    { evidence: "The numbers from the analysis this is based on." })),
  swing_and_feel: str,
  dynamics: str,
  exercises: list(obj({ name: str, instructions: str, start_bpm: int, goal: str })),
  variations: list(PATTERN),
  fills: list(PATTERN),
  your_turn: list(str),
}, {
  variations: "Variation ideas on the main groove, each 1-2 bars.",
  fills: "Fill ideas, each 1-2 bars, played straight after the main groove.",
  your_turn: "Open-ended improvisation challenges with no answer given.",
});

export const COACH_SYSTEM = `You are a drum teacher and working band drummer. Your student is learning drums so they can join a band. You'll get a machine analysis of a recording of them playing and should give them feedback and new material.

How to read the analysis:
- Offsets are in milliseconds; positive = late (behind the beat), negative = early (ahead). "vs_groove" numbers have slow tempo drift removed, so they show where a hit sits inside the groove; "vs_grid" numbers include drift.
- reference "self" means no click was used: the grid is the steady pulse that best fits their playing, so drift and consistency are meaningful but absolute accuracy is not. reference "click" means offsets are against a real metronome.
- Swing is given as MPC-style percentages: 50% straight, ~66.7% triplet swing.
- The transcription is a heuristic onset detector on one microphone. Kit-piece labels can be wrong (e.g. a snare hit also tagged as hi-hat), and occasional hits are missed or doubled. Build feedback on patterns across many hits, not on one odd event, and say so when a number may be an artifact.
- For scale, from published research: the smallest noticeable timing change is about 6 ms for notes under 240 ms apart and about 2.5% of the gap between notes for slower notes (Friberg & Sundberg 1995). A professional benchmark: Jeff Porcaro's hi-hat varied by about 9 ms between hits (Räsänen et al. 2015). Playing tens of ms ahead of a click is normal and shrinks with training (Repp 2005, 2010). Laid-back and pushed feels are deliberate styles, not only errors (Danielsen et al. 2015). Research is split on whether tighter timing grooves more (Frühauf et al. 2013 vs Kilchenmann & Senn 2015), so don't treat perfect quantization as the goal.
- The 10-20 ms "typical intermediate" spread band is a rule of thumb, not research; present it as such if you use it.
- Don't cite studies or sources in your answer. The report lists verified research separately, and any citation you add can't be checked.

What to give back:
- Feedback that is specific, cites the numbers, and is honest about both strengths and problems. Explain what each issue will sound like to bandmates.
- Exercises that target the biggest timing issues.
- Variation and fill ideas in this player's style: start from their actual main groove, the instruments and density they use, and their tendencies, and pitch most at or slightly above their current level. Variations should be usable in a song verse or chorus; fills should lead naturally back into their groove.
- These are starting points for the player to learn from and then change, not parts to copy note for note. Improvising their own ideas is the goal. For each idea, give a few concrete ways to make it their own (move it, thin it out, change the drums or the accents, start it somewhere else).
- "Your turn": a few improvisation challenges that set a constraint and leave the playing to them, e.g. "a one-bar fill using only the floor tom and snare that starts on the 'e' of 4". Don't write out answers for these.

Pattern format: each track's steps string has one character per 16th note, starting on beat 1, with exactly the number of steps per bar given in the analysis (16 in 4/4, 12 in 3/4 and 6/8), times the number of bars. The analysis's count_labels show how each step is counted. Use X accent, x normal, g ghost, - rest. Only include tracks that play. Write patterns that fit the time signature and its feel (e.g. 6/8 is two dotted-quarter beats of three 8ths each).`;

/** The user message for the coaching request. */
export function coachPrompt(analysis, goal) {
  let user = goal ? `About me / what I'm working toward: ${goal}\n\n` : "";
  const spb = (analysis.count_labels || []).length || 16;
  user += `Time signature: ${analysis.time_signature || "4/4"}, ${spb} steps per bar, tempo counted in ${analysis.beat_note || "quarter note"}s.\n\n`;
  return user + "Here is the analysis of my recording:\n\n" + JSON.stringify(trim(analysis), null, 1);
}

/** Drop bulky fields Claude doesn't need; keep per-bar patterns only for bars that differ. */
function trim(analysis) {
  const { patterns: p, kit_profile, ...a } = analysis;
  a.patterns = {
    legend: p.legend, main_groove: p.main_groove, main_groove_bars: p.main_groove_bars,
    bars_that_differ: p.all_bars.filter((b) => p.bars_that_differ.includes(b.bar)),
  };
  return a;
}

/** Split a pattern into per-bar {instrument: steps}, padding/trimming to length. */
export function patternBars(p, spb = 16) {
  const n = Math.max(1, p.bars);
  const out = Array.from({ length: n }, () => ({}));
  for (const t of p.tracks) {
    const s = (t.steps.replace(/[^Xxg-]/g, "") + "-".repeat(spb * n)).slice(0, spb * n);
    for (let b = 0; b < n; b++) out[b][t.instrument] = s.slice(b * spb, (b + 1) * spb);
  }
  return out;
}

/** Transcription labels -> pattern instrument names. */
export function kitNames(bar) {
  const out = {};
  for (const [k, v] of Object.entries(bar)) if (k !== "hit") out[k === "hihat" ? "hihat_closed" : k] = v;
  return Object.keys(out).length ? out : { rim: bar.hit || "" };
}

// --- MIDI (midi.py, midiin.py) ---------------------------------------------------------------------

const TPB = 480;
export const GM = { kick: 36, snare: 38, rim: 37, hihat: 42, hihat_closed: 42, hihat_open: 46, hihat_pedal: 44, ride: 51,
  crash: 49, tom_high: 50, tom_mid: 47, tom_floor: 43, hit: 37 };
const STEP_VELOCITY = { X: 118, x: 92, g: 40 };
// Pad note numbers -> drum names: Alesis Nitro defaults, which match General MIDI.
export const NOTE_MAP = {
  35: "kick", 36: "kick", 38: "snare", 40: "snare", 37: "rim", 48: "tom_high", 50: "tom_high", 45: "tom_mid", 47: "tom_mid",
  43: "tom_floor", 58: "tom_floor", 41: "tom_floor", 39: "tom_floor", 42: "hihat", 22: "hihat", 46: "hihat_open",
  23: "hihat_open", 26: "hihat_open", 44: "hihat_pedal", 21: "hihat_pedal", 49: "crash", 57: "crash", 55: "crash",
  52: "crash", 51: "ride", 59: "ride", 53: "ride",
};

function vlq(n) {
  const bytes = [n & 0x7f];
  while ((n >>= 7)) bytes.unshift((n & 0x7f) | 0x80);
  return bytes;
}

/** A type-0 MIDI file (bytes). events: [tick, note, velocity]. */
function writeMidi(events, quarterBpm, meter) {
  const msgs = [];
  for (const [tick, note, vel] of events) {
    msgs.push([tick, 1, [0x99, note, vel]]);
    msgs.push([tick + TPB / 8, 0, [0x89, note, 0]]);
  }
  msgs.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const tempo = Math.round(60e6 / quarterBpm);
  const track = [0, 0xff, 0x51, 3, (tempo >> 16) & 255, (tempo >> 8) & 255, tempo & 255,
    0, 0xff, 0x58, 4, meter.num, Math.log2(meter.den), 24, 8];
  let last = 0;
  for (const [tick, , bytes] of msgs) { track.push(...vlq(Math.max(0, tick - last)), ...bytes); last = Math.max(last, tick); }
  track.push(0, 0xff, 0x2f, 0);
  const head = [0x4d, 0x54, 0x68, 0x64, 0, 0, 0, 6, 0, 0, 0, 1, TPB >> 8, TPB & 255];
  const len = track.length;
  return new Uint8Array([...head, 0x4d, 0x54, 0x72, 0x6b, (len >>> 24) & 255, (len >> 16) & 255, (len >> 8) & 255, len & 255, ...track]);
}

/** Transcribed hits at their real (unquantized) times. bpm counts the meter's beat. */
export function hitsToMidi(hits, bpm, meter = FOUR_FOUR) {
  const q = bpm * meter.beatQuarters;
  return writeMidi(hits.map((h) => [Math.round(((h.time * q) / 60) * TPB), GM[h.instrument] ?? 37, h.velocity]), q, meter);
}

/** 16th step index -> tick, applying the player's measured swing (x/4 only). */
export function stepsTick(step, s8 = 0.5, s16 = 0.5, meter = FOUR_FOUR) {
  if (!meter.swingable) return (step * TPB) / 4;
  const beat = Math.floor(step / 4), k = step % 4;
  return Math.round((beat + [0, s16 * s8, s8, s8 + s16 * (1 - s8)][k]) * TPB);
}

/** bars: list of {instrument: step string}, laid end to end. bpm counts the meter's beat. */
export function patternsToMidi(bars, bpm, s8 = 0.5, s16 = 0.5, meter = FOUR_FOUR) {
  const events = [];
  let offset = 0;
  for (const bar of bars) {
    for (const [inst, steps] of Object.entries(bar))
      [...steps].forEach((ch, i) => { if (STEP_VELOCITY[ch]) events.push([offset + stepsTick(i, s8, s16, meter), GM[inst] ?? 37, STEP_VELOCITY[ch]]); });
    offset += stepsTick(meter.stepsPerBar, s8, s16, meter);
  }
  return writeMidi(events, bpm * meter.beatQuarters, meter);
}

/** Hits from a MIDI file's bytes (seconds from the start), plus counts of unknown notes. */
export function hitsFromMidi(bytes) {
  const d = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const str4 = (o) => String.fromCharCode(bytes[o], bytes[o + 1], bytes[o + 2], bytes[o + 3]);
  if (str4(0) !== "MThd") throw new Error("That isn't a MIDI file.");
  const ntracks = d.getUint16(10), division = d.getUint16(12);
  if (division & 0x8000) throw new Error("SMPTE-timed MIDI files aren't supported.");
  const events = []; // [tick, order, kind, data]
  let o = 8 + d.getUint32(4), order = 0;
  for (let tr = 0; tr < ntracks && o < bytes.length; tr++) {
    if (str4(o) !== "MTrk") break;
    const end = o + 8 + d.getUint32(o + 4);
    o += 8;
    let tick = 0, status = 0;
    const readVlq = () => { let v = 0, b; do { b = bytes[o++]; v = (v << 7) | (b & 0x7f); } while (b & 0x80); return v; };
    while (o < end) {
      tick += readVlq();
      let b = bytes[o];
      if (b & 0x80) { status = b; o++; }
      if (status === 0xff) {
        const type = bytes[o++], len = readVlq();
        if (type === 0x51) events.push([tick, order++, "tempo", (bytes[o] << 16) | (bytes[o + 1] << 8) | bytes[o + 2]]);
        o += len;
      } else if (status === 0xf0 || status === 0xf7) {
        o += readVlq();
      } else {
        const hi = status & 0xf0;
        const n = hi === 0xc0 || hi === 0xd0 ? 1 : 2;
        const a = bytes[o], v = bytes[o + 1];
        o += n;
        if (hi === 0x90 && v > 0) events.push([tick, order++, "on", [a, v]]);
      }
    }
    o = end;
  }
  events.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  let tempo = 500000, lastTick = 0, secs = 0;
  const hits = [], unknown = {};
  for (const [tick, , kind, data] of events) {
    secs += ((tick - lastTick) * tempo) / division / 1e6;
    lastTick = tick;
    if (kind === "tempo") tempo = data;
    else {
      const name = NOTE_MAP[data[0]];
      if (name) hits.push({ time: round4(secs), instrument: name, velocity: data[1] });
      else unknown[data[0]] = (unknown[data[0]] || 0) + 1;
    }
  }
  return { hits, unknown };
}

/** Hits straight from an e-kit (MIDI), shaped like an audio transcription. */
export function midiTranscription(hits, unknown = {}, start = 0) {
  hits = hits.filter((h) => h.time >= start);
  const warnings = [];
  const unk = Object.entries(unknown);
  if (unk.length)
    warnings.push(`Some hits came from pads the tool doesn't recognize (${unk.map(([n, c]) => `note ${n} (${c}x)`).join(", ")}), ` +
      "so they were left out. Your module may use a custom pad map.");
  const duration = Math.max(0, ...hits.map((h) => h.time)) + 1;
  // Tempo guess from the hits themselves, for takes with no click info.
  const env = new Float64Array(Math.floor((duration * SR) / HOP) + 1);
  for (const h of hits) env[Math.floor((h.time * SR) / HOP)] += h.velocity / 127;
  const smooth = new Float64Array(env.length);
  const han = Array.from({ length: 9 }, (_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / 8));
  for (let i = 0; i < env.length; i++) for (let j = -4; j <= 4; j++) if (env[i + j]) smooth[i] += env[i + j] * han[j + 4];
  return { hits, tempoEstimate: hits.length ? estimateTempo(smooth) : 120, duration, mode: "drums", warnings };
}

// --- drum sounds (synth.py, render.py) ----------------------------------------------------------------

/** Seeded random numbers (mulberry32) with a normal() for noise. */
export function rng(seed = 0) {
  let s = seed >>> 0;
  const u = () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  return { uniform: u, normal: () => Math.sqrt(-2 * Math.log(u() || 1e-12)) * Math.cos(2 * Math.PI * u()) };
}

function kick() {
  const n = Math.floor(0.25 * SR), y = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) { const t = i / SR; ph += (2 * Math.PI * (50 + 90 * Math.exp(-t * 40))) / SR; y[i] = 0.9 * Math.sin(ph) * Math.exp(-t * 14); }
  return y;
}
function snare(r) {
  const n = Math.floor(0.2 * SR), y = new Float32Array(n);
  const noise = Array.from({ length: n }, r.normal);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const bright = noise[i] - 0.6 * (noise[i - 1] ?? 0); // np.convolve(noise, [1, -0.6], "same")
    y[i] = 0.5 * Math.sin(2 * Math.PI * 190 * t) * Math.exp(-t * 30) + 0.35 * bright * Math.exp(-t * 22);
  }
  return y;
}
function hihat(r) {
  const n = Math.floor(0.06 * SR), y = new Float32Array(n);
  let prev = r.normal();
  for (let i = 0; i < n; i++) { const cur = r.normal(); y[i] = 0.25 * (cur - prev) * Math.exp((-i / SR) * 70); prev = cur; }
  return y;
}
const tom = (freq) => (r) => {
  const n = Math.floor(0.35 * SR), y = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    ph += (2 * Math.PI * freq * (1 + 0.15 * Math.exp(-t * 30))) / SR;
    y[i] = 0.7 * (Math.sin(ph) * Math.exp(-t * 10) + r.normal() * Math.exp(-t * 200) * 0.15);
  }
  return y;
};
function crash(r) {
  const n = Math.floor(1.2 * SR), noise = Float32Array.from({ length: n }, r.normal), y = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let acc = 0; // 8-sample mean, aligned like np.convolve(..., "same")
    for (let j = i - 4; j <= i + 3; j++) acc += noise[j] ?? 0;
    y[i] = 0.35 * (noise[i] - acc / 8) * Math.exp((-i / SR) * 3);
  }
  return y;
}
export const VOICES = { kick, snare, hihat, tom_high: tom(180), tom_mid: tom(130), tom_floor: tom(90), crash };
// Pattern instrument -> the built-in drum sound used to play it, and a level.
const SOUND = { kick: ["kick", 1], snare: ["snare", 1], rim: ["snare", 0.4], hihat: ["hihat", 0.8], hihat_closed: ["hihat", 0.8],
  hihat_open: ["hihat", 1], hihat_pedal: ["hihat", 0.5], tom_high: ["tom_high", 0.9], tom_mid: ["tom_mid", 0.9],
  tom_floor: ["tom_floor", 0.9], crash: ["crash", 0.8], ride: ["hihat", 0.7] };
const STEP_LEVEL = { X: 1, x: 0.75, g: 0.3 };

function addAt(y, s, start, gain = 1) {
  for (let i = 0; i < s.length && start + i < y.length; i++) if (start + i >= 0) y[start + i] += s[i] * gain;
}
function normalize(y, to = 0.9) {
  let peak = 0;
  for (const v of y) peak = Math.max(peak, Math.abs(v));
  if (peak > 0) for (let i = 0; i < y.length; i++) y[i] = (to * y[i]) / peak;
  return y;
}

/** Audio for bars of {instrument: step string}, laid end to end. bpm counts the meter's beat. */
export function renderBars(bars, bpm, meter = FOUR_FOUR, s8 = 0.5, s16 = 0.5) {
  const r = rng(0);
  const secPerTick = 60 / (bpm * meter.beatQuarters) / TPB;
  const barTicks = stepsTick(meter.stepsPerBar, s8, s16, meter);
  const y = new Float32Array(Math.floor((bars.length * barTicks * secPerTick + 1.5) * SR));
  bars.forEach((bar, b) => {
    for (const [inst, steps] of Object.entries(bar)) {
      const [voice, level] = SOUND[inst] || ["snare", 0.6];
      [...steps].forEach((ch, i) => {
        if (!STEP_LEVEL[ch]) return;
        const t = (b * barTicks + stepsTick(i, s8, s16, meter)) * secPerTick;
        addAt(y, VOICES[voice](r), Math.floor(t * SR), level * STEP_LEVEL[ch]);
      });
    }
  });
  return normalize(y);
}

const ROCK = { kick: "x-----x-x-------", snare: "----x-------x---", hihat: "x-x-x-x-x-x-x-x-" };
const FILL = { snare: "x-x-x-x-xxxx----", tom_high: "------------x---", tom_floor: "--------------x-" };
const GROOVES = {
  "4/4": [ROCK, FILL],
  "3/4": [{ kick: "x-----------", snare: "----x---x---", hihat: "x-x-x-x-x-x-" },
    { snare: "x-x-x-x-----", tom_high: "--------x---", tom_floor: "----------x-" }],
  "6/8": [{ kick: "x---------x-", snare: "------x-----", hihat: "x-x-x-x-x-x-" },
    { snare: "x-x-x-------", tom_high: "------x-x---", tom_floor: "----------x-" }],
};

/**
 * A drum performance with known timing flaws, for trying the tool without a
 * kit: tempo ramps from bpm to bpm+rushBpm, the snare sits snareLateMs behind,
 * every hit gets random jitter, and swing moves offbeat 8ths (0.5 = straight).
 */
export function synth({ bpm = 96, bars = 8, rushBpm = 4, snareLateMs = 15, jitterMs = 6, swing = 0.5, meter = FOUR_FOUR, fillLastBar = true, seed = 0 } = {}) {
  const [groove, fill] = GROOVES[meter.name] || GROOVES["4/4"];
  const r = rng(seed);
  const total = bars * meter.beats;
  const beatTimes = [0.5];
  for (let i = 0; i < total; i++) beatTimes.push(beatTimes[i] + 60 / (bpm + (rushBpm * i) / total));
  const y = new Float32Array(Math.floor((beatTimes[total] + 1) * SR));
  for (let b = 0; b < bars; b++) {
    const pattern = fillLastBar && b === bars - 1 ? fill : groove;
    for (const [inst, steps] of Object.entries(pattern))
      [...steps].forEach((ch, i) => {
        if (ch !== "x") return;
        const beat = Math.floor(i / meter.slots), k = i % meter.slots;
        const frac = meter.swingable ? [0, (0.25 * swing) / 0.5, swing, swing + 0.5 * (1 - swing)][k] : k / meter.slots;
        const g = b * meter.beats + beat;
        let t = beatTimes[g] + frac * (beatTimes[g + 1] - beatTimes[g]) + (r.normal() * jitterMs) / 1000;
        if (inst === "snare") t += snareLateMs / 1000;
        const gain = inst !== "hihat" || i % meter.slots === 0 ? 1 : 0.6;
        addAt(y, VOICES[inst](r), Math.floor(t * SR), gain);
      });
  }
  for (let i = 0; i < y.length; i++) y[i] += r.normal() * 0.002; // room noise
  return normalize(y, 0.8);
}

// --- WAV -----------------------------------------------------------------------------------------------

/** 16-bit mono WAV bytes from float samples. */
export function encodeWav(y, sr = SR) {
  const buf = new ArrayBuffer(44 + y.length * 2), d = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => d.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); d.setUint32(4, 36 + y.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  d.setUint32(16, 16, true); d.setUint16(20, 1, true); d.setUint16(22, 1, true); d.setUint32(24, sr, true);
  d.setUint32(28, sr * 2, true); d.setUint16(32, 2, true); d.setUint16(34, 16, true); w(36, "data"); d.setUint32(40, y.length * 2, true);
  for (let i = 0; i < y.length; i++) d.setInt16(44 + i * 2, Math.round(clamp(y[i], -1, 1) * 32767), true);
  return new Uint8Array(buf);
}

/** Mono float samples from a PCM WAV (8/16/24/32-bit int or 32-bit float). */
export function decodeWav(bytes) {
  const d = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let o = 12, fmt = null;
  while (o + 8 <= bytes.length) {
    const id = String.fromCharCode(...bytes.slice(o, o + 4)), len = d.getUint32(o + 4, true);
    if (id === "fmt ") fmt = { format: d.getUint16(o + 8, true), ch: d.getUint16(o + 10, true), sr: d.getUint32(o + 12, true), bits: d.getUint16(o + 22, true) };
    if (id === "data" && fmt) {
      const bps = fmt.bits / 8, n = Math.floor(len / bps / fmt.ch), y = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        let s = 0;
        for (let c = 0; c < fmt.ch; c++) {
          const p = o + 8 + (i * fmt.ch + c) * bps;
          if (fmt.format === 3) s += d.getFloat32(p, true);
          else if (fmt.bits === 16) s += d.getInt16(p, true) / 32768;
          else if (fmt.bits === 24) s += (((d.getUint8(p + 2) << 24) | (d.getUint8(p + 1) << 16) | (d.getUint8(p) << 8)) >> 8) / 8388608;
          else if (fmt.bits === 32) s += d.getInt32(p, true) / 2147483648;
          else s += (d.getUint8(p) - 128) / 128;
        }
        y[i] = s / fmt.ch;
      }
      return { y, sr: fmt.sr };
    }
    o += 8 + len + (len % 2);
  }
  throw new Error("Couldn't read that WAV file.");
}
