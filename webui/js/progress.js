"use strict";

import { escapeHtml } from "./format.js";
import { unitName } from "./tree.js";

// The Progreso dashboard's model and markup (issue #74). Pure: models in,
// strings out, so it is unit-testable under Node with no browser.
//
// **No scoring of its own.** Each objective's `level`, `score`, `is_due` and
// `next_review_at` are copied from `/objectives/states`, and a goal's mean is
// `/summary`'s `mean_score`. The only things done here are
//   - grouping a level into one of four *friendly bands* (BANDS below),
//   - counting objectives per band, and
//   - averaging engine scores over a unit, which is the definition the
//     engine itself uses for the goal (`mean_score`) over a subset.
// Nothing is derived from attempts or dates in the browser, apart from
// rendering a review date relative to the `now` passed in.

// The engine ladder folded into the words a student or a parent reads. The
// order is the order the bars and the summary list them in.
export const BANDS = [
  { id: "mastered", label: "Lo domina", levels: ["MASTERED", "COMPETENT"] },
  { id: "good", label: "Va bien", levels: ["LEARNING"] },
  { id: "reinforce", label: "Reforzar", levels: ["WEAK"] },
  { id: "new", label: "Por empezar", levels: ["UNASSESSED"] },
];

export function bandOf(level) {
  const band = BANDS.find((candidate) => candidate.levels.includes(level));
  return band ? band.id : "new";
}

export function bandLabel(id) {
  const band = BANDS.find((candidate) => candidate.id === id);
  return band ? band.label : id;
}

function emptyCounts() {
  return { mastered: 0, good: 0, reinforce: 0, new: 0 };
}

function countBands(objectives) {
  const counts = emptyCounts();
  for (const objective of objectives) counts[objective.band] += 1;
  return counts;
}

function mean(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

/**
 * One goal's dashboard model. `summary` may be null (its call failed): the
 * goal then has no headline percentage rather than a fake zero.
 */
export function buildProgress(topic, states, summary) {
  const stateById = new Map((states || []).map((state) => [state.objective_id, state]));
  const buckets = new Map();
  for (const objective of topic.objectives) {
    const code = objective.domain || null;
    if (!buckets.has(code)) buckets.set(code, []);
    const state = stateById.get(objective.objective_id);
    buckets.get(code).push({
      objectiveId: objective.objective_id,
      title: objective.title,
      band: bandOf(state ? state.level : "UNASSESSED"),
      score: state ? state.score : 0,
      isDue: Boolean(state && state.is_due),
      nextReviewAt: state ? state.next_review_at : null,
    });
  }
  const units = [...buckets.entries()]
    .sort(([left], [right]) => (left === right ? 0 : left === null ? 1 : right === null ? -1 : left < right ? -1 : 1))
    .map(([code, objectives]) => ({
      code,
      name: unitName(code),
      objectives,
      counts: countBands(objectives),
      meanScore: mean(objectives.map((objective) => objective.score)),
    }));
  const all = units.flatMap((unit) => unit.objectives);
  return {
    topicId: topic.topic_id,
    name: topic.name,
    meanScore: summary ? summary.mean_score : null,
    counts: countBands(all),
    total: all.length,
    due: all.filter((objective) => objective.isDue).length,
    units,
  };
}

/** Roll-up across goals, for the strip at the top of the page. */
export function buildOverview(models) {
  const counts = emptyCounts();
  let total = 0;
  let due = 0;
  for (const model of models) {
    for (const band of Object.keys(counts)) counts[band] += model.counts[band];
    total += model.total;
    due += model.due;
  }
  return { counts, total, due, goals: models.length };
}

/**
 * The next reviews across every goal: pending ones first (they are the
 * soonest by definition), then by date, capped at `limit`. Objectives that
 * were never practised have no review date and never appear.
 */
export function upcomingReviews(models, limit = 6) {
  const rows = [];
  for (const model of models) {
    for (const unit of model.units) {
      for (const objective of unit.objectives) {
        if (!objective.nextReviewAt) continue;
        rows.push({
          title: objective.title,
          goal: model.name,
          isDue: objective.isDue,
          at: Date.parse(objective.nextReviewAt),
        });
      }
    }
  }
  return rows.sort((a, b) => a.at - b.at).slice(0, limit);
}

/** "Repaso pendiente", "Hoy", "Mañana", "En 5 días", "En 3 semanas". */
export function reviewWhen(row, now) {
  if (row.isDue) return "Repaso pendiente";
  const days = Math.ceil((row.at - now) / 86400000);
  if (days <= 0) return "Hoy";
  if (days === 1) return "Mañana";
  if (days < 14) return `En ${days} días`;
  return `En ${Math.round(days / 7)} semanas`;
}

function percent(ratio) {
  return Math.round(Math.max(0, Math.min(1, ratio || 0)) * 100);
}

/** The stacked bar: one segment per band, as wide as its share of objectives. */
export function stackedBarView(counts, total) {
  if (!total) return '<span class="stack" aria-hidden="true"></span>';
  const label = BANDS.filter((band) => counts[band.id])
    .map((band) => `${counts[band.id]} ${bandLabel(band.id).toLowerCase()}`)
    .join(", ");
  const segments = BANDS.filter((band) => counts[band.id])
    .map(
      (band) =>
        `<span class="stack-seg" data-band="${band.id}" style="flex: ${counts[band.id]}"></span>`,
    )
    .join("");
  return `<span class="stack" role="img" aria-label="${escapeHtml(label)}">${segments}</span>`;
}

function scoreBarView(score, band) {
  return `<span class="meter" data-band="${band}" role="img" aria-label="${percent(score)}%"
    ><span class="meter-fill" style="width: ${percent(score)}%"></span></span>`;
}

function bandChipView(band) {
  return `<span class="band-chip" data-band="${band}">${escapeHtml(bandLabel(band))}</span>`;
}

function objectiveRowView(objective) {
  const started = objective.band !== "new";
  const bar = started ? scoreBarView(objective.score, objective.band) : '<span class="meter-none">Aún sin practicar</span>';
  const due = objective.isDue ? '<span class="pending-chip">Repaso pendiente</span>' : "";
  return `<li class="prog-objective">
      <span class="prog-objective-title">${escapeHtml(objective.title)}${due}</span>
      ${bar}${bandChipView(objective.band)}
    </li>`;
}

function unitSectionView(unit) {
  const total = unit.objectives.length;
  const good = unit.counts.mastered;
  return `<div class="prog-unit">
      <div class="prog-unit-head">
        <h4>${escapeHtml(unit.name)}</h4>
        <span class="prog-unit-count">${good} de ${total} dominados</span>
      </div>
      ${stackedBarView(unit.counts, total)}
      <ul class="prog-objectives">${unit.objectives.map(objectiveRowView).join("")}</ul>
    </div>`;
}

/** One goal's card: headline bar, the mix of bands, then each unit. */
export function goalProgressView(model) {
  const headline =
    model.meanScore === null
      ? ""
      : `<span class="prog-goal-percent">${percent(model.meanScore)}<small>%</small></span>`;
  const bar = model.meanScore === null ? "" : scoreBarView(model.meanScore, "overall");
  const pending = model.due
    ? `<span class="pending-chip">${model.due} ${model.due === 1 ? "repaso pendiente" : "repasos pendientes"}</span>`
    : "";
  return `<article class="prog-goal" data-topic-id="${escapeHtml(model.topicId)}">
      <div class="prog-goal-head">
        <h3>${escapeHtml(model.name)}</h3>
        ${pending}
      </div>
      <div class="prog-goal-summary">
        ${headline}
        <div class="prog-goal-bars">${bar}${stackedBarView(model.counts, model.total)}${legendView(model.counts)}</div>
      </div>
      ${model.units.map(unitSectionView).join("")}
    </article>`;
}

function legendView(counts) {
  return `<ul class="legend">${BANDS.filter((band) => counts[band.id])
    .map(
      (band) =>
        `<li data-band="${band.id}"><span class="legend-dot"></span>${counts[band.id]} ${escapeHtml(bandLabel(band.id))}</li>`,
    )
    .join("")}</ul>`;
}

export function overviewView(overview, upcomingCount) {
  const tiles = [
    { value: overview.counts.mastered, label: "Objetivos que domina", band: "mastered" },
    { value: overview.counts.good, label: "Van bien", band: "good" },
    { value: overview.counts.reinforce, label: "Por reforzar", band: "reinforce" },
    { value: upcomingCount, label: "Repasos próximos", band: "review" },
  ];
  return `<ul class="prog-tiles">${tiles
    .map(
      (tile) => `<li class="prog-tile" data-band="${tile.band}">
        <span class="prog-tile-value">${escapeHtml(tile.value)}</span>
        <span class="prog-tile-label">${escapeHtml(tile.label)}</span>
      </li>`,
    )
    .join("")}</ul>`;
}

export function upcomingView(rows, now) {
  if (!rows.length) return '<p class="empty">Todavía no hay repasos programados.</p>';
  return `<ul class="prog-upcoming">${rows
    .map(
      (row) => `<li${row.isDue ? ' class="pending"' : ""}>
        <span class="prog-upcoming-title">${escapeHtml(row.title)}<small>${escapeHtml(row.goal)}</small></span>
        <span class="prog-upcoming-when">${escapeHtml(reviewWhen(row, now))}</span>
      </li>`,
    )
    .join("")}</ul>`;
}
