"use strict";

import { describePracticeUnavailable } from "./format.js";

// What "practising a selection" means, kept DOM-free (issue #49, second
// half). Everything the practice tab decides from a picked row - the query
// the scoped endpoint gets, what the action button says, what an empty
// answer means - is decided here, so it is testable without a browser.
//
// **A goal is not a scope.** Selecting the goal row means "practise this
// goal, engine's choice", which is exactly the unscoped call this endpoint
// has always answered, so `scopeQuery` sends nothing for it rather than
// inventing a narrowing the person did not ask for. Only a unit (->
// `domain`) and a topic (-> `objective_id`) narrow the walk, and never
// both: the endpoint answers a request carrying the two with a 400
// (web/routers/practice.py), and the shape below makes sending both
// unrepresentable rather than merely wrong.

/**
 * Turns one pick button's kind and row data into a scope, or `null` when
 * that row cannot be practised.
 *
 * The "Sin unidad" bucket is the null case that matters: it groups
 * objectives that were never filed under a domain, so it has no `domain` to
 * scope by (see tree.js). Returning `null` rather than a scope with an empty
 * domain is what keeps the front end from asking for `?domain=` and getting
 * back the objectives with no domain at all - a different question.
 */
export function scopeFromPick(kind, { topicId, domain, objectiveId, label } = {}) {
  if (!topicId) return null;
  const base = { kind, topicId, domain: null, objectiveId: null, label: label || topicId };
  if (kind === "goal") return base;
  if (kind === "unit") return domain ? { ...base, domain } : null;
  if (kind === "topic") return objectiveId ? { ...base, objectiveId } : null;
  return null;
}

/** Identity by what it selects, not by object reference: the picker
 * re-renders its rows (a goal's units arrive after its first open), so the
 * selected button has to be found again by value every time. */
export function sameScope(left, right) {
  if (!left || !right) return left === right;
  return (
    left.kind === right.kind &&
    left.topicId === right.topicId &&
    left.domain === right.domain &&
    left.objectiveId === right.objectiveId
  );
}

/** The query string for `GET /topics/{id}/practice/next`. Empty for a goal
 * and for no selection alike - both mean "whatever the engine says is
 * next". */
export function scopeQuery(scope) {
  if (!scope) return "";
  if (scope.kind === "topic") return `?objective_id=${encodeURIComponent(scope.objectiveId)}`;
  if (scope.kind === "unit") return `?domain=${encodeURIComponent(scope.domain)}`;
  return "";
}

/** What the action button says, which is the only place the difference
 * between scoped and unscoped is explained to the person: with a goal
 * selected the wording says out loud that the engine is choosing ("lo que
 * toca"), which a button reading "Practicar AI-103" would hide. */
export function practiceButtonLabel(scope) {
  if (!scope) return "Elegí una meta para practicar";
  if (scope.kind === "goal") return `Practicar lo que toca en ${scope.label}`;
  return `Practicar ${scope.label}`;
}

/** The line shown while drilling, so what is being practised is never a
 * guess. A goal says whose choice the questions are. */
export function practicingLabel(scope) {
  if (!scope) return "Practicando lo que toca";
  if (scope.kind === "goal") return `Practicando lo que toca en ${scope.label}`;
  return `Practicando ${scope.label}`;
}

/**
 * Why there is no question, in Spanish, for a scoped call.
 *
 * The endpoint's three 404s (web/routers/practice.py) are three different
 * pieces of news: no objective matching the scope (the selection is empty),
 * no question for any due or unstarted one matching it (there is something
 * to study, the questions do not exist yet), and nothing due or unstarted
 * matching it (caught up here, come back later). The third is ambiguous
 * unscoped - an empty topic reads the same as a finished one, which is why
 * `format.js` needs an objective count to resolve it - but not scoped: an
 * empty scope already failed as the first case, so no extra lookup is
 * needed. Without a scope this delegates to the wording the practice view
 * has always used, rather than growing a second copy free to drift.
 */
export function describeScopedUnavailable(err, { scope, objectiveCount, topicId } = {}) {
  if (!scope || scope.kind === "goal") {
    return describePracticeUnavailable(err, { objectiveCount, topicId: topicId || (scope && scope.topicId) });
  }
  const message = (err && err.message) || "Error inesperado.";
  if (!err || err.status !== 404) return message;
  if (message.includes("has no objective matching")) {
    return `Ya no hay objetivos en ${scope.label}.`;
  }
  if (message.includes("no question for any due or unstarted")) {
    return `Todavía no hay preguntas para lo pendiente en ${scope.label}.`;
  }
  return `Ya no queda nada pendiente en ${scope.label}. Volvé más tarde o elegí otra cosa.`;
}
