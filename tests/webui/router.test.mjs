// Unit tests for webui/js/router.js, run with Node's built-in test runner
// (`node --test`, no extra dependency - matching the front end's own "no
// build step" rule). Invoked from pytest by test_webui_router.py so the one
// suite `pytest` runs still covers it.

import { test } from "node:test";
import assert from "node:assert/strict";
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

test("parseHash recognises every declared view", () => {
  for (const view of VIEWS) {
    assert.equal(parseHash(`#/${view}`).view, view);
  }
});

test("buildHash round-trips through parseHash", () => {
  assert.equal(buildHash("topics", "ai-103"), "#/topics/ai-103");
  assert.deepEqual(parseHash(buildHash("topics", "ai-103")), {
    view: "topics",
    param: "ai-103",
  });
});
