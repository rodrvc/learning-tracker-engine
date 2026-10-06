"use strict";

import { ApiError } from "../api.js";
import {
  buildOverview,
  buildProgress,
  goalProgressView,
  overviewView,
  upcomingReviews,
  upcomingView,
} from "../progress.js";

// The Progreso tab (issue #74): how the person is doing, in words and bars a
// non-technical reader follows. It reads the same three endpoints the
// learning tree reads - topic detail, every objective's state, the summary -
// so there is no backend of its own to keep in step with the engine.
// `topicId`, when the route names one, shows that goal alone.
export async function renderProgress(container, api, topicId) {
  container.innerHTML = `
    <h2>Progreso</h2>
    <div id="progress-body"><p class="empty">Cargando...</p></div>
  `;
  const body = container.querySelector("#progress-body");
  try {
    const all = await api.listTopics();
    const topics = topicId ? all.filter((topic) => topic.topic_id === topicId) : all;
    if (!topics.length) {
      body.innerHTML = '<p class="empty">Todavía no hay metas con progreso para mostrar.</p>';
      return;
    }
    const models = await Promise.all(
      topics.map(async (topic) => {
        const [detail, states, summary] = await Promise.all([
          api.getTopic(topic.topic_id),
          api.getStates(topic.topic_id),
          api.getSummary(topic.topic_id).catch(() => null),
        ]);
        return buildProgress(detail, states, summary);
      }),
    );
    const upcoming = upcomingReviews(models);
    const now = Date.now();
    body.innerHTML = `
      ${overviewView(buildOverview(models), upcoming.length)}
      <h3>Cómo vas en cada materia</h3>
      ${models.map(goalProgressView).join("")}
      <h3 class="prog-section">Próximos repasos</h3>
      ${upcomingView(upcoming, now)}
    `;
  } catch (err) {
    body.innerHTML = "";
    const el = document.createElement("p");
    el.className = "error";
    el.textContent = err instanceof ApiError ? err.message : "Error inesperado.";
    body.appendChild(el);
  }
}
