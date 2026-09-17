"use strict";

// Two tabs (issue #49), and one view that is reachable but not a tab.
// `NAV_VIEWS` is what the header offers; `VIEWS` is what the router
// answers. Material is in the second list only: it is an action inside a
// goal, so it has a route and no tab of its own.
export const NAV_VIEWS = ["learning", "practice"];
export const VIEWS = [...NAV_VIEWS, "material"];
const DEFAULT_VIEW = "learning";

// The views that stopped existing, pointed at the one that absorbed them:
// the topic list, the topic detail and the progress screen are all inside
// the learning tree now. So every `#/topics/<id>` and `#/progress/<id>`
// already written - in a bookmark, or in practice.js's and material.js's
// back links - opens that goal instead of falling into the default view.
const ALIASES = { topics: "learning", progress: "learning" };

/**
 * Turns a location hash into a view name and an optional path parameter.
 *
 * Kept free of the DOM on purpose: it is the one piece of navigation logic
 * worth unit testing without a browser, and doing so needs no more than a
 * string in and a plain object out.
 */
export function parseHash(hash) {
  const cleaned = (hash || "").replace(/^#\/?/, "");
  const [raw, param] = cleaned.split("/").filter(Boolean);
  const view = ALIASES[raw] || raw;
  if (!VIEWS.includes(view)) {
    return { view: DEFAULT_VIEW, param: null };
  }
  return { view, param: param || null };
}

export function buildHash(view, param) {
  return param ? `#/${view}/${param}` : `#/${view}`;
}
