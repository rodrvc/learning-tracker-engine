"use strict";

import { describePracticeUnavailable } from "./format.js";

// What "practising a selection" means, kept DOM-free (issue #49, widened to
// several rows at once in issue #62). Everything the practice tab decides
// from the rows that are ticked - the query the scoped endpoint gets, what
// the action button says, what an empty answer means - is decided here, so
// it is testable without a browser.
//
// **A selection is a set of rows inside one goal.** Shape:
//
//     { topicId, goalLabel, items: [{ kind: "unit" | "topic", value, label }] }
//
// `items` empty is not "nothing selected": it is the goal itself, which
// means "practise this goal, engine's choice" - exactly the unscoped call
// this endpoint has always answered. That is why the goal is not an item:
// an empty selection already says it, and an item for it would be a second
// spelling of the same request, free to disagree with the first. Only a
// unit (-> `domain`) and a topic (-> `objective_id`) narrow the walk.
//
// **One goal, never two**, because the endpoint is per topic
// (`/topics/{id}/practice/next`): ticking a row in another goal starts that
// goal's selection instead of growing a request that cannot be made.
//
// **The order is never ours.** What is built here is a candidate *set*;
// which of its objectives comes up first is the engine's own order (SPEC
// section 5.2, web/routers/practice.py). Nothing here sorts or ranks.

/** A goal with nothing finer ticked: the unscoped call, named. */
export function emptySelection(topicId, goalLabel) {
  if (!topicId) return null;
  return { topicId, goalLabel: goalLabel || topicId, items: [] };
}

/** The item one tickable row stands for, or `null` when that row cannot be
 * practised. The "Sin unidad" bucket is the null case that matters: it
 * groups objectives never filed under a domain, so it has no `domain` to
 * scope by (see tree.js), and `null` rather than an empty domain is what
 * keeps the front end from asking for `?domain=` - a different question. */
export function itemFromRow({ kind, domain, objectiveId, label } = {}) {
  if (kind === "unit") return domain ? { kind, value: domain, label: label || domain } : null;
  if (kind === "topic") {
    return objectiveId ? { kind, value: objectiveId, label: label || objectiveId } : null;
  }
  return null;
}

/** Items compare by what they select, not by object reference: the picker
 * re-renders its rows (a goal's units arrive after its first open), so a
 * ticked row has to be found again by value every time. */
function sameItem(left, right) {
  return Boolean(left) && Boolean(right) && left.kind === right.kind && left.value === right.value;
}

/**
 * The selection after ticking (or unticking) one row: a new selection out,
 * the old one untouched. Three rules live here and only here:
 *   - the goal row *replaces* the selection with the empty one. "The whole
 *     goal" and "these three units" are contradictory answers to the same
 *     question, and keeping both would send a narrowed query while the
 *     screen claimed the engine was choosing.
 *   - a row in another goal starts that goal's selection (see the header).
 *   - a ticked row is unticked; the last one leaves the empty selection,
 *     never `null`, so the button keeps offering the goal instead of going
 *     dead.
 */
export function toggleRow(selection, row = {}) {
  const { topicId, goalLabel } = row;
  if (!topicId) return selection;
  if (row.kind === "goal") return emptySelection(topicId, goalLabel);
  const item = itemFromRow(row);
  if (!item) return selection;
  if (!selection || selection.topicId !== topicId) {
    return { topicId, goalLabel: goalLabel || topicId, items: [item] };
  }
  const items = selection.items.some((current) => sameItem(current, item))
    ? selection.items.filter((current) => !sameItem(current, item))
    : [...selection.items, item];
  return { ...selection, items };
}

/** Whether a row's checkbox is ticked. The goal's is ticked exactly when
 * nothing finer is, which is what makes the two readable as one choice. */
export function isRowSelected(selection, row = {}) {
  if (!selection || selection.topicId !== row.topicId) return false;
  if (row.kind === "goal") return selection.items.length === 0;
  const item = itemFromRow(row);
  return Boolean(item) && selection.items.some((current) => sameItem(current, item));
}

/** How many rows narrow the selection. Zero is the goal. */
export function selectionSize(selection) {
  return selection ? selection.items.length : 0;
}

/** The query string for `GET /topics/{id}/practice/next`: repeated
 * parameters (`?domain=D1&domain=D2&objective_id=D3.2.a`), the shape the
 * endpoint resolves to a union - readable in the address bar and buildable
 * without an encoding scheme of its own. Empty for the goal and for no
 * selection alike: both mean "whatever the engine says is next". */
export function selectionQuery(selection) {
  if (!selection || !selection.items.length) return "";
  const parts = [
    ...pairsFor(selection, "unit", "domain"),
    ...pairsFor(selection, "topic", "objective_id"),
  ];
  return `?${parts.join("&")}`;
}

// Domains first, then objectives: grouped by parameter rather than by the
// order they were ticked in, so the same selection always reads the same
// way in the address bar.
function pairsFor(selection, kind, parameter) {
  return selection.items
    .filter((item) => item.kind === kind)
    .map((item) => `${parameter}=${encodeURIComponent(item.value)}`);
}

/** What the selection is called in Spanish: one row is named, several are
 * *counted*. "Practicando D1 - Planificar..., D2 - IA generativa... y 3
 * más" is a list truncated at the width of the screen, the one thing a
 * person cannot check against what they ticked; "3 unidades y 2 objetivos"
 * is something they can (issue #62). */
export function selectionLabel(selection) {
  if (!selection) return null;
  const { items } = selection;
  if (!items.length) return `lo que toca en ${selection.goalLabel}`;
  if (items.length === 1) return items[0].label;
  const units = items.filter((item) => item.kind === "unit").length;
  const parts = [];
  if (units) parts.push(plural(units, "unidad", "unidades"));
  if (items.length - units) parts.push(plural(items.length - units, "objetivo", "objetivos"));
  return parts.join(" y ");
}

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many}`;
}

/** What the action button says, which is the only place the difference
 * between scoped and unscoped is explained to the person: with the goal
 * ticked the wording says out loud that the engine is choosing ("lo que
 * toca"), which a button reading "Practicar AI-103" would hide. */
export function practiceButtonLabel(selection) {
  if (!selection) return "Elegí una meta para practicar";
  return `Practicar ${selectionLabel(selection)}`;
}

/** The line shown while drilling, so what is being practised is never a
 * guess. The goal says whose choice the questions are. */
export function practicingLabel(selection) {
  if (!selection) return "Practicando lo que toca";
  return `Practicando ${selectionLabel(selection)}`;
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
 * needed. With nothing narrowed this delegates to the wording the practice
 * view has always used, rather than growing a second copy free to drift.
 * A selection of several is "lo que elegiste" in all three rather than its
 * count: "Ya no hay objetivos en 2 unidades y 1 objetivo" makes a reader
 * parse arithmetic to reach the news.
 */
export function describeScopedUnavailable(err, { selection, objectiveCount, topicId } = {}) {
  if (!selectionSize(selection)) {
    return describePracticeUnavailable(err, {
      objectiveCount,
      topicId: topicId || (selection && selection.topicId),
    });
  }
  const message = (err && err.message) || "Error inesperado.";
  if (!err || err.status !== 404) return message;
  const where = selection.items.length === 1 ? selection.items[0].label : "lo que elegiste";
  if (message.includes("has no objective matching")) {
    return `Ya no hay objetivos en ${where}.`;
  }
  if (message.includes("no question for any due or unstarted")) {
    return `Todavía no hay preguntas para lo pendiente en ${where}.`;
  }
  return `Ya no queda nada pendiente en ${where}. Volvé más tarde o elegí otra cosa.`;
}
