import { load, slugs, FINAL_UTC } from "./data.mjs";
import { h, mount, params } from "./dom.mjs";
import { badge, derivationNote } from "./prov.mjs";
import { failure, NotFound, shell } from "./shell.mjs";
import { dataTable, FORMAT_LABEL, scoreText, STAGE_LABEL, teamLink } from "./ui.mjs";
import { dateTimeLabel, pct } from "./util.mjs";

const meta = await shell("matches.html", "Match");
const main = document.getElementById("main");
const id = params.get("id") ?? "";

try {
  const [all, slugOf] = await Promise.all([load("matches.json"), slugs()]);
  const m = all.matches.find((x) => x.id === id);
  if (!m) throw new NotFound("No such match. Pick one from the Matches page.");
  const decided = m.a !== null;
  const title = decided ? `${m.a} v ${m.b}` : `${STAGE_LABEL[m.stage]} (teams not decided)`;
  document.title = `${title} · LoL Worlds Predictor`;
  const done = m.result.status === "final";
  const a = m.a ?? "TBD";
  const b = m.b ?? "TBD";

  const facts = [];
  const add = (k, v) => v !== null && v !== undefined && facts.push(h("dt", {}, k), h("dd", {}, v));
  if (m.assumptions) {
    const x = m.assumptions;
    add("Blue-side bonus (H)", `${x.h.toFixed(1)} rating points for the blue team`);
    add("Side model", x.side.replace("higher_seed", "the team with the better Swiss record").replace("coin_flip", "a coin flip"));
    add("Series model", x.series_model);
    if (x.q !== undefined) add("Chance the side holder ends up on blue (q)", pct(x.q));
    if (x.sigma !== undefined) add("Rating noise averaged over", `sigma ${x.sigma}`);
    add(`Strength of ${a}`, x.strength_a.toFixed(1));
    add(`Strength of ${b}`, x.strength_b.toFixed(1));
    if (x.k_league_in_sample) add("Caution", "The league-offset setting (k_league) was chosen on the 2023–24 results, which include this match.");
  }

  const when =
    m.played_before_commit === true
      ? "Played before the frozen prediction was committed (10 Nov 2026)."
      : m.played_before_commit === false
        ? "Played after the frozen prediction was committed (10 Nov 2026)."
        : m.provenance === "frozen"
          ? "Start time not entered yet, so it is not known whether this was played before the commit."
          : null;

  const games = (m.games ?? []).map((g) => [
    { node: String(g.n), num: true },
    g.blue,
    g.red,
    { node: pct(g.p_blue), num: true },
    badge(g.provenance, meta),
    g.blue_won ? `${g.blue} won` : `${g.red} won`,
    { node: g.log_loss.toFixed(3), num: true },
  ]);

  mount(
    main,
    h(
      "div",
      { class: "wrap" },
      h("p", { class: "small" }, h("a", { href: "matches.html" }, "All matches")),
      h("h1", {}, title),
      h(
        "div",
        { class: "head" },
        h("span", {}, `${m.year} ${STAGE_LABEL[m.stage]} · ${FORMAT_LABEL[m.format]}`),
        m.start ? h("span", { class: "muted" }, dateTimeLabel(m.start)) : null,
      ),
      decided
        ? h(
            "div",
            { class: "versus" },
            h("div", { class: "team" }, teamLink(a, slugOf)),
            h("div", { class: "vs" }, "versus"),
            h("div", { class: "team b" }, teamLink(b, slugOf)),
          )
        : null,
      h("h2", {}, "Probability before the match"),
      decided
        ? h(
            "div",
            {},
            h(
              "div",
              { class: `probbar prov-${m.provenance}`, role: "img", "aria-label": `${a} ${pct(m.p_a)}, ${b} ${pct(1 - m.p_a)}` },
              h("span", { class: "a", style: `width:${(m.p_a * 100).toFixed(2)}%` }),
            ),
            h("div", { class: "problabels", "aria-hidden": "true" }, h("span", {}, `${a} ${pct(m.p_a)}`), h("span", { class: "b" }, `${b} ${pct(1 - m.p_a)}`)),
            h("p", { class: "head" }, badge(m.provenance, meta), h("span", { class: "small" }, "chance of winning the series")),
            derivationNote(m.derivation, meta),
            when ? h("p", { class: "note" }, when) : null,
          )
        : h("p", {}, "The teams are decided by the earlier knockout results, so there is no probability yet."),
      facts.length ? h("div", {}, h("h2", {}, "Assumptions"), h("dl", { class: "facts" }, facts)) : null,
      h(
        "h2",
        {},
        "Result",
      ),
      done
        ? h(
            "div",
            {},
            h("p", {}, h("strong", { class: "won" }, `${m.result.winner} won ${scoreText(m.result.score)}.`)),
            h(
              "p",
              {},
              `Log-loss contribution: ${m.log_loss.toFixed(3)} (minus the natural log of the probability given to the winner; lower is better, 0.693 is a coin flip).`,
            ),
          )
        : h(
            "div",
            { class: "panel", role: "status" },
            h("p", {}, h("strong", {}, "Pending. "), m.year === 2026 ? `Results appear once the frozen prediction is scored; the final is on ${dateTimeLabel(FINAL_UTC)} (UTC).` : "No result recorded."),
          ),
      games.length
        ? h(
            "div",
            {},
            h("h2", {}, "Games"),
            dataTable({
              caption: "Game by game: probability that the blue team wins, and the log loss of each game",
              head: [{ text: "Game", num: true }, "Blue", "Red", { text: "Blue wins", num: true }, "Provenance", "Outcome", { text: "Log loss", num: true }],
              rows: games,
            }),
            h("p", { class: "note" }, "Each game uses the side actually played. The series probability above averages over sides instead, so the two do not multiply out."),
          )
        : null,
    ),
  );
} catch (e) {
  mount(main, failure(e));
}
