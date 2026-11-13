import { eloChart } from "./charts.mjs";
import { load, slugs } from "./data.mjs";
import { h, mount, params } from "./dom.mjs";
import { badge, PROV } from "./prov.mjs";
import { failure, NotFound, shell } from "./shell.mjs";
import { dataTable, matchHref, scoreText, STAGE_LABEL, teamLink } from "./ui.mjs";
import { dateLabel, pct } from "./util.mjs";

const meta = await shell("teams.html", "Team");
const main = document.getElementById("main");
const slug = params.get("t") ?? "";

try {
  if (!/^[a-z0-9-]+$/.test(slug)) throw new NotFound("No team selected. Pick one from the Teams page.");
  const [team, all, ov, slugOf] = await Promise.all([load(`teams/${slug}.json`), load("matches.json"), load("overview_2026.json"), slugs()]);
  document.title = `${team.name} · LoL Worlds Predictor`;
  const byId = Object.fromEntries(all.matches.map((m) => [m.id, m]));
  const mine = team.matches.map((id) => byId[id]);
  const matchOf = {};
  for (const m of mine) for (const g of m.games ?? []) if (g.gameid) matchOf[g.gameid] = m.id;

  const pts = team.history.points;
  const fz = ov.teams.find((t) => t.team === team.name);
  const frozen = fz ? { strength: fz.strength, date: ov.frozen.prediction_cutoff_utc } : null;
  const last = pts.at(-1);

  const worlds = Object.entries(team.worlds).map(([year, w]) => [
    year,
    { node: w.strength.toFixed(1), num: true },
    w.league ?? "–",
    w.swiss_record ? `${w.swiss_record[0]}–${w.swiss_record[1]}` : "Play-in only",
    STAGE_LABEL[w.stage_reached] ?? (w.stage_reached === "champion" ? "Champion" : w.stage_reached),
  ]);

  const probFor = (m) => (m.p_a === null ? null : m.a === team.name ? m.p_a : 1 - m.p_a);
  const rows = mine.map((m) => {
    const opp = m.a === team.name ? m.b : m.a;
    const p = probFor(m);
    const done = m.result.status === "final";
    return [
      m.start ? dateLabel(m.start) : { node: "Not entered yet", cls: "pending" },
      `${m.year} ${STAGE_LABEL[m.stage]}`,
      opp ? teamLink(opp, slugOf) : "To be decided",
      done ? { node: `${m.result.winner === team.name ? "Won" : "Lost"} ${scoreText(m.result.winner === team.name ? m.result.score : [...m.result.score].reverse())}`, cls: m.result.winner === team.name ? "won" : "" } : { node: "Pending", cls: "pending" },
      { node: p === null ? "" : pct(p), num: true },
      badge(m.provenance, meta),
      h("a", { href: matchHref(m.id) }, "Details"),
    ];
  });

  const drift =
    frozen && Math.abs(frozen.strength - last[3]) >= 0.05
      ? h(
          "p",
          { class: "note" },
          `The last point (${last[3].toFixed(1)}) is the strength after ${team.name}'s last game on ${dateLabel(last[0])}. League offsets keep moving with other teams' international games, so the frozen strength at the cutoff is ${frozen.strength.toFixed(1)}.`,
        )
      : null;

  mount(
    main,
    h(
      "div",
      { class: "wrap" },
      h("h1", {}, team.name),
      h("p", { class: "lede" }, `Rated in ${team.league ?? "an unknown league"}. League offset ${team.league_offset.toFixed(1)} as of ${dateLabel(team.as_of)}, the team's last game.`),
      h("h2", {}, "Rating over time"),
      h(
        "figure",
        { class: "chart" },
        eloChart({ points: pts, starts: team.history.segment_starts, matchOf, frozen, name: team.name }),
        h(
          "figcaption",
          {},
          "Strength is the team's rating plus its league offset, one point per game, regional games included. Before each Worlds start the line is dashed: ",
          badge("replay", meta),
          " from the start on it is solid: ",
          badge("walk_forward", meta),
          ". The curve jumps at each start because each Worlds is rated with its own settings.",
        ),
        drift,
      ),
      h("h2", {}, "Worlds appearances"),
      dataTable({
        caption: "Strength going into each Worlds, Swiss record and furthest stage",
        head: ["Year", { text: "Strength at start", num: true }, "League", "Swiss record", "Furthest stage"],
        rows: worlds,
      }),
      team.path_to_title
        ? h(
            "section",
            {},
            h("h2", {}, "Path to the 2026 title"),
            h("p", { class: "head" }, badge("frozen", meta), h("span", { class: "small" }, "from the pre-quarterfinal run")),
            dataTable({
              caption: "Frozen chance of reaching each round in 2026",
              head: [{ text: "Semifinal", num: true }, { text: "Final", num: true }, { text: "Title", num: true }],
              rows: [[{ node: pct(team.path_to_title.semifinal), num: true }, { node: pct(team.path_to_title.final), num: true }, { node: pct(team.path_to_title.title), num: true }]],
            }),
          )
        : null,
      h("h2", {}, "Match history at Worlds"),
      h(
        "p",
        { class: "small" },
        "Chance is this team's probability of winning the series. Badges: " + Object.values(PROV).join(", ") + " (",
        h("a", { href: "model.html#provenance" }, "what they mean"),
        ").",
      ),
      dataTable({
        caption: `${team.name}: series played at Worlds 2023 to 2026`,
        head: ["Date", "Stage", "Opponent", "Result", { text: "Chance", num: true }, "Provenance", ""],
        rows,
      }),
    ),
  );
} catch (e) {
  mount(main, failure(e));
}
