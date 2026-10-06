"use strict";

// Two tabs (issues #69, #74), and one view that is reachable but not a tab.
// `NAV_VIEWS` is what the header offers; `VIEWS` is what the router
// answers. Material is in the second list only: it is an action inside a
// goal, so it has a route and no tab of its own. Practising is a mode
// inside the tree (issue #69), not somewhere else to be. Progreso (issue
// #74) is the dashboard on top of the same engine data. `org` (issue #75) is
// the teacher view: reachable by anyone who types it, but the server answers
// 403 to a non-admin, and app.js only offers the link to an admin.
export const NAV_VIEWS = ["learning", "progress"];
export const VIEWS = [...NAV_VIEWS, "material", "org"];
const DEFAULT_VIEW = "learning";

// The views that stopped existing, pointed at the one that absorbed them:
// the topic list, the topic detail and the practice picker are all inside
// the learning tree. So every `#/topics/<id>` and `#/practice/<id>` already
// written - in a bookmark, or in material.js's back link - opens that goal
// instead of falling into the default view. `progress` came back in issue
// #74 as the dashboard tab.
const ALIASES = { topics: "learning", practice: "learning" };

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
