import { h } from "./dom.mjs";

export const PROV = {
  frozen: "Frozen",
  walk_forward: "Walk-forward",
  replay: "Replay",
  sensitivity: "What-if",
};

/** Provenance badge: the swatch is drawn the same way in badges, lines and bars. */
export function badge(prov, meta) {
  return h(
    "a",
    {
      class: `badge prov-${prov}`,
      href: "model.html#provenance",
      title: meta.legend[prov],
    },
    h("span", { class: "swatch", "aria-hidden": "true" }),
    PROV[prov],
  );
}

/** One line saying how a probability was derived (saved, recomputed from frozen inputs, ...). */
export function derivationNote(derivation, meta) {
  return derivation ? h("p", { class: "note" }, meta.derivation_text[derivation]) : null;
}
