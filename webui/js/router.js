"use strict";

// The four views ACU-252 defines. Only "topics" has a view registered yet;
// the other three are declared here as real destinations - the nav links to
// them and the router recognises them - rather than left out entirely, which
// is what turns them into filler screens instead of an honest "not built
// yet".
export const VIEWS = ["topics", "material", "practice", "progress"];
const DEFAULT_VIEW = "topics";

/**
 * Turns a location hash into a view name and an optional path parameter.
 *
 * Kept free of the DOM on purpose: it is the one piece of navigation logic
 * worth unit testing without a browser, and doing so needs no more than a
 * string in and a plain object out.
 */
export function parseHash(hash) {
  const cleaned = (hash || "").replace(/^#\/?/, "");
  const [view, param] = cleaned.split("/").filter(Boolean);
  if (!VIEWS.includes(view)) {
    return { view: DEFAULT_VIEW, param: null };
  }
  return { view, param: param || null };
}

export function buildHash(view, param) {
  return param ? `#/${view}/${param}` : `#/${view}`;
}
