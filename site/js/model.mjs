import { calibrationChart } from "./charts.mjs";
import { load } from "./data.mjs";
import { h, mount } from "./dom.mjs";
import { badge, PROV } from "./prov.mjs";
import { failure, shell } from "./shell.mjs";
import { dataTable } from "./ui.mjs";
import { pct } from "./util.mjs";

const meta = await shell("model.html", "Model");
const main = document.getElementById("main");
const YEARS = ["2023", "2024", "2025"];
const CLASS_LABEL = {
  "same-league": "Same league",
  "major-major": "Two major leagues",
  "major-minor": "Major v minor",
  "minor-minor": "Two minor leagues",
  unknown: "Unknown",
};

try {
  const md = await load("model.json");
  const v = md.variants;
  const me = v["+H+league"];
  const bs = md.bootstrap_vs_current["+H+league"];
  const f4 = (x) => x.toFixed(4);

  const variantRows = Object.entries(v).map(([k, x]) => [
    x.label,
    ...YEARS.map((y) => ({ node: x.per_year[y] ? f4(x.per_year[y].log_loss) : "", num: true })),
    { node: f4(x.pooled.log_loss), num: true },
    { node: f4(x.pooled.brier), num: true },
  ]);
  const modelIdx = Object.keys(v).indexOf("+H+league");

  const calRows = md.calibration["+H+league"].map((r) => [
    r.bin,
    { node: String(r.n), num: true },
    { node: r.mean_pred === null ? "" : pct(r.mean_pred), num: true },
    { node: r.observed === null ? "" : pct(r.observed), num: true },
  ]);
  const classRows = Object.entries(md.calibration_by_class["+H+league"]).map(([k, c]) => [
    CLASS_LABEL[k] ?? k,
    { node: String(c.n), num: true },
    { node: pct(c.mean_pred), num: true },
    { node: pct(c.observed), num: true },
    { node: f4(c.log_loss), num: true },
  ]);

  mount(
    main,
    h(
      "div",
      { class: "wrap" },
      h("h1", {}, "How good is the model?"),
      h(
        "p",
        { class: "lede" },
        "Replayed over Worlds 2023, 2024 and 2025, game by game, with each game predicted only from games before it. Log loss is the main score: lower is better, and a coin flip scores 0.693.",
      ),
      h("p", { class: "head" }, badge("walk_forward", meta), h("span", { class: "small" }, `${me.pooled.n} games`)),
      h("h2", {}, "Backtest"),
      dataTable({
        caption: "Log loss by year for the model and its baselines, with pooled log loss and Brier score",
        head: ["Forecast", ...YEARS.map((y) => ({ text: `${y} (n=${me.per_year[y].n})`, num: true })), { text: "Pooled log loss", num: true }, { text: "Pooled Brier", num: true }],
        rows: variantRows,
        rowClass: (i) => (i === modelIdx ? "model" : null),
      }),
      h(
        "p",
        {},
        `Against the original Elo the model's log loss is ${(-bs.mean).toFixed(4)} lower (95% interval ${(-bs.hi).toFixed(4)} to ${(-bs.lo).toFixed(4)} lower; paired bootstrap over games, ${md.bootstrap_samples} resamples).`,
      ),
      h("div", { class: "panel" }, h("p", {}, h("strong", {}, "In-sample caution. "), md.k_league.note)),
      h("h2", {}, "Calibration"),
      h(
        "figure",
        { class: "chart narrow" },
        calibrationChart([
          { name: "Model", kind: "model", rows: md.calibration["+H+league"] },
          { name: "Original Elo", kind: "base", rows: md.calibration.current },
        ]),
        h("figcaption", {}, "From the favourite's side: if the model says 70%, the favourite should win about 70% of such games. Filled circles are the model, open circles the original Elo; bigger circles are more games."),
      ),
      dataTable({
        caption: "Model calibration by predicted-probability bin",
        head: ["Bin", { text: "Games", num: true }, { text: "Predicted", num: true }, { text: "Favourite won", num: true }],
        rows: calRows,
      }),
      dataTable({
        caption: "Model calibration by type of matchup",
        head: ["Matchup", { text: "Games", num: true }, { text: "Predicted", num: true }, { text: "Favourite won", num: true }, { text: "Log loss", num: true }],
        rows: classRows,
      }),
      h("h2", {}, "What the model is"),
      h(
        "ul",
        {},
        h("li", {}, "Team Elo ratings, K = 32, where each old game counts less (half-life 182 days)."),
        h("li", {}, "A bonus for the blue side, measured from the year before each tournament."),
        h("li", {}, "A rating for each league, moved only by international games, so regions can be compared."),
        h("li", {}, "The 2026 knockout uses a side model for the right of first selection, then a Monte Carlo simulation with rating noise."),
        h("li", {}, "Every change had to improve backtest log loss. ", h("a", { href: "https://github.com/Tofu80/LoL-Worlds-Predictor/blob/main/docs/decisions.md" }, "The decision log")),
      ),
      h("h2", { id: "provenance" }, "What the badges mean"),
      h("p", {}, "Every probability on this site says where it came from, and the mark is drawn the same way everywhere."),
      h(
        "dl",
        { class: "facts" },
        Object.keys(PROV).flatMap((k) => [h("dt", {}, badge(k, meta)), h("dd", {}, meta.legend[k])]),
      ),
      h("h3", {}, "How a number was derived"),
      h("ul", {}, Object.values(meta.derivation_text).map((t) => h("li", {}, t))),
    ),
  );
  if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
} catch (e) {
  mount(main, failure(e));
}
