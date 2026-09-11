// Unit tests for webui/js/practice-keys.js: the keyboard contract ACU-267
// exists to serve ("a number picks an option, Enter confirms"). Every case
// pins both a positive (the key does the thing) and a negative (the same
// key does nothing in the wrong phase) so a mutant that drops the phase
// check cannot pass silently.

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveKeyAction } from "../../webui/js/practice-keys.js";

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
