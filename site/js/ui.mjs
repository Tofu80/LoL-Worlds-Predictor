import { h } from "./dom.mjs";

/**
 * Accessible data table. head: [{ text | node, num? }]; rows: arrays of cells where a cell is
 * a string, a node, or { node | text, num?, cls? }.
 */
export function dataTable({ caption, head, rows, rowClass }) {
  const cell = (c, tag, hd) => {
    const o = c !== null && typeof c === "object" && !(c instanceof Node) ? c : { node: c };
    const num = o.num ?? hd?.num;
    return h(tag, { class: [num ? "num" : "", o.cls ?? ""].join(" ").trim() || null, scope: tag === "th" ? "col" : null }, o.node ?? o.text);
  };
  return h(
    "div",
    { class: "scroll", tabindex: "0", role: "region", "aria-label": caption },
    h(
      "table",
      {},
      h("caption", { class: "sr" }, caption),
      h("thead", {}, h("tr", {}, head.map((c) => cell(typeof c === "string" ? { node: c } : { node: c.node ?? c.text, num: c.num }, "th")))),
      h(
        "tbody",
        {},
        rows.map((r, i) =>
          h(
            "tr",
            { class: rowClass ? rowClass(i) : null },
            r.map((c, j) => cell(c, "td", head[j] && typeof head[j] === "object" ? head[j] : null)),
          ),
        ),
      ),
    ),
  );
}

export function teamLink(name, slugOf) {
  const slug = slugOf[name];
  return slug ? h("a", { href: `team.html?t=${encodeURIComponent(slug)}` }, name) : name;
}

export function matchHref(id) {
  return `match.html?id=${encodeURIComponent(id)}`;
}

/** "3–1" with the winner first. */
export function scoreText(score) {
  return `${score[0]}–${score[1]}`;
}

export const STAGE_LABEL = {
  "play-in": "Play-in",
  swiss: "Swiss",
  quarterfinal: "Quarterfinal",
  semifinal: "Semifinal",
  final: "Final",
};

export const FORMAT_LABEL = { bo1: "Best of 1", bo3: "Best of 3", bo5: "Best of 5" };
