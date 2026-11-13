import { h } from "./dom.mjs";

export const PROV = {
  frozen: "Frozen",
  walk_forward: "Walk-forward",
  replay: "Replay",
  sensitivity: "What-if",
};

/**
 * Provenance badge: the swatch is drawn the same way in badges, lines and bars. A probability
 * computed from the frozen inputs (not saved on the day) carries that caveat in its tooltip too.
 */
export function badge(prov, meta, derivation = null) {
  const caveat = derivation === "computed_from_frozen_inputs" ? ` ${meta.derivation_text[derivation]}` : "";
  return h(
    "a",
    {
      class: `badge prov-${prov}`,
      href: "model.html#provenance",
      title: meta.legend[prov] + caveat,
    },
    h("span", { class: "swatch", "aria-hidden": "true" }),
    PROV[prov],
  );
}

/**
 * Notes to print under a list of matches: how frozen series chances were derived, and the
 * k_league caution for 2023-24 matches. Returns an array of nodes (possibly empty).
 */
export function listNotes(matches, meta) {
  const notes = [];
  if (matches.some((m) => m.derivation === "computed_from_frozen_inputs")) {
    notes.push(derivationNote("computed_from_frozen_inputs", meta));
  }
  if (matches.some((m) => m.assumptions?.k_league_in_sample)) {
    notes.push(
      h("p", { class: "note" }, "The league-offset setting (k_league) was chosen on the 2023\u201324 results, so probabilities for those years are in-sample."),
    );
  }
  return notes;
}

/** One line saying how a probability was derived (saved, recomputed from frozen inputs, ...). */
export function derivationNote(derivation, meta) {
  return derivation ? h("p", { class: "note" }, meta.derivation_text[derivation]) : null;
}
