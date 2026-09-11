// Unit tests for webui/js/practice-keys.js: the keyboard contract ACU-267
// exists to serve ("a number picks an option, Enter confirms"). Every case
// pins both a positive (the key does the thing) and a negative (the same
// key does nothing in the wrong phase) so a mutant that drops the phase
// check cannot pass silently.

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveKeyAction, isAlreadyRecorded, makeAttemptId } from "../../webui/js/practice-keys.js";

test("a digit within range selects that option while answering", () => {
  assert.deepEqual(resolveKeyAction("1", { phase: "answering", optionCount: 3 }), {
    type: "select",
    index: 0,
  });
  assert.deepEqual(resolveKeyAction("3", { phase: "answering", optionCount: 3 }), {
    type: "select",
    index: 2,
  });
});

test("a digit outside the option range is ignored", () => {
  assert.equal(resolveKeyAction("4", { phase: "answering", optionCount: 3 }), null);
  assert.equal(resolveKeyAction("0", { phase: "answering", optionCount: 3 }), null);
});

test("a non-numeric key other than Enter is ignored while answering", () => {
  assert.equal(resolveKeyAction("a", { phase: "answering", optionCount: 3 }), null);
});

test("Enter submits while answering", () => {
  assert.deepEqual(resolveKeyAction("Enter", { phase: "answering", optionCount: 3 }), {
    type: "submit",
  });
});

test("Enter advances to the next question once feedback is shown", () => {
  assert.deepEqual(resolveKeyAction("Enter", { phase: "feedback", optionCount: 3 }), {
    type: "next",
  });
});

test("a digit does nothing once feedback is shown - the question is already answered", () => {
  assert.equal(resolveKeyAction("1", { phase: "feedback", optionCount: 3 }), null);
});

test("Enter is ignored while a request is in flight, so mashing it cannot double-submit", () => {
  assert.equal(resolveKeyAction("Enter", { phase: "submitting", optionCount: 3 }), null);
  assert.equal(resolveKeyAction("Enter", { phase: "loading", optionCount: 3 }), null);
});

test("a digit is ignored while a request is in flight", () => {
  assert.equal(resolveKeyAction("1", { phase: "submitting", optionCount: 3 }), null);
});

test("a modifier combination is refused even where the bare key would act (review round 1)", () => {
  const base = { optionCount: 3, hasModifier: true };
  assert.equal(resolveKeyAction("1", { ...base, phase: "answering" }), null);
  assert.equal(resolveKeyAction("Enter", { ...base, phase: "answering" }), null);
  assert.equal(resolveKeyAction("Enter", { ...base, phase: "feedback" }), null);
});

test("isAlreadyRecorded is true only for a 409, not neighbouring statuses", () => {
  assert.equal(isAlreadyRecorded({ status: 409 }), true);
  assert.equal(isAlreadyRecorded({ status: 410 }), false);
  assert.equal(isAlreadyRecorded({ status: 408 }), false);
  assert.equal(isAlreadyRecorded(null), false);
});

test("makeAttemptId uses the injected randomUUID when available", () => {
  assert.equal(makeAttemptId(() => "fixed-id"), "fixed-id");
});

test("makeAttemptId falls back to a unique-enough id when randomUUID is unavailable", () => {
  const first = makeAttemptId(undefined);
  const second = makeAttemptId(undefined);
  assert.equal(typeof first, "string");
  assert.notEqual(first, second);
});
