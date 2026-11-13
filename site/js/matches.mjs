import { load, slugs } from "./data.mjs";
import { h, mount } from "./dom.mjs";
import { badge } from "./prov.mjs";
import { failure, shell } from "./shell.mjs";
import { dataTable, FORMAT_LABEL, matchHref, scoreText, STAGE_LABEL } from "./ui.mjs";
import { dateLabel, pct } from "./util.mjs";

const meta = await shell("matches.html", "Matches");
const main = document.getElementById("main");

try {
  const [all, slugOf] = await Promise.all([load("matches.json"), slugs()]);
  const ms = all.matches;
  const years = [...new Set(ms.map((m) => m.year))].sort();
  const stages = Object.keys(STAGE_LABEL);
  const year = h("select", { id: "f-year" }, h("option", { value: "" }, "All years"), years.map((y) => h("option", { value: y }, y)));
  const stage = h("select", { id: "f-stage" }, h("option", { value: "" }, "All stages"), stages.map((s) => h("option", { value: s }, STAGE_LABEL[s])));
  const search = h("input", { id: "f-team", type: "search", placeholder: "Team name" });
  const count = h("p", { class: "small", role: "status" });
  const holder = h("div", {});

  const render = () => {
    const q = search.value.trim().toLowerCase();
    const rows = ms.filter(
      (m) =>
        (!year.value || String(m.year) === year.value) &&
        (!stage.value || m.stage === stage.value) &&
        (!q || [m.a, m.b].some((t) => t && t.toLowerCase().includes(q))),
    );
    count.textContent = `Showing ${rows.length} of ${ms.length} series.`;
    mount(
      holder,
      dataTable({
        caption: "Worlds series 2023 to 2026",
        head: ["Date", "Stage", "Teams", "Format", { text: "Chance team 1 wins", num: true }, "Result", "Provenance", ""],
        rows: rows.map((m) => [
          m.start ? dateLabel(m.start) : { node: "Not entered yet", cls: "pending" },
          `${m.year} ${STAGE_LABEL[m.stage]}`,
          m.a ? `${m.a} v ${m.b}` : { node: "To be decided", cls: "pending" },
          FORMAT_LABEL[m.format],
          { node: m.p_a === null ? "" : pct(m.p_a), num: true },
          m.result.status === "final" ? `${m.result.winner} ${scoreText(m.result.score)}` : { node: "Pending", cls: "pending" },
          badge(m.provenance, meta),
          h("a", { href: matchHref(m.id) }, "Details"),
        ]),
      }),
    );
  };
  for (const el of [year, stage]) el.addEventListener("change", render);
  search.addEventListener("input", render);

  mount(
    main,
    h(
      "div",
      { class: "wrap" },
      h("h1", {}, "Matches"),
      h("p", { class: "lede" }, "Every series at Worlds 2023–2026 with the probability the model gave before it was played. Team 1 is the team on blue side in game 1 (or the first-listed team in the 2026 knockout)."),
      h(
        "div",
        { class: "filters", role: "search" },
        h("label", { for: "f-year" }, "Year", year),
        h("label", { for: "f-stage" }, "Stage", stage),
        h("label", { for: "f-team" }, "Team", search),
      ),
      count,
      holder,
    ),
  );
  render();
} catch (e) {
  mount(main, failure(e));
}
