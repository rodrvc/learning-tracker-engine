// Unit tests for webui/js/tree.js - the Goal > Unit > Topic grouping and the
// markup it produces (issue #49). Run by test_webui_router.py.

import { test } from "node:test";
import assert from "node:assert/strict";
import { buildTree, unitName, unitsView, treeView, UNGROUPED_UNIT_NAME } from "../../webui/js/tree.js";

const topic = {
  topic_id: "ai-103-oficial",
  name: "AI-103",
  objectives: [
    { objective_id: "D2.1.a", title: "Desplegar modelos", domain: "D2", has_questions: true },
    { objective_id: "D1.1.a", title: "Elegir un modelo", domain: "D1", has_questions: true },
    { objective_id: "D1.2.a", title: "Diseñar la infra", domain: "D1", has_questions: false },
    { objective_id: "loose", title: "Sin dominio", domain: null, has_questions: false },
  ],
};
const summary = { assessed_objectives: 2, total_objectives: 4, coverage: 0.5 };
const states = [
  { objective_id: "D1.1.a", level: "MASTERED", is_due: false },
  { objective_id: "D1.2.a", level: "WEAK", is_due: true },
  { objective_id: "D2.1.a", level: "UNASSESSED", is_due: false },
];

test("units come out in code order, with the unnamed bucket last", () => {
  const model = buildTree(topic, states, summary);
  assert.deepEqual(model.units.map((unit) => unit.code), ["D1", "D2", null]);
  assert.equal(model.units[2].name, UNGROUPED_UNIT_NAME);
});

test("a topic carries the level and the due flag the engine reported", () => {
  const [first, second] = buildTree(topic, states, summary).units[0].topics;
  assert.deepEqual([first.level, first.isDue], ["MASTERED", false]);
  assert.deepEqual([second.level, second.isDue], ["WEAK", true]);
});

// The rule this repo cares about most: nothing here is derived from
// attempts. An objective the states call did not mention is UNASSESSED and
// not due - what the engine reports for one with no attempt - not a guess.
test("an objective with no state shows as unassessed, never as missing", () => {
  const units = buildTree(topic, [], summary).units;
  assert.deepEqual(units[0].topics.map((t) => [t.level, t.isDue]), [
    ["UNASSESSED", false],
    ["UNASSESSED", false],
  ]);
});

// A unit's bar counts the levels the engine assigned; the goal's is the
// summary's own coverage, not a recount of the same rows.
test("bars count the engine's levels and reuse its coverage", () => {
  const model = buildTree(topic, states, summary);
  assert.deepEqual(model.units[0].progress, { assessed: 2, total: 2, ratio: 1 });
  assert.deepEqual(model.units[1].progress, { assessed: 0, total: 1, ratio: 0 });
  assert.deepEqual(model.progress, { assessed: 2, total: 4, ratio: 0.5 });
  assert.equal(buildTree(topic, states, null).progress, null);
});

test("a domain with no name shows its raw code, and an empty goal says so", () => {
  assert.equal(unitName("D3"), "Visión");
  assert.equal(unitName("D9"), "D9");
  assert.equal(unitName(null), UNGROUPED_UNIT_NAME);
  assert.deepEqual(buildTree({ ...topic, objectives: [] }, [], summary).units, []);
  assert.match(unitsView([]), /Todavía no tiene objetivos/);
});

// The attributes the controls are resolved through, so the view can rely on
// them instead of on this file staying unchanged by luck.
test("every row carries its scope, its identifier and its state", () => {
  const html = treeView(buildTree(topic, states, summary));
  assert.match(html, /data-scope="goal" data-topic-id="ai-103-oficial"/);
  assert.match(html, /data-goal-label="AI-103"/);
  assert.match(html, /data-scope="unit" data-domain="D1"/);
  assert.match(html, /data-scope="topic" data-objective-id="D1\.2\.a" data-has-questions="false"/);
  assert.match(html, /data-has-questions="true"/);
  // The fallback bucket has no domain to scope a practice call by, so it
  // must not claim one.
  assert.doesNotMatch(html, /data-domain="null"/);
  assert.equal(html.match(/due-marker/g).length, 1);
  assert.match(html, /Débil/);
});

// --- One checkbox per selectable row (issue #71) ---

// There is no mode to ask for a control any more: the per-row "Practicar"
// button and the "Elegir varios" toggle were two mechanisms for one idea, so
// the tree renders one control, on every selectable row, always.
test("every selectable row carries a checkbox, labelled in Spanish", () => {
  const html = treeView(buildTree(topic, states, summary));
  assert.match(html, /data-pick="goal"\s+data-pick-label="AI-103"/);
  assert.match(html, /data-pick="unit"\s+data-pick-label="D1 - Planificar/);
  assert.match(html, /data-pick="topic"\s+data-pick-label="D1\.1\.a - Elegir un modelo"/);
  // Goal, D1, D2 and the two objectives with a question - not the "Sin
  // unidad" bucket nor the objective with none: both would promise a 404.
  assert.equal(html.match(/type="checkbox"/g).length, 5);
  // Nothing starts ticked: the view marks what is selected itself, since a
  // selection outlives the markup a re-render throws away.
  assert.doesNotMatch(html, /checked/);
  // And no practice control on any row: rows select, the two actions above
  // the tree practise.
  assert.doesNotMatch(html, /data-play|class="play"|>Practicar</);
});

// The two rows that must not be selectable, for the same reason in both
// cases: there is nothing behind them to practise.
test("a topic with no question and the unnamed bucket offer no way to practise them", () => {
  const html = treeView(buildTree(topic, states, summary));
  assert.match(html, /data-objective-id="D1\.2\.a" data-has-questions="false" aria-disabled="true"/);
  assert.match(html, /Sin preguntas/);
  assert.doesNotMatch(html, /data-pick-label="D1\.2\.a/);
  assert.doesNotMatch(html, /data-pick-label="null/);
  // One unit checkbox per named unit (D1, D2), none for "Sin unidad".
  assert.equal(html.match(/data-pick="unit"/g).length, 2);
});

// The checkbox is an addition to the tree, it does not replace it: what a row
// says about where it stands is the reason to tick it.
test("the checkboxes do not displace what a row reports", () => {
  const html = treeView(buildTree(topic, states, summary));
  assert.match(html, /Dominado/);
  assert.match(html, /due-marker/);
  assert.match(html, /bar-count/);
});

test("a name with markup in it is escaped, not interpolated", () => {
  const html = treeView(buildTree({ ...topic, name: "<img src=x>" }, states, summary), {});
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});
