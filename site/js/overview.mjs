import { bracket, hatchDefs, oddsBar } from "./charts.mjs";
import { load, slugs, FINAL_UTC } from "./data.mjs";
import { h, mount } from "./dom.mjs";
import { badge, derivationNote } from "./prov.mjs";
import { failure, shell } from "./shell.mjs";
import { dataTable, matchHref, scoreText, teamLink } from "./ui.mjs";
import { dateLabel, pct } from "./util.mjs";

const meta = await shell("index.html", "Worlds 2026 title odds");
const main = document.getElementById("main");

const STAGE_RANK = { quarterfinal: 0, semifinal: 1, final: 2 };
const STAGE_NAME = { quarterfinal: "quarterfinal", semifinal: "semifinal", final: "final" };

/** What happened to a team so far, from the finished 2026 knockout series. */
function outcome(team, ko) {
  let best = null;
  for (const m of ko) {
    if (m.result.status !== "final" || ![m.a, m.b].includes(team)) continue;
    if (best === null || STAGE_RANK[m.stage] > STAGE_RANK[best.stage]) best = m;
  }
  if (best === null) return h("span", { class: "pending" }, "Pending");
  if (best.result.winner === team) {
    return best.stage === "final" ? h("span", { class: "won" }, "Champion") : "Won the " + STAGE_NAME[best.stage];
  }
  return `Out in the ${STAGE_NAME[best.stage]}`;
}

try {
  const [ov, all, slugOf] = await Promise.all([load("overview_2026.json"), load("matches.json"), slugs()]);
  const ko = all.matches.filter((m) => m.year === 2026 && m.stage in STAGE_RANK);
  const byId = Object.fromEntries(ko.map((m) => [m.id, m]));
  const top = Math.max(...ov.teams.map((t) => t.title));
  const pending = ov.score.status === "pending";

  const rows = ov.teams.map((t) => [
    teamLink(t.team, slugOf),
    { node: t.swiss_record ? `${t.swiss_record[0]}–${t.swiss_record[1]}` : "", num: true },
    { node: pct(t.semifinal), num: true },
    { node: pct(t.final), num: true },
    { node: oddsBar(t.title, top, "frozen", `${t.team}: ${pct(t.title)} to win the title (frozen)`), cls: "bar-cell" },
    { node: pct(t.title), num: true, cls: "won" },
    { node: pct(t.sensitivity.title), num: true },
    outcome(t.team, ko),
  ]);

  mount(
    main,
    h(
      "div",
      { class: "wrap" },
      h("h1", {}, "Worlds 2026 title odds"),
      h("p", { class: "lede" }, `Computed from games before ${dateLabel(ov.frozen.prediction_cutoff_utc)}, before the quarterfinals were played.`),
      h(
        "div",
        { class: "head" },
        badge("frozen", meta),
        h("span", { class: "small" }, `Committed ${dateLabel(ov.frozen.committed_utc)}, after the quarterfinals had started, and never re-run.`),
      ),
      pending
        ? h(
            "div",
            { class: "panel", role: "status" },
            h("p", {}, h("strong", {}, "Results pending. "), `The final is on ${dateLabel(FINAL_UTC)} (UTC). Once the frozen prediction has been scored, this page shows how each team did.`),
          )
        : null,
      h(
        "figure",
        {},
        dataTable({
          caption: "Chance of reaching each round, with the Swiss record and what happened",
          head: [
            "Team",
            { text: "Swiss", num: true },
            { text: "Semifinal", num: true },
            { text: "Final", num: true },
            { text: "Title" },
            { text: "", num: true },
            { node: h("span", {}, "What-if title ", badge("sensitivity", meta)), num: true },
            "Result",
          ],
          rows,
        }),
        h(
          "figcaption",
          {},
          "Frozen probabilities from the pre-quarterfinal run (10,000 simulations, rating noise 50). The what-if column repeats the run with the side choice in quarterfinal game 1 as a coin flip: no team's title chance moves by more than " +
            `${(ov.sensitivity.max_abs_title_change * 100).toFixed(1)} points.`,
        ),
      ),
      h("h2", {}, "Bracket"),
      h(
        "figure",
        { class: "chart" },
        bracket({
          qfs: ov.bracket.quarterfinals.map((q) => q.id),
          semis: ["2026-SF1", "2026-SF2"],
          byId,
        }),
        h(
          "figcaption",
          {},
          "Each box shows the chance that a team wins that best-of-five series. Select a box for the match page. ",
          badge("frozen", meta),
        ),
        derivationNote("computed_from_frozen_inputs", meta),
      ),
      pending
        ? null
        : h(
            "section",
            {},
            h("h2", {}, "How the frozen prediction did"),
            h("p", { class: "small" }, `Scored on ${ov.score.n.series} series and ${ov.score.n.games} games. That is far too little to say anything about model quality.`),
            dataTable({
              caption: "Series log loss and Brier score",
              head: ["Forecast", { text: "Log loss", num: true }, { text: "Brier", num: true }],
              rows: Object.entries(ov.score.series_scores).map(([k, v]) => [
                { model: "Model (frozen)", half: "Coin flip", blue_only: "Blue-side bonus only" }[k] ?? k,
                { node: v.log_loss.toFixed(3), num: true },
                { node: v.brier.toFixed(3), num: true },
              ]),
            }),
          ),
      h(
        "p",
        { class: "small" },
        "Series pages: ",
        ov.bracket.quarterfinals.map((q, i) => [i ? ", " : "", h("a", { href: matchHref(q.id) }, q.id.slice(5))]),
        ".",
      ),
    ),
  );
  main.append(hatchDefs());
} catch (e) {
  mount(main, failure(e));
}
