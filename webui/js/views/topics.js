"use strict";

import { ApiError } from "../api.js";
import { escapeHtml, topicItem, objectiveItem } from "../format.js";

/** Renders the topics view: the list-and-create screen with no parameter,
 * or one topic's detail when `topicId` is given. */
export async function renderTopics(container, api, topicId) {
  if (topicId) {
    await renderDetail(container, api, topicId);
  } else {
    await renderList(container, api);
  }
}

async function renderList(container, api) {
  container.innerHTML = `
    <form id="create-topic-form" class="topic-form">
      <input id="topic-id-input" placeholder="id (ej: ai-103)" required />
      <input id="topic-name-input" placeholder="nombre" required />
      <button type="submit">Crear tópico</button>
    </form>
    <ul id="topics-list" class="topics-list"><li class="empty">Cargando...</li></ul>
    <div id="topics-feedback" role="alert"></div>
  `;
  const list = container.querySelector("#topics-list");
  const feedback = container.querySelector("#topics-feedback");
  const form = container.querySelector("#create-topic-form");

  async function load() {
    feedback.textContent = "";
    list.innerHTML = '<li class="empty">Cargando...</li>';
    try {
      const topics = await api.listTopics();
      list.innerHTML = topics.length
        ? topics.map(topicItem).join("")
        : '<li class="empty">Todavía no hay tópicos.</li>';
    } catch (err) {
      list.innerHTML = "";
      showError(feedback, err);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    feedback.textContent = "";
    const topicId = form.querySelector("#topic-id-input").value.trim();
    const name = form.querySelector("#topic-name-input").value.trim();
    try {
      await api.createTopic(topicId, name);
      form.reset();
      await load();
    } catch (err) {
      showError(feedback, err);
    }
  });

  await load();
}

async function renderDetail(container, api, topicId) {
  container.innerHTML = '<p id="topic-detail-body">Cargando...</p>';
  const body = container.querySelector("#topic-detail-body");
  try {
    const topic = await api.getTopic(topicId);
    body.outerHTML = `
      <a href="#/topics" class="back-link">&larr; Tópicos</a>
      <h2>${escapeHtml(topic.name)}</h2>
      <a href="#/material/${encodeURIComponent(topicId)}">Ver material</a>
      <a href="#/practice/${encodeURIComponent(topicId)}">Practicar</a>
      <ul class="objectives-list">
        ${
          topic.objectives.length
            ? topic.objectives.map(objectiveItem).join("")
            : '<li class="empty">Todavía no tiene objetivos.</li>'
        }
      </ul>
    `;
  } catch (err) {
    body.outerHTML = '<a href="#/topics" class="back-link">&larr; Tópicos</a><div id="topic-detail-error"></div>';
    showError(container.querySelector("#topic-detail-error"), err);
  }
}

function showError(container, err) {
  const message = err instanceof ApiError ? err.message : "Error inesperado.";
  const el = document.createElement("p");
  el.className = "error";
  el.textContent = message;
  container.appendChild(el);
}
