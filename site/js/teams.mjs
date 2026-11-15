import { load } from "./data.mjs";
import { h, mount } from "./dom.mjs";
import { failure, shell } from "./shell.mjs";
import { dataTable } from "./ui.mjs";

await shell("teams.html", "Teams");
const main = document.getElementById("main");
try {
  const idx = await load("teams/index.json");
  const teams = [...idx.teams].sort((a, b) => a.league.localeCompare(b.league) || a.name.localeCompare(b.name));
  mount(
    main,
    h(
      "div",
      { class: "wrap" },
      h("h1", {}, "Teams"),
      h("p", { class: "lede" }, `Every team that played at Worlds 2023–2026 (${teams.length}). Each page shows the team's rating over time, regional games included.`),
      dataTable({
        caption: "Teams at Worlds 2023 to 2026",
        head: ["Team", "League", "Worlds"],
        rows: teams.map((t) => [
          h("a", { href: `team.html?t=${encodeURIComponent(t.slug)}` }, t.name),
          t.league ?? "",
          t.years.join(", "),
        ]),
      }),
      h("p", { class: "small" }, "League is the one the team was last rated in."),
    ),
  );
} catch (e) {
  mount(main, failure(e));
}
