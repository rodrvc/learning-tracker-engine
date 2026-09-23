// Unit tests for webui/js/practice-scope.js - what the ticked rows of the
// practice tree mean for the scoped practice endpoint (issue #49, several
// rows at once in issue #62). Run by test_webui_router.py.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  describeScopedUnavailable,
  emptySelection,
  isRowSelected,
  practiceButtonLabel,
  practicingLabel,
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

const goal = emptySelection("ai-103", "AI-103");
const unit = toggleRow(goal, d3Row);
const objective = toggleRow(goal, objectiveRow);
const mixed = toggleRow(toggleRow(unit, d4Row), objectiveRow);

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
  // Back to the goal, never to `null`: the action button has to keep
  // offering "lo que toca" instead of going dead.
  assert.deepEqual(toggleRow(unit, d3Row), goal);
  assert.equal(selectionSize(toggleRow(mixed, d4Row)), 2);
});

// A unit and one of its own objectives may be ticked together: the endpoint
// unions them, so the pair is legal and says "this unit, and be sure to
// include that objective" rather than contradicting itself.
test("units and objectives mix, in one goal", () => {
  assert.deepEqual(
    mixed.items.map((item) => [item.kind, item.value]),
    [
      ["unit", "D3"],
      ["unit", "D4"],
      ["topic", "D3.2.a"],
    ],
  );
});

// Ticking the goal is the way back to "the engine chooses", so it clears
// what was ticked instead of adding a contradiction to it.
test("ticking the goal drops every finer row", () => {
  assert.deepEqual(toggleRow(mixed, goalRow), goal);
  assert.ok(isRowSelected(goal, goalRow));
  assert.ok(!isRowSelected(mixed, goalRow));
  assert.ok(isRowSelected(mixed, d4Row));
  assert.ok(!isRowSelected(unit, d4Row));
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
  assert.ok(!isRowSelected(elsewhere, d3Row));
});

test("the query repeats a parameter per ticked row, encoded, domains first", () => {
  assert.equal(selectionQuery(unit), "?domain=D3");
  assert.equal(selectionQuery(objective), "?objective_id=D3.2.a");
  assert.equal(selectionQuery(mixed), "?domain=D3&domain=D4&objective_id=D3.2.a");
  assert.equal(selectionQuery(goal), "");
  assert.equal(selectionQuery(null), "");
  const odd = toggleRow(emptySelection("t", "T"), { ...d3Row, topicId: "t", domain: "D&3 x" });
  assert.equal(selectionQuery(odd), "?domain=D%263%20x");
});

// The button has to say whose choice the questions are: with the goal ticked
// the engine decides - and that is not obvious from a button reading only
// "Practicar AI-103".
test("the button says when the engine is the one choosing", () => {
  assert.equal(practiceButtonLabel(goal), "Practicar lo que toca en AI-103");
  assert.equal(practiceButtonLabel(unit), "Practicar D3 - Visión");
  assert.match(practiceButtonLabel(null), /Elegí una meta/);
  assert.equal(practicingLabel(objective), "Practicando D3.2.a - Analizar imágenes");
  assert.equal(practicingLabel(goal), "Practicando lo que toca en AI-103");
});

// Counted, never a list cut off at the width of the screen: a person can
// check "2 unidades y 1 objetivo" against what they ticked.
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
