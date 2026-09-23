// Unit tests for webui/js/practice-scope.js - what the ticked rows of the
// practice tree mean for the scoped practice endpoint (issue #49, several
// rows at once in issue #62). Run by test_webui_router.py.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  describeScopedUnavailable,
  dueActionLabel,
  emptySelection,
  practicingLabel,
  rowState,
  selectedActionLabel,
  selectionLabel,
  selectionQuery,
  selectionSize,
  toggleRow,
} from "../../webui/js/practice-scope.js";

const goalRow = { kind: "goal", topicId: "ai-103", goalLabel: "AI-103", label: "AI-103" };
const d3Row = { ...goalRow, kind: "unit", domain: "D3", label: "D3 - Visión" };
const d4Row = { ...goalRow, kind: "unit", domain: "D4", label: "D4 - Lenguaje y voz" };
const objectiveRow = {
  ...goalRow,
  kind: "topic",
  domain: "D3",
  objectiveId: "D3.2.a",
  label: "D3.2.a - Analizar imágenes",
};

// The goal as the tree reports it, which is what lets a ticked parent be
// expanded into its children. Only D3 is spelled out in full; the rest are
// there so "every unit is ticked" is a question with an answer.
const shape = {
  ungrouped: false,
  units: [
    { code: "D3", label: "D3 - Visión", objectives: [
      { id: "D3.2.a", label: "D3.2.a - Analizar imágenes" },
      { id: "D3.2.b", label: "D3.2.b - Leer documentos" },
    ] },
    { code: "D4", label: "D4 - Lenguaje y voz", objectives: [{ id: "D4.1.a", label: "D4.1.a - Hablar" }] },
    { code: "D5", label: "D5 - Recuperación", objectives: [
      { id: "D5.1.a", label: "D5.1.a - Indexar" },
      { id: "D5.1.b", label: "D5.1.b - Enriquecer" },
    ] },
  ],
};
const d3bRow = { ...objectiveRow, objectiveId: "D3.2.b", label: "D3.2.b - Leer documentos" };
const d4aRow = { ...objectiveRow, domain: "D4", objectiveId: "D4.1.a", label: "D4.1.a - Hablar" };
const d5aRow = { ...objectiveRow, domain: "D5", objectiveId: "D5.1.a", label: "D5.1.a - Indexar" };
const d5Row = { ...goalRow, kind: "unit", domain: "D5", label: "D5 - Recuperación" };

const goal = emptySelection("ai-103", "AI-103");
const unit = toggleRow(null, d3Row);
const objective = toggleRow(null, objectiveRow);
const mixed = toggleRow(toggleRow(unit, d4Row, shape), d5aRow, shape);

// The goal is the *empty* selection, not an item: "practise this goal" is
// the unscoped call, and a second spelling of it could disagree with the
// first.
test("the goal is a selection with nothing narrowed", () => {
  assert.deepEqual(goal, { topicId: "ai-103", goalLabel: "AI-103", items: [] });
  assert.equal(selectionSize(goal), 0);
  assert.equal(selectionSize(mixed), 3);
});

// The rows that cannot be ticked: the "Sin unidad" bucket (no domain to ask
// by) and anything without a goal to ask within.
test("a row with nothing to scope by leaves the selection alone", () => {
  assert.equal(toggleRow(goal, { ...d3Row, domain: null }), goal);
  assert.equal(toggleRow(goal, { ...objectiveRow, objectiveId: null }), goal);
  assert.equal(toggleRow(goal, { ...d3Row, kind: "whatever" }), goal);
  assert.equal(toggleRow(null, { ...d3Row, topicId: null }), null);
  assert.equal(emptySelection(null, "AI-103"), null);
});

test("ticking a row adds it, ticking it again removes it", () => {
  assert.deepEqual(unit.items, [{ kind: "unit", value: "D3", label: "D3 - Visión" }]);
  // To `null`, never to the empty list: the empty list is the whole goal,
  // so a selection that emptied into it would practise more than was ticked.
  assert.equal(toggleRow(unit, d3Row), null);
  assert.equal(selectionSize(toggleRow(mixed, d4Row)), 2);
});

// Whole units and single objectives of *other* units mix freely: the
// endpoint unions them. What no longer mixes is a unit with one of its own
// objectives - that pair said the same thing twice, and under the cascade
// the objective is already ticked, so pressing it means "not that one".
test("units and objectives of other units mix, in one goal", () => {
  assert.deepEqual(
    mixed.items.map((item) => [item.kind, item.value]),
    [
      ["unit", "D3"],
      ["unit", "D4"],
      ["topic", "D5.1.a"],
    ],
  );
  assert.equal(selectionSize(toggleRow(mixed, objectiveRow, shape)), 3);
  assert.equal(rowState(toggleRow(mixed, objectiveRow, shape), objectiveRow, shape), "off");
});

// Ticking the goal is the way back to "the engine chooses", so it clears
// what was ticked instead of adding a contradiction to it. From partly
// ticked it goes fully on, which is the move every file tree makes.
test("ticking the goal drops every finer row", () => {
  assert.deepEqual(toggleRow(mixed, goalRow), goal);
  assert.equal(rowState(goal, goalRow), "on");
  assert.equal(rowState(mixed, goalRow), "partial");
  assert.equal(rowState(mixed, d4Row), "on");
  assert.equal(rowState(unit, d4Row), "off");
  // And unticking it leaves nothing at all, not the whole goal again.
  assert.equal(toggleRow(goal, goalRow), null);
});

// --- The cascade (issue #71 follow-up) ---

// The bug this exists to stop: a ticked goal that left every unit and every
// objective drawn empty, which to a person reads as nothing having happened.
test("a ticked parent shows every row beneath it ticked", () => {
  assert.equal(rowState(goal, d3Row, shape), "on");
  assert.equal(rowState(goal, objectiveRow, shape), "on");
  // A unit covers its own objectives the same way.
  assert.equal(rowState(unit, objectiveRow, shape), "on");
  assert.equal(rowState(unit, d4aRow, shape), "off");
  // A leaf has nothing under it, so it is never partly anything.
  assert.equal(rowState(objective, objectiveRow, shape), "on");
});

// Three states, because a parent some of whose children are ticked is
// neither: ticked it would claim the others, empty it would hide these.
test("a parent only partly ticked is indeterminate", () => {
  assert.equal(rowState(objective, d3Row, shape), "partial");
  assert.equal(rowState(objective, goalRow, shape), "partial");
  // Without the shape a unit cannot know whose objectives those are, so it
  // reports the one thing it can be sure of.
  assert.equal(rowState(objective, d3Row), "off");
});

// The case that decides the model: "the whole goal minus D3" is not any
// empty list, so the goal is expanded into the units it stood for.
test("unticking one child of a ticked parent keeps its siblings", () => {
  const minusD3 = toggleRow(goal, d3Row, shape);
  assert.deepEqual(minusD3.items.map((item) => item.value), ["D4", "D5"]);
  assert.equal(rowState(minusD3, d4Row, shape), "on");
  assert.equal(rowState(minusD3, d3Row, shape), "off");
  assert.equal(rowState(minusD3, goalRow, shape), "partial");
  // And the same one level down: the unit becomes its own objectives.
  const minusOne = toggleRow(unit, objectiveRow, shape);
  assert.deepEqual(minusOne.items.map((item) => item.value), ["D3.2.b"]);
  assert.equal(rowState(minusOne, d3bRow, shape), "on");
  assert.equal(rowState(minusOne, d3Row, shape), "partial");
});

// Putting the last child back has to give the parent's own spelling again,
// or the same set would have two forms and the goal would stay drawn
// `partial` with every one of its units ticked.
test("ticking the children back collapses them into the parent", () => {
  const rebuilt = toggleRow(toggleRow(unit, objectiveRow, shape), objectiveRow, shape);
  assert.deepEqual(rebuilt, unit);
  // Every unit ticked one at a time is the goal, and therefore the unscoped
  // call: this is where the cascade and the query are kept in agreement.
  const twoUnits = toggleRow(toggleRow(null, d3Row, shape), d4Row, shape);
  const everyUnit = toggleRow(twoUnits, d5Row, shape);
  assert.deepEqual(everyUnit.items, []);
  assert.equal(selectionQuery(everyUnit), "");
  assert.equal(rowState(everyUnit, goalRow, shape), "on");
  // Same by objective: D4 holds one, so ticking it completes D4, and with
  // D3 and D5 already ticked that completes the goal.
  const byObjective = toggleRow(toggleRow(toggleRow(null, d3Row, shape), d5Row, shape), d4aRow, shape);
  assert.deepEqual(byObjective.items, []);
});

// Collapsing to "the whole goal" is only honest when every objective can be
// named by a unit. A goal with objectives filed under none would be widened
// by it, and a shape that knows of no unit at all would be invented.
test("a goal with unnameable objectives never collapses into the whole goal", () => {
  const ungrouped = { ...shape, ungrouped: true };
  const two = toggleRow(toggleRow(null, d3Row, ungrouped), d4Row, ungrouped);
  const everyUnit = toggleRow(two, d5Row, ungrouped);
  assert.deepEqual(everyUnit.items.map((item) => item.value), ["D3", "D4", "D5"]);
  assert.equal(rowState(everyUnit, goalRow, ungrouped), "partial");
  assert.deepEqual(toggleRow(null, d3Row, {}).items.map((item) => item.value), ["D3"]);
});

// A goal ticked while it is still folded has no shape to expand, and must
// not need one: what is under it is covered by coverage, not by a list.
test("a goal ticked before its units have loaded still covers them", () => {
  const blind = toggleRow(null, goalRow, { units: [], ungrouped: false });
  assert.deepEqual(blind.items, []);
  assert.equal(rowState(blind, d3Row, shape), "on");
  assert.equal(rowState(blind, objectiveRow, shape), "on");
});

// Ticking a unit whose objectives were ticked one by one leaves the unit
// alone, not the unit plus the objectives it already contains.
test("ticking a parent absorbs the children already ticked", () => {
  const absorbed = toggleRow(objective, d3Row, shape);
  assert.deepEqual(absorbed.items, [{ kind: "unit", value: "D3", label: "D3 - Visión" }]);
});

// One endpoint per topic (`/topics/{id}/practice/next`), so a selection
// across two goals is not a request that can be made.
test("a row in another goal starts that goal's selection", () => {
  const elsewhere = toggleRow(mixed, {
    kind: "unit",
    topicId: "other",
    goalLabel: "Otra meta",
    domain: "D1",
    label: "D1 - Algo",
  });
  assert.equal(elsewhere.topicId, "other");
  assert.equal(selectionSize(elsewhere), 1);
  assert.equal(rowState(elsewhere, d3Row), "off");
});

test("the query repeats a parameter per ticked row, encoded, domains first", () => {
  assert.equal(selectionQuery(unit), "?domain=D3");
  assert.equal(selectionQuery(objective), "?objective_id=D3.2.a");
  assert.equal(selectionQuery(mixed), "?domain=D3&domain=D4&objective_id=D5.1.a");
  assert.equal(selectionQuery(goal), "");
  assert.equal(selectionQuery(null), "");
  const odd = toggleRow(null, { ...d3Row, topicId: "t", domain: "D&3 x" });
  assert.equal(selectionQuery(odd), "?domain=D%263%20x");
});

// The selection's action is a second button, never the first one relabelled:
// it says "lo marcado" where the default says "lo que toca", so the
// suggested path cannot be mistaken for the selection's (issue #71).
test("the selection's action names what is marked, and nothing marked has none", () => {
  assert.equal(selectedActionLabel(unit), "Practicar lo marcado (D3 - Visión)");
  assert.equal(selectedActionLabel(mixed), "Practicar lo marcado (2 unidades y 1 objetivo)");
  // The goal ticked is the one case with nothing narrowed. It is named by the
  // goal, not by "lo que toca en AI-103": that is the other button's
  // sentence, and the two may not read as the same offer.
  assert.equal(selectedActionLabel(goal), "Practicar lo marcado (AI-103)");
  assert.doesNotMatch(selectedActionLabel(goal), /lo que toca/);
  // Nothing selected, nothing to label: the button is not on screen at all.
  assert.equal(selectedActionLabel(null), null);
  assert.equal(practicingLabel(objective), "Practicando D3.2.a - Analizar imágenes");
  assert.equal(practicingLabel(goal), "Practicando lo que toca en AI-103");
});

// Counted, never a list cut off at the width of the screen: a person can
// check "2 unidades y 1 objetivo" against what they ticked.
// The default action of the whole screen (issue #69): the backlog's size is
// on the button, so nobody has to open the tree to find out how much there
// is. Zero is printed rather than hidden - and does not disable it, because
// never-practised objectives are not due and the endpoint serves them too.
test("the default action carries the engine's due count", () => {
  assert.equal(dueActionLabel(8), "Practicar lo que toca (8)");
  assert.equal(dueActionLabel(0), "Practicar lo que toca (0)");
  // No count known (a summary that failed) drops the number instead of
  // printing a zero that would read as "nothing to do".
  assert.equal(dueActionLabel(null), "Practicar lo que toca");
  assert.equal(dueActionLabel(undefined), "Practicar lo que toca");
  // The goal is named only when there is more than one to confuse it with,
  // which is the caller's call: several goals, and the button has to say
  // which syllabus it would drill.
  assert.equal(dueActionLabel(3, "AI-103"), "Practicar lo que toca en AI-103 (3)");
});

test("a selection of several is named by how many of each it holds", () => {
  assert.equal(selectionLabel(mixed), "2 unidades y 1 objetivo");
  assert.equal(practicingLabel(mixed), "Practicando 2 unidades y 1 objetivo");
  assert.equal(selectionLabel(toggleRow(objective, { ...objectiveRow, objectiveId: "D3.3.a" })), "2 objetivos");
  assert.equal(selectionLabel(toggleRow(unit, d4Row)), "2 unidades");
});

// The three scoped 404s (web/routers/practice.py) are three different
// pieces of news, and the one that matters most is "no hay preguntas" vs
// "no queda nada pendiente": the first is a content gap, the second is
// being up to date.
test("each scoped 404 gets its own honest message", () => {
  const notFound = (detail) => ({ status: 404, message: detail });
  assert.match(
    describeScopedUnavailable(notFound("topic ai-103 has no objective matching domain D3"), {
      selection: unit,
    }),
    /Ya no hay objetivos en D3 - Visión\./,
  );
  assert.match(
    describeScopedUnavailable(
      notFound("topic ai-103 has no question for any due or unstarted objective matching domain D3: D3.1.a"),
      { selection: unit },
    ),
    /Todavía no hay preguntas para lo pendiente en D3 - Visión\./,
  );
  assert.match(
    describeScopedUnavailable(
      notFound("nothing to study in topic ai-103 matching domain D3: no objective is due or unstarted"),
      { selection: unit },
    ),
    /Ya no queda nada pendiente en D3 - Visión\./,
  );
});

// Several ticked rows are "lo que elegiste" in the news, not their count:
// the sentence is about what happened, and arithmetic in the middle of it
// makes it slower to read, not more precise.
test("a selection of several is spoken of as what was chosen", () => {
  assert.equal(
    describeScopedUnavailable(
      { status: 404, message: "topic ai-103 has no objective matching 2 domains and 1 objective" },
      { selection: mixed },
    ),
    "Ya no hay objetivos en lo que elegiste.",
  );
});

// Not a 404 - a 500 or an outage - is shown as the backend said it, the
// same rule format.js already follows: a friendlier guess would hide it.
test("anything that is not a scoped 404 is shown unchanged", () => {
  assert.equal(
    describeScopedUnavailable({ status: 500, message: "boom" }, { selection: unit }),
    "boom",
  );
  assert.equal(describeScopedUnavailable(null, { selection: unit }), "Error inesperado.");
});

// The goal, and no selection at all, are the unscoped call - so they keep
// the wording the practice view already had, rather than a second copy of
// it.
test("an unscoped call falls back to the view's existing wording", () => {
  const caughtUp = { status: 404, message: "nothing to study in topic ai-103: no objective is due or unstarted" };
  assert.equal(
    describeScopedUnavailable(caughtUp, { selection: goal, objectiveCount: 64 }),
    "No hay nada vencido por ahora.",
  );
  assert.match(
    describeScopedUnavailable(caughtUp, { selection: goal, objectiveCount: 0 }),
    /subí material y generá preguntas/,
  );
});
