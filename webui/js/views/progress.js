"use strict";

import { ApiError } from "../api.js";
import {
  levelBreakdownView,
  dueListView,
  unstartedListView,
  progressActionView,
  describeProgressError,
} from "../format.js";

// RETIRED by issue #49 and no longer imported: the numbers live in the
// learning tree, and `#/progress/<id>` redirects there (router.js). Its
// removal takes its half of format.js and of progress-format.test.mjs with
// it, which did not fit this PR's diff budget - that is the follow-up.
//
// Renders the progress view for one topic (ACU-268): the level breakdown,
// what is due and what was never practised, each list with one honest way
// into practising.
//
// **Why the action is once per list, not once per row:** `GET
// /topics/{id}/practice/next` (web/routers/practice.py) picks the objective
// itself - due first, most overdue first, then unstarted - and skips any
// candidate with no stored question as it walks that order (HANDOFF.md:
// this repo has questions for only a fraction of its objectives), so not
// even the top row of `due` is a guaranteed match. A link beside a specific
// row would tell someone they are about to practise that objective, which
// would usually be false, and a per-list one is no better: due is walked
// before unstarted globally, so an action over the unstarted list would
// return an old objective whenever a due one has a question. See
// `progressActionView` in format.js for the single action this renders
// instead. Reimplementing the engine's own choice here to target a row for
// real would be the exact divergence SPEC exists to prevent - that stays
// the engine's, on a future `objective_id` parameter, not a client-side
// workaround.
//
// State here is nothing but the three fetched lists: there is no in-flight
// mutation this view starts (unlike material's generation, or practice's
// answer submit), so nothing here needs to survive a re-render - a
// `hashchange` back to this view just re-fetches, and that costs one
// read-only round trip, not a user's typed input or a paid call.
export async function renderProgress(container, api, topicId) {
  if (!topicId) {
    container.innerHTML =
      '<p class="empty-view">Elegí un tópico primero. <a href="#/topics">Ver tópicos</a></p>';
    return;
  }

  container.innerHTML = `
    <a href="#/topics/${encodeURIComponent(topicId)}" class="back-link">&larr; Tópico</a>
    <h2>Progreso</h2>
    <div id="progress-body"><p class="empty-view">Cargando...</p></div>
  `;
  const body = container.querySelector("#progress-body");

  try {
    const [topic, summary, due, unstarted] = await Promise.all([
      api.getTopic(topicId),
      api.getSummary(topicId),
      api.getDue(topicId),
      api.getUnstarted(topicId),
    ]);
    const titles = new Map(topic.objectives.map((o) => [o.objective_id, o.title]));
    const titleFor = (objectiveId) => titles.get(objectiveId);

    body.innerHTML = `
      <section>
        <h3>Reparto por nivel</h3>
        <ul class="level-breakdown">${levelBreakdownView(summary.by_level)}</ul>
      </section>
      ${progressActionView(topicId)}
      <section>
        <h3>Vencido (${due.length})</h3>
        ${dueListView(due, titleFor)}
      </section>
      <section>
        <h3>Nunca practicado (${unstarted.length})</h3>
        ${unstartedListView(unstarted, titleFor)}
      </section>
    `;
  } catch (err) {
    const message = err instanceof ApiError ? describeProgressError(err, { topicId }) : "Error inesperado.";
    body.innerHTML = "";
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = message;
    body.appendChild(p);
  }
}
