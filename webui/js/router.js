"use strict";

// One tab (issue #69), and one view that is reachable but not a tab.
// `NAV_VIEWS` is what the header offers; `VIEWS` is what the router
// answers. Material is in the second list only: it is an action inside a
// goal, so it has a route and no tab of its own. A nav of one entry is not
// a nav, which is the point: there is one place, and practising is a mode
// inside it rather than somewhere else to be.
export const NAV_VIEWS = ["learning"];
export const VIEWS = [...NAV_VIEWS, "material"];
const DEFAULT_VIEW = "learning";

// The views that stopped existing, pointed at the one that absorbed them:
// the topic list, the topic detail, the progress screen and now the
// practice picker are all inside the learning tree. So every
// `#/topics/<id>`, `#/progress/<id>` and `#/practice/<id>` already written
// - in a bookmark, or in material.js's back link - opens that goal instead
// of falling into the default view.
const ALIASES = { topics: "learning", progress: "learning", practice: "learning" };

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
