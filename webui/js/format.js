"use strict";

// Pure, DOM-free string builders so they are unit-testable under Node - and
// so escaping stays testable: a topic or objective name is user-entered and
// interpolated into markup, so a no-op escaper here would be stored XSS.

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

export function topicItem(topic) {
  return `<li><a href="#/topics/${encodeURIComponent(topic.topic_id)}">
      <span>${escapeHtml(topic.name)}</span>
      <span>${escapeHtml(topic.objective_count)} objetivos</span>
    </a></li>`;
}

export function objectiveItem(objective) {
  return `<li>${escapeHtml(objective.title)}</li>`;
}
