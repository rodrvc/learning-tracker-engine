// Unit tests for webui/js/router.js under Node's built-in test runner (no
// build step, matching the front end's own rule). Wired into pytest by
// test_webui_router.py.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseHash, buildHash, VIEWS, NAV_VIEWS } from "../../webui/js/router.js";

test("parseHash defaults to learning for an empty hash", () => {
  assert.deepEqual(parseHash(""), { view: "learning", param: null });
});

test("parseHash reads the learning route", () => {
  assert.deepEqual(parseHash("#/learning"), { view: "learning", param: null });
});

test("parseHash reads a goal id as the route parameter", () => {
  assert.deepEqual(parseHash("#/learning/ai-103"), { view: "learning", param: "ai-103" });
});

test("parseHash falls back to learning for an unrecognised view", () => {
  assert.deepEqual(parseHash("#/whatever"), { view: "learning", param: null });
});

// The views issue #49 folded into the tree still resolve, parameter and all,
// so every #/topics/<id> and #/progress/<id> already written - in a bookmark,
// or in practice.js's own back link - opens that goal. Material keeps its
// route without keeping its tab: it is an action inside a goal now.
test("the retired views redirect, and material routes without a tab", () => {
  assert.deepEqual(parseHash("#/topics"), { view: "learning", param: null });
  assert.deepEqual(parseHash("#/topics/ai-103"), { view: "learning", param: "ai-103" });
  assert.deepEqual(parseHash("#/progress/ai-103"), { view: "learning", param: "ai-103" });
  assert.deepEqual(parseHash("#/material/ai-103"), { view: "material", param: "ai-103" });
  assert.equal(NAV_VIEWS.includes("material"), false);
});

// Literal, not derived: looping over the list to assert each entry parses to
// itself is tautological - deleting one would still pass, even though the nav
// still links to it.
test("the tabs are exactly the two of issue #49, in nav order", () => {
  assert.deepEqual(NAV_VIEWS, ["learning", "practice"]);
  assert.deepEqual(VIEWS, ["learning", "practice", "material"]);
});

test("every NAV_VIEWS entry has a nav link in index.html, and nothing else does", () => {
  const html = readFileSync(new URL("../../webui/index.html", import.meta.url), "utf8");
  const navViews = [...html.matchAll(/data-view="([a-z]+)"/g)].map((m) => m[1]);
  assert.deepEqual(navViews, NAV_VIEWS);
});

test("buildHash round-trips through parseHash", () => {
  assert.equal(buildHash("learning", "ai-103"), "#/learning/ai-103");
  assert.deepEqual(parseHash(buildHash("learning", "ai-103")), {
    view: "learning",
    param: "ai-103",
  });
});
