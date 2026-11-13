// Pure helpers (no DOM): scales, ticks, paths, number and date formatting.
// Tested by util.test.mjs with `node --test site/js/util.test.mjs`.

/** Linear map from domain [d0, d1] to range [r0, r1]; a flat domain maps to the range middle. */
export function linear(d0, d1, r0, r1) {
  const f = (x) => (d1 === d0 ? (r0 + r1) / 2 : r0 + ((x - d0) / (d1 - d0)) * (r1 - r0));
  f.invert = (y) => (r1 === r0 ? (d0 + d1) / 2 : d0 + ((y - r0) / (r1 - r0)) * (d1 - d0));
  return f;
}

/** Multiples of a 1/2/5 x 10^k step inside [min, max], about `count` of them. */
export function niceTicks(min, max, count = 5) {
  if (!(max > min)) return [min];
  const rough = (max - min) / Math.max(1, count);
  const pow = 10 ** Math.floor(Math.log10(rough));
  const f = rough / pow;
  const step = (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * pow;
  const out = [];
  const last = Math.floor(max / step + 1e-9);
  for (let k = Math.ceil(min / step - 1e-9); k <= last; k++) {
    out.push(Number((k * step).toPrecision(12))); // k*step, minus float noise like 0.6000000000000001
  }
  return out;
}

/** [lo, hi] around the values with `pad` (fraction of the span) on both sides; flat data gets +-1. */
export function paddedDomain(values, pad = 0.05) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (lo === Infinity) return [0, 1];
  if (lo === hi) return [lo - 1, hi + 1];
  const p = (hi - lo) * pad;
  return [lo - p, hi + p];
}

/** SVG path for several runs of [x, y] points; each run starts with its own "M". */
export function pathOf(runs, digits = 1) {
  const n = (v) => Number(v.toFixed(digits));
  return runs
    .filter((r) => r.length)
    .map((r) => r.map(([x, y], i) => `${i ? "L" : "M"}${n(x)},${n(y)}`).join(""))
    .join("");
}

/** "2026-11-03T22:00" (UTC, no zone in the data) -> milliseconds. */
export function utcMs(iso) {
  return Date.parse(iso.length <= 10 ? `${iso}T00:00:00Z` : `${iso}:00Z`.replace(/:00:00Z$/, ":00Z"));
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "3 Nov 2026" in UTC. */
export function dateLabel(iso) {
  const d = new Date(utcMs(iso));
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** "3 Nov 2026, 22:00 UTC" when the string has a time, else the date alone. */
export function dateTimeLabel(iso) {
  if (iso.length <= 10) return dateLabel(iso);
  return `${dateLabel(iso)}, ${iso.slice(11, 16)} UTC`;
}

/** Probability 0.5499 -> "55.0%". */
export function pct(p, digits = 1) {
  return `${(p * 100).toFixed(digits)}%`;
}

/** Signed number with a real minus sign: -0.0432 -> "−0.0432", 0.5 -> "+0.5000". */
export function signed(x, digits = 4) {
  const s = Math.abs(x).toFixed(digits);
  return x < 0 ? `−${s}` : `+${s}`;
}

/** Shorten a name for a narrow SVG label. */
export function clip(text, max) {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

/** Jan 1 of every year touched by [t0, t1] (ms), as { t, label }. */
export function yearTicks(t0, t1) {
  const out = [];
  for (let y = new Date(t0).getUTCFullYear(); ; y++) {
    const t = Date.UTC(y, 0, 1);
    if (t > t1) break;
    if (t >= t0) out.push({ t, label: String(y) });
  }
  return out;
}
