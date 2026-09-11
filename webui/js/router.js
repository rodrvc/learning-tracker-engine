"use strict";

// The four views ACU-252 defines, all now wired to a real view in app.js.
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
