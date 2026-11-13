// Hand-drawn SVG charts. Every chart has a <title> and <desc>, and the page next to it
// carries the same numbers as a table.
import { s } from "./dom.mjs";
import {
  clip,
  dateLabel,
  linear,
  niceTicks,
  paddedDomain,
  pathOf,
  pct,
  utcMs,
  yearTicks,
} from "./util.mjs";

/** Zero-size SVG holding the hatch pattern the what-if marks use (reference: url(#hatch)). */
export function hatchDefs() {
  return s(
    "svg",
    { width: 0, height: 0, "aria-hidden": "true", style: "position:absolute" },
    s(
      "defs",
      {},
      s(
        "pattern",
        { id: "hatch", width: 5, height: 5, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
        s("rect", { width: 5, height: 5, fill: "none" }),
        s("line", { x1: 0, y1: 0, x2: 0, y2: 5, stroke: "currentColor", "stroke-width": 2 }),
      ),
    ),
  );
}

/** A horizontal bar for a probability p on a 0..max scale. */
export function oddsBar(p, max, prov, label) {
  return s(
    "svg",
    { class: "bar", viewBox: "0 0 100 14", preserveAspectRatio: "none", role: "img", "aria-label": label },
    s("title", {}, label),
    s("rect", { class: "track", x: 0.5, y: 0.5, width: 99, height: 13 }),
    s("rect", { class: `fill prov-${prov}`, x: 0.5, y: 0.5, width: Math.max(0.5, (p / max) * 99), height: 13 }),
  );
}

/**
 * Strength over time. points: the team file's history points
 * [date, opponent, strength_before, strength_after, offset_after, gameid, segment, provenance].
 * Replay runs are dashed grey, walk-forward runs solid; a vertical line marks each Worlds start.
 */
export function eloChart({ points, starts, matchOf, frozen, name }) {
  const W = 960;
  const H = 360;
  const m = { l: 56, r: 24, t: 54, b: 30 };
  const ts = points.map((p) => utcMs(p[0]));
  const frozenT = frozen ? utcMs(frozen.date) : -Infinity;
  const x = linear(ts[0], Math.max(ts.at(-1), frozenT), m.l, W - m.r);
  const ys = points.map((p) => p[3]);
  if (frozen) ys.push(frozen.strength);
  const [lo, hi] = paddedDomain(ys, 0.08);
  const y = linear(lo, hi, H - m.b, m.t);

  const runs = [];
  let cur = null;
  points.forEach((p, i) => {
    const key = `${p[6]}|${p[7]}`;
    const pt = [x(ts[i]), y(p[3])];
    if (!cur || cur.key !== key) {
      const prev = cur;
      cur = { key, prov: p[7], seg: p[6], pts: [] };
      if (prev && prev.seg === p[6]) cur.pts.push(prev.pts.at(-1)); // join replay to walk-forward
      runs.push(cur);
    }
    cur.pts.push(pt);
  });

  const first = points[0];
  const last = points.at(-1);
  const svg = s(
    "svg",
    { viewBox: `0 0 ${W} ${H}`, role: "img" },
    s("title", {}, `Strength of ${name} over time`),
    s(
      "desc",
      {},
      `Strength (team rating plus league offset) of ${name}, from ${first[3].toFixed(0)} on ${dateLabel(first[0])} ` +
        `to ${last[3].toFixed(0)} on ${dateLabel(last[0])}. Dashed grey sections are replays before each Worlds ` +
        `start; solid teal sections are walk-forward. Vertical lines mark the start of each Worlds.` +
        (frozen ? ` The blue diamond is the frozen strength at the 2026 cutoff, ${frozen.strength.toFixed(1)}.` : ""),
    ),
  );
  for (const v of niceTicks(lo, hi, 5)) {
    svg.append(
      s("line", { class: "grid", x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }),
      s("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" }, String(v)),
    );
  }
  for (const t of yearTicks(ts[0], x.invert(W - m.r))) {
    svg.append(s("text", { x: x(t.t), y: H - 8, "text-anchor": "middle" }, t.label));
  }
  for (const r of runs) {
    svg.append(s("path", { class: `line prov-${r.prov}`, d: pathOf([r.pts]) }));
  }
  Object.entries(starts).forEach(([year, iso], i) => {
    const xs = x(utcMs(iso));
    if (xs < m.l || xs > W - m.r) return;
    const ly = m.t - 12 - (i % 2) * 16; // alternate rows so neighbouring labels do not collide
    svg.append(
      s("line", { class: "start-line", x1: xs, x2: xs, y1: ly - 4, y2: H - m.b }),
      xs > W - 190
        ? s("text", { class: "start-label", x: xs - 4, y: ly, "text-anchor": "end" }, `Worlds ${year} starts`)
        : s("text", { class: "start-label", x: xs + 4, y: ly }, `Worlds ${year} starts`),
    );
  });
  points.forEach((p, i) => {
    const id = p[5] && matchOf[p[5]];
    if (!id) return;
    svg.append(
      s(
        "a",
        { href: `match.html?id=${encodeURIComponent(id)}`, tabindex: "-1", "aria-hidden": "true" },
        s("circle", { class: "dot", cx: x(ts[i]), cy: y(p[3]), r: 4 }),
        s("title", {}, `${dateLabel(p[0])} vs ${p[1]}: strength ${p[3].toFixed(1)}`),
      ),
    );
  });
  if (frozen) {
    const cx = x(frozenT);
    const cy = y(frozen.strength);
    svg.append(
      s("path", { class: "frozen-mark", d: `M${cx},${cy - 7}L${cx + 7},${cy}L${cx},${cy + 7}L${cx - 7},${cy}Z` }),
      s(
        "text",
        { class: "frozen-label", x: cx - 12, y: cy + 22, "text-anchor": "end" },
        `frozen strength ${frozen.strength.toFixed(1)}`,
      ),
    );
  }
  return svg;
}

/**
 * Reliability chart from the favourite's view: predicted vs observed win rate per bin.
 * series: [{ name, kind: "model" | "base", rows: [{ n, mean_pred, observed }] }].
 */
export function calibrationChart(series) {
  const W = 540;
  const H = 440;
  const m = { l: 60, r: 20, t: 20, b: 56 };
  const x = linear(0.5, 1, m.l, W - m.r);
  const y = linear(0.3, 1, H - m.b, m.t);
  const svg = s(
    "svg",
    { viewBox: `0 0 ${W} ${H}`, role: "img" },
    s("title", {}, "Calibration: how often the favourite won against its predicted probability"),
    s(
      "desc",
      {},
      "Points near the dashed diagonal mean the predicted probabilities matched how often the favourite won. " +
        "Filled teal circles are the model, open circles the original Elo. Circle size grows with the number of games.",
    ),
  );
  for (const v of niceTicks(0.3, 1, 7)) {
    svg.append(
      s("line", { class: "grid", x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }),
      s("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" }, pct(v, 0)),
    );
  }
  for (const v of niceTicks(0.5, 1, 5)) {
    svg.append(s("text", { x: x(v), y: H - m.b + 18, "text-anchor": "middle" }, pct(v, 0)));
  }
  svg.append(
    s("line", { class: "diag", x1: x(0.5), y1: y(0.5), x2: x(1), y2: y(1) }),
    s("text", { class: "axis-label", x: (m.l + W - m.r) / 2, y: H - 10, "text-anchor": "middle" }, "Predicted chance of the favourite"),
    s(
      "text",
      { class: "axis-label", transform: `translate(14 ${(m.t + H - m.b) / 2}) rotate(-90)`, "text-anchor": "middle" },
      "How often the favourite won",
    ),
  );
  for (const ser of series) {
    for (const r of ser.rows) {
      if (r.mean_pred === null || r.n === 0) continue;
      const radius = Math.min(14, 3 + Math.sqrt(r.n) * 0.9);
      svg.append(
        s(
          "circle",
          { class: ser.kind === "model" ? "pt-model" : "pt-base", cx: x(r.mean_pred), cy: y(r.observed), r: radius },
          s("title", {}, `${ser.name}: predicted ${pct(r.mean_pred)}, favourite won ${pct(r.observed)} (${r.n} games)`),
        ),
      );
    }
  }
  return svg;
}

/**
 * The knockout bracket. entries: match objects by id; each box links to its match page.
 * A row shows the series win probability (frozen) for that team; the winner gets a bar.
 */
export function bracket({ qfs, semis, byId }) {
  const W = 900;
  const H = 420;
  const bw = 236;
  const bh = 74;
  const cols = [0, 332, 664];
  const ys = { qf: [8, 108, 228, 328], sf: [58, 278], f: [168] };
  const svg = s(
    "svg",
    { class: "bracket", viewBox: `0 0 ${W} ${H}`, role: "group", "aria-label": "Knockout bracket" },
    s("title", {}, "Worlds 2026 knockout bracket with series win probabilities"),
    s(
      "desc",
      {},
      "Four quarterfinals feed two semifinals, which feed the final. Each box shows the two teams with " +
        "the probability that each wins that best-of-five series, and who won it if it has been played.",
    ),
  );
  const elbow = (x1, y1, x2, y2) => {
    const xm = (x1 + x2) / 2;
    return `M${x1},${y1}H${xm}V${y2}H${x2}`;
  };
  const place = [
    ...qfs.map((id, i) => ({ id, x: cols[0], y: ys.qf[i] })),
    ...semis.map((id, i) => ({ id, x: cols[1], y: ys.sf[i] })),
    { id: "2026-F", x: cols[2], y: ys.f[0] },
  ];
  const pos = Object.fromEntries(place.map((p) => [p.id, p]));
  semis.forEach((sid, i) => {
    [qfs[i * 2], qfs[i * 2 + 1]].forEach((q) =>
      svg.append(s("path", { class: "conn", d: elbow(pos[q].x + bw, pos[q].y + bh / 2, pos[sid].x, pos[sid].y + bh / 2) })),
    );
    svg.append(s("path", { class: "conn", d: elbow(pos[sid].x + bw, pos[sid].y + bh / 2, pos["2026-F"].x, pos["2026-F"].y + bh / 2) }));
  });
  const feeders = { "2026-SF1": ["QF1", "QF2"], "2026-SF2": ["QF3", "QF4"], "2026-F": ["SF1", "SF2"] };
  for (const { id, x: bx, y: by } of place) {
    const mt = byId[id];
    const done = mt.result.status === "final";
    const names = [mt.a ?? `Winner ${feeders[id][0]}`, mt.b ?? `Winner ${feeders[id][1]}`];
    const probs = mt.p_a === null ? [null, null] : [mt.p_a, 1 - mt.p_a];
    const label = mt.a
      ? `${mt.a} versus ${mt.b}: ${pct(mt.p_a)} to ${pct(1 - mt.p_a)}` +
        (done ? `; ${mt.result.winner} won ${mt.result.score.join("-")}` : "; not played yet")
      : `${id.slice(5)}: teams not decided yet`;
    const g = s("a", { href: `match.html?id=${encodeURIComponent(id)}` }, s("title", {}, label));
    g.append(s("rect", { class: "box", x: bx, y: by, width: bw, height: bh }));
    names.forEach((nm, i) => {
      const row = s("g", { class: done && mt.result.winner !== nm ? "lost" : "" });
      const ry = by + 22 + i * 20;
      if (done && mt.result.winner === nm) {
        row.append(s("rect", { class: "winner-bar", x: bx, y: ry - 14, width: 4, height: 18 }));
      }
      row.append(
        s("text", { x: bx + 12, y: ry, class: mt.a ? "" : "meta" }, clip(nm, 24)),
        probs[i] === null ? null : s("text", { class: "p", x: bx + bw - 10, y: ry, "text-anchor": "end" }, pct(probs[i], 1)),
      );
      g.append(row);
    });
    g.append(
      s(
        "text",
        { class: "meta", x: bx + 12, y: by + bh - 8 },
        `${id.slice(5)} · best of 5 · ` + (done ? `${mt.result.winner} won ${mt.result.score.join("–")}` : "pending"),
      ),
    );
    svg.append(g);
  }
  return svg;
}
