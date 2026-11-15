// Tiny element builders. Text is always added as text nodes, never parsed as HTML, so
// team names and other data cannot inject markup.
const SVG_NS = "http://www.w3.org/2000/svg";

function build(node, attrs, kids) {
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid);
  }
  return node;
}

export const h = (tag, attrs = {}, ...kids) =>
  build(document.createElement(tag), attrs, kids);
export const s = (tag, attrs = {}, ...kids) =>
  build(document.createElementNS(SVG_NS, tag), attrs, kids);

export const params = new URLSearchParams(location.search);

export function mount(node, ...kids) {
  node.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== false));
  return node;
}
