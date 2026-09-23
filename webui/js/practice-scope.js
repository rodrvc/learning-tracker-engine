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
// `items` empty is not "nothing selected" - `null` is: it is the goal
// itself, which means "practise this goal, engine's choice", exactly the
// unscoped call this endpoint has always answered. That is why the goal is
// not an item: an empty list already says it, and an item for it would be a
// second spelling of the same request, free to disagree with the first. Only
// a unit (-> `domain`) and a topic (-> `objective_id`) narrow the walk.
//
// **`items` is the coarsest honest description of the set, and the display
// is derived from it** (issue #71 follow-up). This is the one idea that
// makes the cascade and the query agree instead of fighting:
//
//   - *the display cascades down.* `rowState` asks "is this row covered by
//     something in `items`?", so the goal ticked (`items: []`) shows every
//     unit and every objective ticked, and a unit ticked shows its
//     objectives ticked. A tree of checkboxes means that everywhere else and
//     it has to mean it here.
//   - *the request stays as small as it can honestly be.* A ticked goal is
//     still the empty list, so the query is still no parameters at all - the
//     unscoped call the engine owns - and not sixteen repeated `domain=`.
//     Nothing about the cascade reaches `selectionQuery`.
//
// A parent is expanded into its children only when one of them is taken
// out, because that is the only moment the coarse form stops being able to
// say what is meant: "the whole goal minus D3" is not any `items: []`, it is
// the four other units. `normalize` puts it back the moment the children are
// all ticked again, so there is one canonical form per set and a goal whose
// units are all ticked one by one is the same `items: []` as a goal ticked
// in one press.
//
// Expanding needs the goal's shape, which the caller reads off the tree and
// passes in:
//
//     { units: [{ code, label, objectives: [{ id, label }] }], ungrouped }
//
// `objectives` holds only the ones that can be practised - an objective with
// no stored question has no checkbox and no `objective_id` worth sending.
// `ungrouped` says the goal also holds objectives filed under no unit at
// all: they cannot be named by any parameter, so a goal that has them is
// never collapsed back to `items: []` from its units, and expanding it does
// lose them. That is the one lossy step here, and it only happens because
// the person just narrowed the selection themselves.
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

/** Items compare by what they select, not by object reference: the view
 * re-renders its rows (a goal's units arrive after its first open), so a
 * ticked row has to be found again by value every time. */
function sameItem(left, right) {
  return Boolean(left) && Boolean(right) && left.kind === right.kind && left.value === right.value;
}

/** The selectable objectives of one unit, as the shape reported them. */
function objectivesOf(shape, code) {
  const unit = ((shape && shape.units) || []).find((current) => current.code === code);
  return (unit && unit.objectives) || [];
}

function hasItem(items, kind, value) {
  return items.some((item) => item.kind === kind && item.value === value);
}

/**
 * How a row's checkbox is drawn: `"on"`, `"off"` or `"partial"`.
 *
 * Three states, not two, because a parent whose children are only some of
 * them ticked is neither: drawn ticked it would claim the ones that are not,
 * drawn empty it would hide the ones that are. `partial` is the browser's
 * own `indeterminate`, so the distinction costs no mark of our own.
 *
 * Coverage, never identity: a row is on when *anything in `items` covers
 * it*, which is what makes ticking a goal tick every row underneath without
 * `items` having to list them.
 */
export function rowState(selection, row = {}, shape = {}) {
  if (!selection || selection.topicId !== row.topicId) return "off";
  const { items } = selection;
  // The whole goal: everything under it is covered, at every level.
  if (!items.length) return "on";
  // ...and anything narrower leaves the goal itself partly ticked, since a
  // non-empty list is by definition less than all of it.
  if (row.kind === "goal") return "partial";
  if (row.kind === "unit") {
    if (hasItem(items, "unit", row.domain)) return "on";
    const ids = objectivesOf(shape, row.domain).map((objective) => objective.id);
    return ids.some((id) => hasItem(items, "topic", id)) ? "partial" : "off";
  }
  if (row.kind === "topic") {
    // An objective is covered by its own unit as well as by itself. There is
    // no third state for a leaf: it has nothing underneath to be partly of.
    return hasItem(items, "unit", row.domain) || hasItem(items, "topic", row.objectiveId)
      ? "on"
      : "off";
  }
  return "off";
}

/**
 * The selection after ticking (or unticking) one row: a new selection out,
 * the old one untouched. The rules that live here and only here:
 *   - a row that is fully on goes off, and takes everything under it with
 *     it. One that is off *or only partly on* goes fully on, children
 *     included - partial to on is the move every file tree makes, and it
 *     leaves no way to get stuck halfway.
 *   - taking a child out of a ticked parent expands that parent into its
 *     siblings, which is the only way "the whole goal minus D3" can be said
 *     at all.
 *   - putting the last child back collapses them into the parent again
 *     (`normalize`), so one set has one spelling.
 *   - a row in another goal starts that goal's selection (see the header).
 *   - unticking the last thing leaves `null`, not the empty list: the empty
 *     list is the whole goal, and a selection that meant "everything" the
 *     moment it was emptied would be a trap.
 */
export function toggleRow(selection, row = {}, shape = {}) {
  const { topicId, goalLabel, kind } = row;
  if (!topicId) return selection;
  if (kind !== "goal" && !itemFromRow(row)) return selection;
  const mine = selection && selection.topicId === topicId ? selection : null;
  const named = { topicId, goalLabel: goalLabel || topicId };
  const state = rowState(mine, row, shape);
  // The goal is the only row whose "on" *is* the empty list, so it is the
  // only one that toggles without expanding or collapsing anything.
  if (kind === "goal") return state === "on" ? null : { ...named, items: [] };
  // "Everything" has to become the units it stands for before a child can be
  // taken out of it.
  const items = !mine ? [] : mine.items.length ? mine.items : expandGoal(shape);
  if (state !== "on") {
    // An empty list out of `normalize` is the goal itself - every unit ended
    // up ticked - which is the one result that must not be read as "nothing
    // left", hence the two returns rather than one length test.
    const next = normalize([...withoutSubtree(items, row, shape), itemFromRow(row)], shape);
    return { ...named, items: next };
  }
  const rest = turnOff(items, row, shape);
  return rest.length ? { ...named, items: rest } : null;
}

// The goal as the units it stands for. Objectives filed under no unit are
// dropped here, because no parameter can name them - see the header.
function expandGoal(shape) {
  return ((shape && shape.units) || []).map((unit) => ({
    kind: "unit",
    value: unit.code,
    label: unit.label || unit.code,
  }));
}

function expandUnit(shape, code) {
  return objectivesOf(shape, code).map((objective) => ({
    kind: "topic",
    value: objective.id,
    label: objective.label || objective.id,
  }));
}

// What a row about to be ticked makes redundant: its own item, and - for a
// unit - every one of its objectives. Leaving them in would let the same
// objectives be named twice and let `normalize` read a unit as complete
// while its own item was already there.
function withoutSubtree(items, row, shape) {
  if (row.kind !== "unit") return items.filter((item) => !sameItem(item, itemFromRow(row)));
  const ids = objectivesOf(shape, row.domain).map((objective) => objective.id);
  return items.filter(
    (item) => item.value !== row.domain && !(item.kind === "topic" && ids.includes(item.value)),
  );
}

// Taking one row out of a set that covers it. An objective covered by its
// unit is the case that has to expand: the unit goes, its other objectives
// arrive in its place.
function turnOff(items, row, shape) {
  if (row.kind === "unit") return withoutSubtree(items, row, shape);
  const rest = hasItem(items, "unit", row.domain)
    ? [...items.filter((item) => !(item.kind === "unit" && item.value === row.domain)),
       ...expandUnit(shape, row.domain)]
    : items;
  return rest.filter((item) => !(item.kind === "topic" && item.value === row.objectiveId));
}

// The coarsest spelling of the same set: every objective of a unit becomes
// the unit, every unit of the goal becomes the goal. Guarded twice - a shape
// that reported no unit at all must not collapse to "the whole goal", and
// neither must a goal that also holds objectives no unit can name.
function normalize(items, shape) {
  const units = (shape && shape.units) || [];
  let next = items;
  for (const unit of units) {
    const ids = unit.objectives.map((objective) => objective.id);
    if (!ids.length || !ids.every((id) => hasItem(next, "topic", id))) continue;
    next = [
      ...next.filter((item) => !(item.kind === "topic" && ids.includes(item.value))),
      { kind: "unit", value: unit.code, label: unit.label || unit.code },
    ];
  }
  const whole =
    units.length &&
    !(shape && shape.ungrouped) &&
    units.every((unit) => hasItem(next, "unit", unit.code));
  return whole ? [] : next;
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

/**
 * What the selection's own action says (issue #71).
 *
 * It is the second of two buttons and never a relabelling of the first:
 * "Practicar lo que toca" stays on screen beside it, because the suggested
 * path is what most days want and a selection is the detour. That is the
 * whole reason this label exists separately from `dueActionLabel` - a single
 * button whose wording changed with the selection took the suggested path
 * away the moment a row was ticked.
 *
 * So the two have to be impossible to confuse at a glance: this one says
 * "lo marcado" and names what is marked, the other says "lo que toca" and
 * leaves the choice to the engine. The goal row marked is the one case with
 * nothing narrowed, and it is named by the goal rather than by
 * `selectionLabel`'s "lo que toca en AI-103" - that is the other button's
 * sentence, and borrowing it here would undo the distinction.
 *
 * Null with no selection: there is no button to label. A disabled one
 * standing there waiting is how this screen ended up with two mechanisms
 * for one idea the first time.
 */
export function selectedActionLabel(selection) {
  if (!selection) return null;
  const what = selection.items.length ? selectionLabel(selection) : selection.goalLabel;
  return `Practicar lo marcado (${what})`;
}

/**
 * What the default action says: the unscoped call, with how much is due
 * behind it (issue #69).
 *
 * This is the one button the screen is built around - "just practise, stop
 * asking me" - so it states the size of the backlog rather than making
 * anyone open the tree to find out. The count is the engine's own
 * `due_objectives` off `/summary`, never counted here; unknown (a summary
 * that failed) drops the number instead of printing a zero that would read
 * as "nothing to do".
 *
 * It never disables at zero, which is why the count is parenthetical and
 * not the subject: nothing due still leaves everything never practised, and
 * which of the two the endpoint serves is the engine's call (SPEC section
 * 5.2), not this label's. The goal is named only when there is more than
 * one to confuse it with.
 */
export function dueActionLabel(dueCount, goalLabel) {
  const where = goalLabel ? ` en ${goalLabel}` : "";
  const count = Number.isInteger(dueCount) ? ` (${dueCount})` : "";
  return `Practicar lo que toca${where}${count}`;
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
