"use strict";

import { escapeHtml, levelLabel } from "./format.js";

// The Goal > Unit > Topic tree, which since issue #69 is the screen: goal ->
// topic/profile, unit -> objective.domain (D1..D5), topic -> objective.
// Everything here is pure - a model in, markup out. Expansion is
// `<details>`/`<summary>`, so unfolding needs no listener at all: a row
// opens in place, keyboard included, and this module owns no DOM state a
// re-render could lose.
//
// **THE MODE CONTRACT** (`treeView(model, { mode })`). Both modes draw the
// same tree - every row reports where it stands, a bar for the goal and each
// unit, a level and a due marker for each topic - and differ only in the
// control they hang off a row:
//   - `"play"` (the default): a "Practicar" button per practisable row,
//     which drills exactly that scope. Nothing to confirm, because the row
//     the button sits on *is* the choice.
//   - `"pick"` (behind "Elegir varios"): an "Elegir" checkbox instead,
//     feeding the scoped
//     `GET /topics/{id}/practice/next?domain=&objective_id=`. Several may
//     be ticked at once, at any level and mixed (issue #62), which is why
//     the control is a checkbox and not the single-choice button it was:
//     the shape of the control is the honest statement of what may be
//     chosen. It is the occasional case, so it is not what every visit
//     pays for (issue #69). Any other mode still throws rather than
//     quietly rendering a tree with no controls: one that looks selectable
//     and is not is worse than an error.
// Either control is an addition, not a rewrite: every row already carried
// `data-scope` and what that scope needs - `data-topic-id` and
// `data-goal-label` on the goal, `data-domain` on the unit (absent on the
// fallback bucket, which has no domain to scope by), `data-objective-id`
// and `data-has-questions` on the topic. Which is why neither is rendered
// on that bucket or on a `has_questions === false` topic: the practice
// endpoint skips objectives with no stored question, so offering one would
// promise what the engine cannot deliver, and the row says "Sin preguntas"
// instead.
//
// A control carries `data-pick`/`data-play` (the kind) and its label twin
// (what the selection is called in Spanish, e.g. "D3 - Visión"). Building
// that label here rather than in the view is deliberate: this file is the
// one that knows a unit by both its code and its name, which leaves the
// view thin enough to be a click handler.

// Bare codes say nothing in a tree. These names are read off the objectives
// each code actually holds in `ai-103-oficial` (D1 is all choose / deploy /
// monitor / govern, D3 is all images and video), not copied from an exam
// outline this repo does not store. An unknown code falls back to itself:
// showing "D6" is honest, naming it is not. Objectives with no domain were
// never filed under a unit and group under a bucket that says so.
export const UNIT_NAMES = {
  D1: "Planificar, desplegar, gestionar y gobernar",
  D2: "IA generativa y agentes",
  D3: "Visión",
  D4: "Lenguaje y voz",
  D5: "Recuperación y extracción de conocimiento",
};
export const UNGROUPED_UNIT_NAME = "Sin unidad";

export function unitName(code) {
  return code ? UNIT_NAMES[code] || code : UNGROUPED_UNIT_NAME;
}

/**
 * Builds one goal's tree out of what the API already derived.
 *
 * **The one rule this file exists to respect:** no level, no due date and
 * no score is computed here. `level` and `is_due` are copied from
 * `/objectives/states`, the goal's bar is `summary.coverage`, and the only
 * arithmetic below is counting rows the engine already labelled - so a
 * unit's bar is the goal's own definition (coverage is assessed / total,
 * assessed is "level is not UNASSESSED", core/models.py) over a subset.
 * Deriving any of it from the attempts in the browser is the divergence
 * SPEC section 0 exists to prevent. An objective absent from `states` shows
 * as UNASSESSED and not due - what the engine reports for one with no
 * attempt - rather than vanishing from the tree.
 */
export function buildTree(topic, states, summary) {
  const stateById = new Map((states || []).map((state) => [state.objective_id, state]));
  const buckets = new Map();
  for (const objective of topic.objectives) {
    const code = objective.domain || null;
    if (!buckets.has(code)) buckets.set(code, []);
    const state = stateById.get(objective.objective_id);
    buckets.get(code).push({
      objectiveId: objective.objective_id,
      title: objective.title,
      level: state ? state.level : "UNASSESSED",
      isDue: Boolean(state && state.is_due),
      hasQuestions: Boolean(objective.has_questions),
    });
  }
  const units = [...buckets.entries()]
    .sort(byUnitCode)
    .map(([code, topics]) => ({ code, name: unitName(code), topics, progress: count(topics) }));
  return { topicId: topic.topic_id, name: topic.name, units, progress: summaryProgress(summary) };
}

/** The goal's own bar, read straight off `/summary`: the engine's coverage
 * and the counts behind it. Null without one - a missing bar, never a fake
 * zero. */
export function summaryProgress(summary) {
  if (!summary) return null;
  const { assessed_objectives: assessed, total_objectives: total, coverage: ratio } = summary;
  return { assessed, total, ratio };
}

// Codes ascending, the unnamed bucket last: it is not a unit, so it does
// not compete for a place among them.
function byUnitCode([left], [right]) {
  if (left === right) return 0;
  if (left === null || right === null) return left === null ? 1 : -1;
  return left < right ? -1 : 1;
}

function count(topics) {
  const assessed = topics.filter((topic) => topic.level !== "UNASSESSED").length;
  return { assessed, total: topics.length, ratio: topics.length ? assessed / topics.length : 0 };
}

// The bar, plus the count that says what it means: a bar alone is a shape,
// "12/64" is something to act on.
export function progressBarView(progress) {
  const percent = Math.round((progress.ratio || 0) * 100);
  return `<span class="bar" role="img" aria-label="${percent}% evaluado"
      ><span class="bar-fill" style="width: ${percent}%"></span></span
    ><span class="bar-count">${escapeHtml(progress.assessed)}/${escapeHtml(progress.total)}</span>`;
}

/** The "Elegir" checkbox, rendered in pick mode on a selectable row only.
 *
 * A checkbox, not the `aria-pressed` button this was while a selection could
 * hold exactly one row (issue #49): rows at several levels may be ticked
 * together now, and a native checkbox states that by itself - to the eye, to
 * a screen reader and to the keyboard alike, with no role invented here. It
 * is always rendered unticked: which ones are ticked is the picker's to set,
 * because this file is pure and a selection outlives the markup a re-render
 * throws away.
 *
 * The `<label>` wrapping it makes the whole control, word included, the
 * target - the reach the button had on a phone, kept. The visible word stays
 * "Elegir" for the eye, which has the row next to it; `aria-label` names the
 * row, because a screen reader reading sixty checkboxes all called "Elegir"
 * cannot tell which one it is on. */
export function pickView(kind, label) {
  return `<label class="pick"><input type="checkbox" class="pick-check" data-pick="${escapeHtml(kind)}"
      data-pick-label="${escapeHtml(label)}" aria-label="Elegir ${escapeHtml(label)}"><span>Elegir</span></label>`;
}

/** The "Practicar" button play mode hangs off a practisable row (issue #69).
 *
 * It wears the same pill the checkbox wears and says the word rather than
 * drawing a play triangle: the disclosure triangle sits two elements to its
 * left on the very same row, and in this system that mark already means
 * "unfold". Two identical triangles meaning two different things on one row
 * is not a saving. The visible word is the same on all sixty of them, so
 * `aria-label` names the row - a screen reader has no row to read it next
 * to. */
export function playView(kind, label) {
  return `<button type="button" class="play" data-play="${escapeHtml(kind)}"
      data-play-label="${escapeHtml(label)}" aria-label="Practicar ${escapeHtml(label)}">Practicar</button>`;
}

/** The control one practisable row carries, by mode. Kept in one place so
 * "which rows may be practised" is decided once and the two modes cannot
 * drift into disagreeing about it. */
function actionView(mode, kind, label) {
  if (mode === "pick") return pickView(kind, label);
  if (mode === "play") return playView(kind, label);
  return "";
}

export function topicRowView(topic, options = {}) {
  const id = `data-objective-id="${escapeHtml(topic.objectiveId)}" data-has-questions="${topic.hasQuestions}"`;
  const chip = `<span class="level-chip" data-level="${escapeHtml(topic.level)}">${escapeHtml(levelLabel(topic.level))}</span>`;
  const acting = options.mode === "pick" || options.mode === "play";
  const action = !acting
    ? ""
    : topic.hasQuestions
      ? actionView(options.mode, "topic", `${topic.objectiveId} - ${topic.title}`)
      : '<span class="no-questions">Sin preguntas</span>';
  // `aria-disabled`, not a hidden row: its level and its due marker are the
  // reason to go generate questions for it. It just offers no way to
  // practise it, because the endpoint has nothing to serve.
  const disabled = acting && !topic.hasQuestions ? ' aria-disabled="true"' : "";
  return `<li class="tree-topic" data-scope="topic" ${id}${disabled}>
      <span class="tree-topic-title">${escapeHtml(topic.title)}</span>
      ${chip}${topic.isDue ? '<span class="due-marker">Vencido</span>' : ""}${action}
    </li>`;
}

export function unitView(unit, options = {}) {
  const domain = unit.code ? ` data-domain="${escapeHtml(unit.code)}"` : "";
  const pick = unit.code ? actionView(options.mode, "unit", `${unit.code} - ${unit.name}`) : "";
  const head = `<span class="tree-name">${escapeHtml(unit.name)}</span>${progressBarView(unit.progress)}${pick}`;
  return `<li><details class="tree-unit" data-scope="unit"${domain}>
      <summary class="tree-row">${head}</summary>
      <ul class="tree-topics">${unit.topics.map((topic) => topicRowView(topic, options)).join("")}</ul>
    </details></li>`;
}

/** The units of one goal, split out of `treeView` because the learning tab
 * fetches a goal's objectives only once its row is open, so it has a body
 * already on screen to fill. */
export function unitsView(units, options = {}) {
  assertMode(options.mode);
  if (!units.length) return '<p class="empty">Todavía no tiene objetivos.</p>';
  return `<ul class="tree-units">${units.map((unit) => unitView(unit, options)).join("")}</ul>`;
}

/** The goal row, open or closed. `progress` may be null while its summary
 * is still in flight (or failed): the bar is then absent, not faked at 0. */
export function goalView(model, body, options = {}) {
  assertMode(options.mode);
  const bar = model.progress ? progressBarView(model.progress) : "";
  const pick = actionView(options.mode, "goal", model.name);
  const head = `<span class="tree-name">${escapeHtml(model.name)}</span>${bar}${pick}`;
  // `data-goal-label` so a control anywhere inside can name its goal ("lo
  // que toca en AI-103") by looking up, without the view having to hold a
  // second copy of the goal list to look the name up in.
  return `<details class="tree-goal" data-scope="goal" data-topic-id="${escapeHtml(model.topicId)}"
      data-goal-label="${escapeHtml(model.name)}"${options.open ? " open" : ""}>
      <summary class="tree-row">${head}</summary>
      <div class="goal-body">${body}</div>
    </details>`;
}

/** The whole goal, for a caller that already has every level loaded. */
export function treeView(model, options = {}) {
  return goalView(model, unitsView(model.units, options), options);
}

function assertMode(mode) {
  if (mode !== undefined && mode !== "play" && mode !== "pick") {
    throw new Error(`tree mode not implemented: ${mode}`);
  }
}
