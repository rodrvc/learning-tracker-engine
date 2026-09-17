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
  levelMixView,
  coverageHeroView,
  summaryTilesView,
  objectiveRowView,
  dueListView,
  unstartedListView,
  progressActionView,
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

test("levelBreakdownView appends a level the ladder does not name, through levelLabel's own fallback", () => {
  // Review round 1 (ACU-268): the previous version only ever iterated
  // LEVEL_ORDER, so a key present in the response but absent from the
  // ladder never rendered at all - the row vanished and levelLabel's
  // documented "show something instead of a blank row" fallback was
  // unreachable from here. Escaped, since an unknown identifier now
  // reaches the same interpolation a title does.
  const html = levelBreakdownView({ WEAK: 1, "<b>NEW</b>": 3 });
  assert.equal(html.includes("<b>NEW</b>"), false);
  assert.ok(html.includes("&lt;b&gt;NEW&lt;/b&gt;"));
  assert.ok(html.includes(">3<"));
});

test("objectiveRowView escapes an attacker-controlled title", () => {
  const state = { objective_id: "obj-1", level: "WEAK" };
  const html = objectiveRowView(state, "<img src=x onerror=alert(1)>");
  assert.equal(html.includes("<img src"), false);
  assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));
});

test("objectiveRowView falls back to the objective id when no title was found", () => {
  const html = objectiveRowView({ objective_id: "obj-9", level: "MASTERED" }, undefined);
  assert.ok(html.includes("obj-9"));
});

test("objectiveRowView shows the level the API returned, translated to Spanish", () => {
  const html = objectiveRowView({ objective_id: "o1", level: "COMPETENT" }, "Title");
  assert.ok(html.includes("Competente"));
});

test("objectiveRowView carries no link of its own - see the section-level action instead", () => {
  // Review round 1 (ACU-268): a per-row "Practicar" link beside this row's
  // own title and level implied a click there would practise this row's
  // objective. The endpoint gives no such guarantee (not even for the due
  // list's first row - it skips any objective with no stored question), so
  // the row promises nothing it cannot keep.
  const html = objectiveRowView({ objective_id: "o1", level: "WEAK" }, "Title");
  assert.equal(html.includes("<a "), false);
});

test("dueListView shows the specific empty-state message when nothing is due", () => {
  const html = dueListView([], () => "x");
  assert.ok(html.includes("No hay nada vencido por ahora."));
});

test("dueListView renders one row per due objective, using the caller's title lookup", () => {
  const states = [
    { objective_id: "o1", level: "WEAK" },
    { objective_id: "o2", level: "LEARNING" },
  ];
  const titleFor = (id) => ({ o1: "First", o2: "Second" })[id];
  const html = dueListView(states, titleFor);
  assert.ok(html.includes("First"));
  assert.ok(html.includes("Second"));
});

test("neither list carries an action of its own - the page has exactly one", () => {
  // Two links meant two promises for one behaviour, and the unstarted one
  // was false whenever a due objective had a question, which is the normal
  // state of a topic in use.
  const states = [{ objective_id: "o1", level: "WEAK" }];
  assert.equal(dueListView(states, () => "x").includes("<a "), false);
  assert.equal(unstartedListView(states, () => "x").includes("<a "), false);
});

test("the action names the order the engine walks, and links into practice", () => {
  const html = progressActionView("a b");
  assert.ok(html.includes("primero lo vencido, después lo nunca practicado"));
  assert.ok(html.includes('href="#/practice/a%20b"'));
});

test("unstartedListView shows the specific empty-state message when everything was practised", () => {
  const html = unstartedListView([], () => "x");
  assert.ok(html.includes("Ya se practicó cada objetivo al menos una vez."));
});

test("unstartedListView renders one row per unstarted objective", () => {
  const states = [{ objective_id: "o3", level: "UNASSESSED" }];
  const html = unstartedListView(states, () => "Third");
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

test("describeProgressError does not special-case a non-404 status even if the message reads unknown topic", () => {
  // Closes the `&&` -> `||` mutant: with `||`, a non-404 status alone would
  // be enough to trigger the Spanish rewrite.
  assert.equal(
    describeProgressError({ status: 500, message: "unknown topic: ai-103" }, { topicId: "ai-103" }),
    "unknown topic: ai-103",
  );
});

test("describeProgressError does not special-case a 404 with an unrelated message", () => {
  // Closes the same mutant from the other side: with `||`, a 404 status
  // alone would be enough, regardless of what the message actually says.
  assert.equal(describeProgressError({ status: 404, message: "boom" }, { topicId: "ai-103" }), "boom");
});

// --- The ordinal ladder ------------------------------------------------
//
// Colour is the one thing a string test cannot see, so what these pin is the
// `data-level` hook the stylesheet hangs each rung on, and the label that
// keeps the meaning from resting on colour at all.

test("every level row carries its own level as a styling hook", () => {
  const html = levelBreakdownView({ UNASSESSED: 1, WEAK: 2, MASTERED: 3 });
  for (const level of LEVEL_ORDER) {
    assert.ok(html.includes(`data-level="${level}"`), `${level} lost its hook`);
  }
});

test("a level row names its level in Spanish, so colour is never the only carrier", () => {
  const html = levelBreakdownView({ MASTERED: 3 });
  assert.ok(html.includes("Dominado"));
});

test("levelMixView drops the levels with no objectives instead of painting zero-width segments", () => {
  const html = levelMixView({ UNASSESSED: 3, WEAK: 0, MASTERED: 1 }, 4);
  assert.ok(html.includes('data-level="UNASSESSED"'));
  assert.ok(html.includes('data-level="MASTERED"'));
  assert.equal(html.includes('data-level="WEAK"'), false);
});

test("levelMixView sizes each segment against the response's total, not the sum", () => {
  // A level this front end has not been taught yet must leave its share
  // unpainted rather than inflate the others to fill the bar.
  const html = levelMixView({ WEAK: 5 }, 10);
  assert.ok(html.includes("width:50.00%"));
});

test("levelMixView labels the bar for a reader who cannot see the colours", () => {
  const html = levelMixView({ WEAK: 2, MASTERED: 1 }, 3);
  assert.ok(html.includes('role="img"'));
  assert.ok(html.includes("Débil: 2"));
  assert.ok(html.includes("Dominado: 1"));
});

test("levelMixView renders nothing for a topic with no objectives", () => {
  assert.equal(levelMixView({}, 0), "");
  assert.equal(levelMixView(null, undefined), "");
});

test("coverageHeroView shows the engine's own coverage as a percentage", () => {
  const html = coverageHeroView({ coverage: 0.1875, assessed_objectives: 12, total_objectives: 64 });
  assert.ok(html.includes(">19<"));
  assert.ok(html.includes("12 de 64"));
});

test("coverageHeroView reads zero coverage as 0%, never as a blank", () => {
  const html = coverageHeroView({ coverage: 0, assessed_objectives: 0, total_objectives: 64 });
  assert.ok(html.includes(">0<"));
});

test("summaryTilesView copies the response's counts rather than deriving them", () => {
  const html = summaryTilesView({
    total_attempts: 118,
    due_objectives: 8,
    unstarted_objectives: 52,
  });
  for (const value of [">118<", ">8<", ">52<"]) {
    assert.ok(html.includes(value), `${value} missing`);
  }
});

test("summaryTilesView shows a missing count as zero instead of undefined", () => {
  const html = summaryTilesView({});
  assert.equal(html.includes("undefined"), false);
  assert.ok(html.includes(">0<"));
});

test("objectiveRowView carries its level as a styling hook too", () => {
  const html = objectiveRowView({ objective_id: "o1", level: "COMPETENT" }, "Title");
  assert.ok(html.includes('data-level="COMPETENT"'));
});
