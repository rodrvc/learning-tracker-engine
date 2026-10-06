// Unit tests for webui/js/progress.js (issue #74): the Progreso dashboard's
// model and markup. Wired into pytest by test_webui_router.py.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BANDS,
  bandOf,
  buildOverview,
  buildProgress,
  goalProgressView,
  overviewView,
  reviewWhen,
  stackedBarView,
  upcomingReviews,
  upcomingView,
} from "../../webui/js/progress.js";

const NOW = Date.parse("2026-10-06T12:00:00Z");
const day = (n) => new Date(NOW + n * 86400000).toISOString();

const topic = {
  topic_id: "historia",
  name: "Historia <2° Medio>",
  objectives: [
    { objective_id: "a", title: "Independencia", domain: "U1 · Independencia" },
    { objective_id: "b", title: "Constituciones", domain: "U1 · Independencia" },
    { objective_id: "c", title: "Ancón", domain: "U2 · Guerra" },
    { objective_id: "d", title: "Sin empezar", domain: "U2 · Guerra" },
    { objective_id: "e", title: "Suelto", domain: null },
  ],
};

function state(id, level, score, next, due = false) {
  return { objective_id: id, level, score, next_review_at: next, is_due: due };
}

const states = [
  state("a", "MASTERED", 0.97, day(30)),
  state("b", "WEAK", 0.4, day(-1), true),
  state("c", "LEARNING", 0.7, day(3)),
];

test("levels fold into the four friendly bands", () => {
  assert.deepEqual(BANDS.map((band) => band.id), ["mastered", "good", "reinforce", "new"]);
  assert.equal(bandOf("MASTERED"), "mastered");
  assert.equal(bandOf("COMPETENT"), "mastered");
  assert.equal(bandOf("LEARNING"), "good");
  assert.equal(bandOf("WEAK"), "reinforce");
  assert.equal(bandOf("UNASSESSED"), "new");
  assert.equal(bandOf("SOMETHING_NEW"), "new");
});

test("buildProgress copies engine values and only counts and averages them", () => {
  const model = buildProgress(topic, states, { mean_score: 0.55 });
  assert.equal(model.meanScore, 0.55);
  assert.equal(model.total, 5);
  assert.deepEqual(model.counts, { mastered: 1, good: 1, reinforce: 1, new: 2 });
  assert.equal(model.due, 1);
  assert.deepEqual(
    model.units.map((unit) => unit.name),
    ["U1 · Independencia", "U2 · Guerra", "Sin unidad"],
  );
  const first = model.units[0];
  assert.ok(Math.abs(first.meanScore - (0.97 + 0.4) / 2) < 1e-9);
  assert.deepEqual(first.counts, { mastered: 1, good: 0, reinforce: 1, new: 0 });
  // An objective the engine has no state for is "por empezar", not missing.
  assert.equal(model.units[1].objectives[1].band, "new");
});

test("a failed summary leaves the headline out instead of faking zero", () => {
  const model = buildProgress(topic, states, null);
  assert.equal(model.meanScore, null);
  const html = goalProgressView(model);
  assert.doesNotMatch(html, /prog-goal-percent/);
});

test("overview adds the goals up", () => {
  const one = buildProgress(topic, states, { mean_score: 0.5 });
  const overview = buildOverview([one, one]);
  assert.equal(overview.total, 10);
  assert.equal(overview.due, 2);
  assert.equal(overview.counts.mastered, 2);
  const html = overviewView(overview, 4);
  assert.match(html, /Objetivos que domina/);
  assert.match(html, /Por reforzar/);
  assert.match(html, /Repasos próximos/);
});

test("upcoming reviews are sorted, skip never-practised objectives and honour the limit", () => {
  const model = buildProgress(topic, states, null);
  const rows = upcomingReviews([model]);
  assert.deepEqual(rows.map((row) => row.title), ["Constituciones", "Ancón", "Independencia"]);
  assert.equal(upcomingReviews([model], 2).length, 2);
});

test("review dates read as friendly relative words, never VENCIDO", () => {
  assert.equal(reviewWhen({ isDue: true, at: NOW - 1 }, NOW), "Repaso pendiente");
  assert.equal(reviewWhen({ isDue: false, at: NOW + 3600000 }, NOW), "Mañana");
  assert.equal(reviewWhen({ isDue: false, at: NOW - 1 }, NOW), "Hoy");
  assert.equal(reviewWhen({ isDue: false, at: NOW + 3 * 86400000 }, NOW), "En 3 días");
  assert.equal(reviewWhen({ isDue: false, at: NOW + 30 * 86400000 }, NOW), "En 4 semanas");
  const model = buildProgress(topic, states, null);
  assert.doesNotMatch(upcomingView(upcomingReviews([model]), NOW), /vencid/i);
});

test("an empty upcoming list says so", () => {
  assert.match(upcomingView([], NOW), /Todavía no hay repasos programados/);
});

test("the stacked bar sizes segments by count and names them for screen readers", () => {
  const html = stackedBarView({ mastered: 3, good: 1, reinforce: 0, new: 0 }, 4);
  assert.match(html, /data-band="mastered" style="flex: 3"/);
  assert.doesNotMatch(html, /data-band="reinforce"/);
  assert.match(html, /aria-label="3 lo domina, 1 va bien"/);
});

test("goal markup escapes user text and uses friendly wording", () => {
  const html = goalProgressView(buildProgress(topic, states, { mean_score: 0.55 }));
  assert.match(html, /Historia &lt;2° Medio&gt;/);
  assert.doesNotMatch(html, /<2° Medio>/);
  assert.match(html, /55<small>%<\/small>/);
  assert.match(html, /1 repaso pendiente/);
  assert.match(html, /Aún sin practicar/);
  assert.match(html, /1 de 2 dominados/);
  assert.doesNotMatch(html, /vencid|débil/i);
});
