const cache = new Map();

/** Fetch site/data/<path> once. */
export function load(path) {
  if (!cache.has(path)) {
    cache.set(
      path,
      fetch(`data/${path}`).then((r) => {
        if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
        return r.json();
      }),
    );
  }
  return cache.get(path);
}

/** Team name -> slug, from the index. */
export async function slugs() {
  const idx = await load("teams/index.json");
  return Object.fromEntries(idx.teams.map((t) => [t.name, t.slug]));
}

// The final is on 14 November 2026 (UTC); until the frozen prediction is scored the site
// shows the 2026 knockout as pending.
export const FINAL_UTC = "2026-11-14";
