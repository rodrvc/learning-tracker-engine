// Unit tests for webui/js/practice-scope.js - what a picked row means for
// the scoped practice endpoint (issue #49). Run by test_webui_router.py.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  describeScopedUnavailable,
  practiceButtonLabel,
  practicingLabel,
  sameScope,
  scopeFromPick,
  scopeQuery,
} from "../../webui/js/practice-scope.js";

const goal = scopeFromPick("goal", { topicId: "ai-103", label: "AI-103" });
const unit = scopeFromPick("unit", { topicId: "ai-103", domain: "D3", label: "D3 - Visión" });
const objective = scopeFromPick("topic", {
  topicId: "ai-103",
  objectiveId: "D3.2.a",
  label: "D3.2.a - Analizar imágenes",
});

test("a scope carries one narrowing field at most, never two", () => {
  assert.deepEqual(
    [goal.domain, goal.objectiveId, unit.objectiveId, objective.domain],
    [null, null, null, null],
  );
  assert.deepEqual([unit.domain, objective.objectiveId], ["D3", "D3.2.a"]);
});

// The rows that cannot be scoped: the "Sin unidad" bucket (no domain to ask
// by) and anything without a goal to ask within.
test("a row with nothing to scope by yields no scope at all", () => {
  assert.equal(scopeFromPick("unit", { topicId: "ai-103", domain: null }), null);
  assert.equal(scopeFromPick("topic", { topicId: "ai-103", objectiveId: null }), null);
  assert.equal(scopeFromPick("goal", { topicId: null }), null);
  assert.equal(scopeFromPick("whatever", { topicId: "ai-103" }), null);
});

test("the query narrows for a unit and a topic, and for nothing else", () => {
  assert.equal(scopeQuery(unit), "?domain=D3");
  assert.equal(scopeQuery(objective), "?objective_id=D3.2.a");
  assert.equal(scopeQuery(goal), "");
  assert.equal(scopeQuery(null), "");
  const odd = scopeFromPick("unit", { topicId: "t", domain: "D&3 x" });
  assert.equal(scopeQuery(odd), "?domain=D%263%20x");
});

test("scopes compare by what they select, not by identity", () => {
  assert.ok(sameScope(unit, { ...unit }));
  assert.ok(!sameScope(unit, objective));
  assert.ok(!sameScope(unit, { ...unit, domain: "D4" }));
  assert.ok(!sameScope(unit, null));
  assert.ok(sameScope(null, null));
});

// The button has to say whose choice the questions are: with a goal (or
// nothing) picked, the engine decides - and that is not obvious from a
// button reading only "Practicar AI-103".
test("the button says when the engine is the one choosing", () => {
  assert.equal(practiceButtonLabel(goal), "Practicar lo que toca en AI-103");
  assert.equal(practiceButtonLabel(unit), "Practicar D3 - Visión");
  assert.match(practiceButtonLabel(null), /Elegí una meta/);
  assert.equal(practicingLabel(objective), "Practicando D3.2.a - Analizar imágenes");
  assert.equal(practicingLabel(goal), "Practicando lo que toca en AI-103");
});

// The three scoped 404s (web/routers/practice.py) are three different
// pieces of news, and the one that matters most is "no hay preguntas" vs
// "no queda nada pendiente": the first is a content gap, the second is
// being up to date.
test("each scoped 404 gets its own honest message", () => {
  const notFound = (detail) => ({ status: 404, message: detail });
  assert.match(
    describeScopedUnavailable(notFound("topic ai-103 has no objective matching domain D3"), {
      scope: unit,
    }),
    /Ya no hay objetivos en D3 - Visión\./,
  );
  assert.match(
    describeScopedUnavailable(
      notFound("topic ai-103 has no question for any due or unstarted objective matching domain D3: D3.1.a"),
      { scope: unit },
    ),
    /Todavía no hay preguntas para lo pendiente en D3 - Visión\./,
  );
  assert.match(
    describeScopedUnavailable(
      notFound("nothing to study in topic ai-103 matching domain D3: no objective is due or unstarted"),
      { scope: unit },
    ),
    /Ya no queda nada pendiente en D3 - Visión\./,
  );
});

// Not a 404 - a 500 or an outage - is shown as the backend said it, the
// same rule format.js already follows: a friendlier guess would hide it.
test("anything that is not a scoped 404 is shown unchanged", () => {
  assert.equal(describeScopedUnavailable({ status: 500, message: "boom" }, { scope: unit }), "boom");
  assert.equal(describeScopedUnavailable(null, { scope: unit }), "Error inesperado.");
});

// A goal, and no selection at all, are the unscoped call - so they keep the
// wording the practice view already had, rather than a second copy of it.
test("an unscoped call falls back to the view's existing wording", () => {
  const caughtUp = { status: 404, message: "nothing to study in topic ai-103: no objective is due or unstarted" };
  assert.equal(
    describeScopedUnavailable(caughtUp, { scope: goal, objectiveCount: 64 }),
    "No hay nada vencido por ahora.",
  );
  assert.match(
    describeScopedUnavailable(caughtUp, { scope: goal, objectiveCount: 0 }),
    /subí material y generá preguntas/,
  );
});
