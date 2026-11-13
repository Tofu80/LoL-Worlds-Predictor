import assert from "node:assert/strict";
import { test } from "node:test";
import {
  clip,
  dateLabel,
  dateTimeLabel,
  linear,
  niceTicks,
  paddedDomain,
  pathOf,
  pct,
  signed,
  utcMs,
  yearTicks,
} from "./util.mjs";

test("linear maps the domain ends to the range ends and inverts", () => {
  const f = linear(0, 10, 100, 300);
  assert.equal(f(0), 100);
  assert.equal(f(10), 300);
  assert.equal(f(5), 200);
  assert.equal(f.invert(200), 5);
  const flipped = linear(0, 1, 340, 20); // SVG y grows downwards
  assert.equal(flipped(0), 340);
  assert.equal(flipped(1), 20);
});

test("linear with a flat domain maps to the middle of the range", () => {
  assert.equal(linear(7, 7, 0, 100)(7), 50);
  assert.equal(linear(0, 1, 5, 5).invert(5), 0.5);
});

test("niceTicks gives 1/2/5 steps inside the range", () => {
  assert.deepEqual(niceTicks(0, 100, 5), [0, 20, 40, 60, 80, 100]);
  assert.deepEqual(niceTicks(1490, 2060, 5), [1500, 1600, 1700, 1800, 1900, 2000]);
  assert.deepEqual(niceTicks(0.5, 1, 5), [0.5, 0.6, 0.7, 0.8, 0.9, 1]);
  assert.deepEqual(niceTicks(3, 3), [3]);
});

test("niceTicks stays inside [min, max] and is increasing", () => {
  for (const [a, b] of [[0.62, 0.71], [-3, 12], [1480.2, 2133.7]]) {
    const t = niceTicks(a, b, 6);
    assert.ok(t.length >= 2);
    assert.ok(t[0] >= a && t.at(-1) <= b);
    assert.ok(t.every((v, i) => i === 0 || v > t[i - 1]));
  }
});

test("paddedDomain pads by a fraction of the span and handles flat or empty data", () => {
  assert.deepEqual(paddedDomain([10, 20], 0.1), [9, 21]);
  assert.deepEqual(paddedDomain([5, 5, 5]), [4, 6]);
  assert.deepEqual(paddedDomain([]), [0, 1]);
});

test("pathOf starts a new subpath per run and skips empty runs", () => {
  assert.equal(pathOf([[[0, 0], [1, 2.25]], [], [[5, 5]]]), "M0,0L1,2.3M5,5");
  assert.equal(pathOf([]), "");
});

test("dates are read as UTC", () => {
  assert.equal(utcMs("2026-11-03T22:00"), Date.UTC(2026, 10, 3, 22, 0));
  assert.equal(utcMs("2026-11-03"), Date.UTC(2026, 10, 3));
  assert.equal(dateLabel("2026-11-03T22:00"), "3 Nov 2026");
  assert.equal(dateLabel("2024-01-01"), "1 Jan 2024");
  assert.equal(dateTimeLabel("2026-11-03T22:00"), "3 Nov 2026, 22:00 UTC");
  assert.equal(dateTimeLabel("2026-11-03"), "3 Nov 2026");
});

test("yearTicks lists the January firsts inside the span", () => {
  const t = yearTicks(utcMs("2023-03-01"), utcMs("2026-10-31"));
  assert.deepEqual(t.map((x) => x.label), ["2024", "2025", "2026"]);
  assert.equal(t[0].t, Date.UTC(2024, 0, 1));
});

test("number formatting", () => {
  assert.equal(pct(0.5499), "55.0%");
  assert.equal(pct(0.0022, 2), "0.22%");
  assert.equal(signed(-0.0432), "−0.0432");
  assert.equal(signed(0.5, 1), "+0.5");
  assert.equal(clip("Fukuoka SoftBank HAWKS gaming", 12), "Fukuoka Sof…");
  assert.equal(clip("T1", 12), "T1");
});
