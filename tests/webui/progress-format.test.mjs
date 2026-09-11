// Unit tests for the progress view's DOM-free helpers in webui/js/format.js
// (ACU-268). Same escaping discipline as format.test.mjs: every assertion
// that a raw tag is absent is paired with one that its escaped form is
// present, so a mutant that drops the field from the markup - rather than
// merely failing to escape it - still fails a test.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  LEVEL_ORDER,
  levelLabel,
  levelBreakdownView,
  objectiveRowView,
  dueListView,
  unstartedListView,
  describeProgressError,
} from "../../webui/js/format.js";

test("levelLabel translates every SPEC level to its Spanish product name", () => {
  assert.equal(levelLabel("UNASSESSED"), "Sin evaluar");
  assert.equal(levelLabel("WEAK"), "Débil");
  assert.equal(levelLabel("LEARNING"), "Aprendiendo");
  assert.equal(levelLabel("COMPETENT"), "Competente");
  assert.equal(levelLabel("MASTERED"), "Dominado");
});

test("levelLabel falls back to the raw identifier instead of going blank", () => {
  assert.equal(levelLabel("SOMETHING_NEW"), "SOMETHING_NEW");
});

test("LEVEL_ORDER is the SPEC 1.4 ladder, weakest evidence first", () => {
  assert.deepEqual(LEVEL_ORDER, ["UNASSESSED", "WEAK", "LEARNING", "COMPETENT", "MASTERED"]);
});

test("levelBreakdownView renders one row per level, in ladder order", () => {
  const html = levelBreakdownView({
    UNASSESSED: 2,
    WEAK: 1,
    LEARNING: 0,
    COMPETENT: 3,
    MASTERED: 5,
  });
  const order = ["Sin evaluar", "Débil", "Aprendiendo", "Competente", "Dominado"].map((label) =>
    html.indexOf(label),
  );
  assert.deepEqual(
    [...order].sort((a, b) => a - b),
    order,
  );
  assert.ok(html.includes(">2<"));
  assert.ok(html.includes(">5<"));
});

test("levelBreakdownView shows a level missing from the response as a zero, not a dropped row", () => {
  // The engine always sends all five (core/tracker.py's `by_level`), but a
  // row that silently disappeared on a missing key would be exactly the
  // kind of "0 mastered" information this screen exists to show reliably.
  const html = levelBreakdownView({ WEAK: 4 });
  assert.ok(html.includes("Sin evaluar"));
  assert.ok(html.includes(">0<"));
});

test("objectiveRowView escapes an attacker-controlled title", () => {
  const state = { objective_id: "obj-1", level: "WEAK" };
  const html = objectiveRowView(state, "<img src=x onerror=alert(1)>", "topic-1");
  assert.equal(html.includes("<img src"), false);
  assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));
});

test("objectiveRowView falls back to the objective id when no title was found", () => {
  const html = objectiveRowView({ objective_id: "obj-9", level: "MASTERED" }, undefined, "t1");
  assert.ok(html.includes("obj-9"));
});

test("objectiveRowView shows the level the API returned, translated to Spanish", () => {
  const html = objectiveRowView({ objective_id: "o1", level: "COMPETENT" }, "Title", "t1");
  assert.ok(html.includes("Competente"));
});

test("objectiveRowView links into practising the topic, percent-encoded", () => {
  const html = objectiveRowView({ objective_id: "o1", level: "WEAK" }, "Title", "a b");
  assert.ok(html.includes('href="#/practice/a%20b"'));
});

test("dueListView shows the specific empty-state message when nothing is due", () => {
  const html = dueListView([], () => "x", "t1");
  assert.ok(html.includes("No hay nada vencido por ahora."));
});

test("dueListView renders one row per due objective, using the caller's title lookup", () => {
  const states = [
    { objective_id: "o1", level: "WEAK" },
    { objective_id: "o2", level: "LEARNING" },
  ];
  const titleFor = (id) => ({ o1: "First", o2: "Second" })[id];
  const html = dueListView(states, titleFor, "t1");
  assert.ok(html.includes("First"));
  assert.ok(html.includes("Second"));
});

test("unstartedListView shows the specific empty-state message when everything was practised", () => {
  const html = unstartedListView([], () => "x", "t1");
  assert.ok(html.includes("Ya se practicó cada objetivo al menos una vez."));
});

test("unstartedListView renders one row per unstarted objective", () => {
  const states = [{ objective_id: "o3", level: "UNASSESSED" }];
  const html = unstartedListView(states, () => "Third", "t1");
  assert.ok(html.includes("Third"));
  assert.ok(html.includes("Sin evaluar"));
});

test("describeProgressError names the missing topic on a 404 unknown-topic response", () => {
  const message = describeProgressError(
    { status: 404, message: "unknown topic: ai-103" },
    { topicId: "ai-103" },
  );
  assert.equal(message, 'No existe el tema "ai-103".');
});

test("describeProgressError passes every other failure through verbatim", () => {
  assert.equal(
    describeProgressError({ status: 500, message: "boom" }, { topicId: "ai-103" }),
    "boom",
  );
});
