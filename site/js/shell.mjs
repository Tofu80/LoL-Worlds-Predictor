import { h } from "./dom.mjs";
import { load } from "./data.mjs";

const NAV = [
  ["index.html", "Overview"],
  ["teams.html", "Teams"],
  ["matches.html", "Matches"],
  ["model.html", "Model"],
];
const REPO = "https://github.com/Tofu80/LoL-Worlds-Predictor";
const RIOT_NOTICE =
  'LoL Worlds Predictor was created under Riot Games\' "Legal Jibber Jabber" policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.';

/** Header, footer and page title. Returns the loaded meta.json for the page to use. */
export async function shell(active, title) {
  document.title = title ? `${title} · LoL Worlds Predictor` : "LoL Worlds Predictor";
  const main = document.getElementById("main");
  document.body.prepend(
    h("a", { class: "skip", href: "#main" }, "Skip to content"),
    h(
      "header",
      { class: "site" },
      h(
        "div",
        { class: "wrap bar" },
        h("a", { class: "brand", href: "index.html" }, "LoL Worlds Predictor"),
        h(
          "nav",
          { "aria-label": "Main" },
          NAV.map(([href, label]) =>
            h("a", { href, "aria-current": href === active ? "page" : null }, label),
          ),
        ),
      ),
    ),
  );
  let meta;
  try {
    meta = await load("meta.json");
  } catch (e) {
    main.replaceChildren(failure(e));
    throw e;
  }
  document.body.append(
    h(
      "footer",
      { class: "site" },
      h(
        "div",
        { class: "wrap" },
        h(
          "p",
          {},
          "Game results come from ",
          h("a", { href: "https://oracleselixir.com" }, "Oracle's Elixir"),
          ". Only team-level results are used here; no player data.",
        ),
        h("p", {}, RIOT_NOTICE),
        h(
          "p",
          { class: "small" },
          `Data exported ${meta.generated_at.slice(0, 10)} from commit ${meta.commit.slice(0, 7)}. `,
          h("a", { href: REPO }, "Source code and modelling decisions"),
          ".",
        ),
      ),
    ),
  );
  return meta;
}

/** An error that means "no such page" rather than "the data failed to load". */
export class NotFound extends Error {}

/** A readable error instead of a blank page (for example when opened from file://). */
export function failure(e) {
  if (e instanceof NotFound) {
    return h(
      "div",
      { class: "wrap error", role: "alert" },
      h("h1", {}, "Not found"),
      h("p", {}, e.message),
      h("p", {}, h("a", { href: "index.html" }, "Back to the overview")),
    );
  }
  return h(
    "div",
    { class: "wrap error", role: "alert" },
    h("h1", {}, "The data could not be loaded"),
    h(
      "p",
      {},
      "This site reads JSON files, so it has to be served over http (for example ",
      h("code", {}, "python -m http.server -d site"),
      "), not opened as a file.",
    ),
    h("p", { class: "small" }, String(e.message || e)),
  );
}
