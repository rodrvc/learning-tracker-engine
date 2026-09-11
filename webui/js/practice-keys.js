"use strict";

// Pure mapping from a keydown event's `key` to a practice action (ACU-267:
// "a number picks an option, Enter confirms" is the primary path this view
// exists for). Kept DOM-free, the same reasoning as router.js and
// format.js, so the keyboard contract is unit-testable without a
// KeyboardEvent or a browser: views/practice.js wires the result to
// `addEventListener("keydown", ...)` and to a click handler that produces
// the identical action for the mouse path.
//
// `phase` is the caller's own state machine, not read from the DOM, which
// is what makes Enter a no-op while a request is in flight (phase
// "submitting"/"loading") even though nothing there is disabled - a
// disabled button does not stop a keydown handler from firing.
export function resolveKeyAction(key, { phase, optionCount }) {
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
