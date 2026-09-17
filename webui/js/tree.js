"use strict";

import { escapeHtml, levelLabel } from "./format.js";

// The Goal > Unit > Topic tree, shared by both tabs (issue #49): goal ->
// topic/profile, unit -> objective.domain (D1..D5), topic -> objective.
// Everything here is pure - a model in, markup out. Expansion is
// `<details>`/`<summary>`, so the read mode needs no listener at all: a row
// opens in place, keyboard included, and this module owns no DOM state a
// re-render could lose.
//
// **THE MODE CONTRACT** (`treeView(model, { mode })`), so the practice tab
// is built on this file rather than beside it:
//   - `"read"` (implemented, the learning tab): every row reports where it
//     stands - a bar for the goal and each unit, a level and a due marker
//     for each topic - and nothing is clickable but the triangles.
//   - `"pick"` (implemented, the practice tab): the same tree, plus one
//     "Elegir" button per selectable row, feeding the scoped
//     `GET /topics/{id}/practice/next?domain=&objective_id=`. Any other
//     mode still throws rather than quietly rendering the read one: a tree
//     that looks selectable and is not is worse than an error.
// Pick mode stayed a selection control plus a click delegate, not a
// rewrite: every row already carried `data-scope` and what that scope needs
// - `data-topic-id` on the goal, `data-domain` on the unit (absent on the
// fallback bucket, which has no domain to scope by), `data-objective-id`
// and `data-has-questions` on the topic. Which is why the pick button is
// absent from that bucket and from a `has_questions === false` topic: the
// practice endpoint skips objectives with no stored question, so offering
// one would promise what the engine cannot deliver, and the row says "Sin
// preguntas" instead.
//
// The button carries `data-pick` (the kind) and `data-pick-label` (what the
// selection is called in Spanish, e.g. "D3 - Visión"). Building that label
// here rather than in the view is deliberate: this file is the one that
// knows a unit by both its code and its name, which leaves the view thin
// enough to be a click handler.

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

/** The "Elegir" button, rendered in pick mode on a selectable row only.
 * `aria-pressed` carries the selected state - exactly one button in the
 * tree says `true` - which is a radio group written with the control that
 * already reads as a target on a phone. */
export function pickView(kind, label) {
  return `<button type="button" class="pick" data-pick="${escapeHtml(kind)}"
      data-pick-label="${escapeHtml(label)}" aria-pressed="false">Elegir</button>`;
}

export function topicRowView(topic, options = {}) {
  const id = `data-objective-id="${escapeHtml(topic.objectiveId)}" data-has-questions="${topic.hasQuestions}"`;
  const chip = `<span class="level-chip" data-level="${escapeHtml(topic.level)}">${escapeHtml(levelLabel(topic.level))}</span>`;
  const picking = options.mode === "pick";
  const pick = !picking
    ? ""
    : topic.hasQuestions
      ? pickView("topic", `${topic.objectiveId} - ${topic.title}`)
      : '<span class="no-questions">Sin preguntas</span>';
  // `aria-disabled`, not a hidden row: its level and its due marker are the
  // reason to go generate questions for it. It just offers no way to
  // practise it, because the endpoint has nothing to serve.
  const disabled = picking && !topic.hasQuestions ? ' aria-disabled="true"' : "";
  return `<li class="tree-topic" data-scope="topic" ${id}${disabled}>
      <span class="tree-topic-title">${escapeHtml(topic.title)}</span>
      ${chip}${topic.isDue ? '<span class="due-marker">Vencido</span>' : ""}${pick}
    </li>`;
}

export function unitView(unit, options = {}) {
  const domain = unit.code ? ` data-domain="${escapeHtml(unit.code)}"` : "";
  const pick =
    options.mode === "pick" && unit.code ? pickView("unit", `${unit.code} - ${unit.name}`) : "";
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
  const pick = options.mode === "pick" ? pickView("goal", model.name) : "";
  const head = `<span class="tree-name">${escapeHtml(model.name)}</span>${bar}${pick}`;
  return `<details class="tree-goal" data-scope="goal" data-topic-id="${escapeHtml(model.topicId)}"${options.open ? " open" : ""}>
      <summary class="tree-row">${head}</summary>
      <div class="goal-body">${body}</div>
    </details>`;
}

/** The whole goal, for a caller that already has every level loaded. */
export function treeView(model, options = {}) {
  return goalView(model, unitsView(model.units, options), options);
}

function assertMode(mode) {
  if (mode !== undefined && mode !== "read" && mode !== "pick") {
    throw new Error(`tree mode not implemented: ${mode}`);
  }
}
