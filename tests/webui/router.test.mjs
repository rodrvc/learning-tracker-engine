// Unit tests for webui/js/router.js under Node's built-in test runner (no
// build step, matching the front end's own rule). Wired into pytest by
// test_webui_router.py.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseHash, buildHash, VIEWS } from "../../webui/js/router.js";

test("parseHash defaults to topics for an empty hash", () => {
  assert.deepEqual(parseHash(""), { view: "topics", param: null });
});

test("parseHash reads the topics list route", () => {
  assert.deepEqual(parseHash("#/topics"), { view: "topics", param: null });
});

test("parseHash reads a topic id as the route parameter", () => {
  assert.deepEqual(parseHash("#/topics/ai-103"), { view: "topics", param: "ai-103" });
});

test("parseHash falls back to topics for an unrecognised view", () => {
  assert.deepEqual(parseHash("#/whatever"), { view: "topics", param: null });
});

// Literal, not derived from VIEWS: looping over VIEWS to assert each entry
// parses to itself is tautological - deleting "progress" from the list
// would still pass, even though the nav still links to "#/progress".
test("VIEWS is exactly the four ACU-252 views, in nav order", () => {
  assert.deepEqual(VIEWS, ["topics", "material", "practice", "progress"]);
});

test("every VIEWS entry has a nav link in index.html, and nothing else does", () => {
  const html = readFileSync(new URL("../../webui/index.html", import.meta.url), "utf8");
  const navViews = [...html.matchAll(/data-view="([a-z]+)"/g)].map((m) => m[1]);
  assert.deepEqual(navViews, VIEWS);
});

test("buildHash round-trips through parseHash", () => {
  assert.equal(buildHash("topics", "ai-103"), "#/topics/ai-103");
  assert.deepEqual(parseHash(buildHash("topics", "ai-103")), { view: "topics", param: "ai-103" });
});
