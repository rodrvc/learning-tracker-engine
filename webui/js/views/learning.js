"use strict";

import { ApiError } from "../api.js";
import { buildTree, goalView, summaryProgress, unitsView } from "../tree.js";

// The learning tab (issue #49): every goal on one screen, each opening in
// place into its units and topics. It replaces three of the four old tabs
// at once - topic list, topic detail and the whole progress screen -
// because all three answered "where do I stand?" from three places.
//
// **Goal bars eager, units lazy.** The bar on a closed goal is the reason
// to open it, so it cannot wait for the click: one `/summary` per goal, all
// in flight together (~10 ms each, measured in #49). What is under it costs
// a topic detail plus every objective's state, and nobody reads twenty
// goals' worth at once, so it waits for the first open. A summary that
// fails leaves that goal without a bar instead of taking the page down.
//
// Creating a goal is a `<details>` at the bottom: it used to be the form at
// the top, which put the app's rarest action where its commonest belongs.
export async function renderLearning(container, api, topicId) {
  container.innerHTML = `
    <h2>Aprendiendo</h2>
    <div id="goals"><p class="empty">Cargando...</p></div>
    <details class="goal-create">
      <summary>Crear meta</summary>
      <form id="create-topic-form" class="topic-form">
        <input id="topic-id-input" placeholder="id (ej: ai-103)" required />
        <input id="topic-name-input" placeholder="nombre" required />
        <button type="submit">Crear meta</button>
      </form>
    </details>
    <div id="goals-feedback" role="alert"></div>
  `;
  const goals = container.querySelector("#goals");
  const feedback = container.querySelector("#goals-feedback");
  const form = container.querySelector("#create-topic-form");

  async function load() {
    feedback.textContent = "";
    goals.innerHTML = '<p class="empty">Cargando...</p>';
    let topics;
    try {
      topics = await api.listTopics();
    } catch (err) {
      goals.innerHTML = "";
      showError(feedback, err);
      return;
    }
    if (!topics.length) {
      goals.innerHTML = '<p class="empty">Todavía no hay metas.</p>';
      return;
    }
    const summaries = await Promise.all(
      topics.map((topic) => api.getSummary(topic.topic_id).catch(() => null)),
    );
    // `open` when the route names this goal, so `#/learning/<id>` - and the
    // `#/topics/<id>` and `#/progress/<id>` links that now redirect to it -
    // lands on that goal unfolded instead of on a list to hunt through.
    goals.innerHTML = topics
      .map((topic, i) =>
        goalView(
          { topicId: topic.topic_id, name: topic.name, progress: summaryProgress(summaries[i]) },
          '<p class="empty">Cargando...</p>',
          { mode: "read", open: topic.topic_id === topicId },
        ),
      )
      .join("");
    goals.querySelectorAll(".tree-goal").forEach((node) => {
      // "toggle", not a click on the summary: `<details>` opens by keyboard
      // too, and those users would be left staring at "Cargando...".
      node.addEventListener("toggle", () => {
        if (node.open) fillGoal(node, api);
      });
      if (node.open) fillGoal(node, api);
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    feedback.textContent = "";
    const id = form.querySelector("#topic-id-input").value.trim();
    const name = form.querySelector("#topic-name-input").value.trim();
    try {
      await api.createTopic(id, name);
      form.reset();
      await load();
    } catch (err) {
      showError(feedback, err);
    }
  });

  await load();
}

// Once per goal per render: `dataset.loaded` is what stops a second open
// from firing the same two calls. The material link lives here, inside the
// goal, which is the whole of "material stops being a top-level tab": it is
// something one does to a goal, not a place to go.
async function fillGoal(node, api) {
  if (node.dataset.loaded) return;
  node.dataset.loaded = "1";
  const body = node.querySelector(".goal-body");
  const goalId = node.dataset.topicId;
  try {
    const [topic, states] = await Promise.all([api.getTopic(goalId), api.getStates(goalId)]);
    body.innerHTML = `
      <p class="goal-actions">
        <a href="#/practice/${encodeURIComponent(goalId)}">Practicar</a>
        <a href="#/material/${encodeURIComponent(goalId)}">Material</a>
      </p>
      ${unitsView(buildTree(topic, states, null).units, { mode: "read" })}
    `;
  } catch (err) {
    // Re-openable: a goal whose fetch failed retries on the next open
    // rather than staying broken until the page is reloaded.
    delete node.dataset.loaded;
    body.innerHTML = "";
    showError(body, err);
  }
}

function showError(container, err) {
  const message = err instanceof ApiError ? err.message : "Error inesperado.";
  const el = document.createElement("p");
  el.className = "error";
  el.textContent = message;
  container.appendChild(el);
}
