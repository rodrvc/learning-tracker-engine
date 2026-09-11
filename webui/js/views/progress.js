"use strict";

import { ApiError } from "../api.js";
import { levelBreakdownView, dueListView, unstartedListView, describeProgressError } from "../format.js";

// Renders the progress view for one topic (ACU-268): the level breakdown,
// what is due and what was never practised, each with a way into practising.
//
// **Why every "Practicar" link goes to `#/practice/{topicId}`, not to one
// objective:** `GET /topics/{id}/practice/next` (web/routers/practice.py)
// picks the objective itself - due first, most overdue first, then
// unstarted - and takes no objective id to narrow that choice. Reimplementing
// that choice here to jump straight to a row's own objective would be the
// exact divergence SPEC exists to prevent: this layer would be re-deciding
// what the engine already decides. So the direct path this view offers is
// into the practice flow that the engine itself will resolve to the most
// urgent objective - which, for the top row of the due list, is this row.
// If per-objective practice is ever wanted, it needs a new query parameter
// on that endpoint, not a client-side workaround.
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
      <section>
        <h3>Vencido (${due.length})</h3>
        ${dueListView(due, titleFor, topicId)}
      </section>
      <section>
        <h3>Nunca practicado (${unstarted.length})</h3>
        ${unstartedListView(unstarted, titleFor, topicId)}
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
