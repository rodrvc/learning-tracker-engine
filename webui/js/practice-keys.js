"use strict";

// The practice view's DOM-free logic (ACU-267): keydown-to-action mapping,
// plus two classifications review round 1 pulled out of the DOM wiring, out
// of mutation testing's reach. Same reasoning as router.js/format.js:
// testable without a KeyboardEvent or a browser. views/practice.js wires
// `resolveKeyAction`'s result to a keydown listener and to click handlers
// that produce the identical action for the mouse path.
//
// `phase` gates Enter/digits while a request is in flight, even though
// nothing is disabled then. `hasModifier` bails unconditionally, so a
// Cmd/Ctrl/Alt shortcut on `document` reaches the browser untouched.
export function resolveKeyAction(key, { phase, optionCount, hasModifier = false }) {
  if (hasModifier) return null;
  if (phase === "answering") {
    const index = Number(key) - 1;
    if (Number.isInteger(index) && index >= 0 && index < optionCount) {
      return { type: "select", index };
    }
    if (key === "Enter") return { type: "submit" };
    return null;
  }
  if (phase === "feedback" && key === "Enter") return { type: "next" };
  return null;
}

// Whether an answer failure means the attempt is already recorded (SPEC
// C9), not that something broke - one of the three non-negotiable rules,
// so pure and tested here, not buried where a 409-to-410 mutant survives.
export function isAlreadyRecorded(err) {
  return Boolean(err) && err.status === 409;
}

// `crypto.randomUUID` needs a secure context; plain HTTP off localhost
// leaves it undefined, and the resulting TypeError used to fail the whole
// view with no readable message. Takes the generator as a bound function,
// not a boolean, so the caller does the one-line feature check and this
// stays pure: "have a generator or don't."
export function makeAttemptId(randomUUID) {
  if (typeof randomUUID === "function") return randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
