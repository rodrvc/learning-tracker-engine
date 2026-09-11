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

// A material's `created_at` is an ISO timestamp with an offset (e.g.
// "2026-09-11T13:46:49.226000+00:00"). Slicing rather than going through
// `Date`/`toLocaleString` keeps this pure and timezone-independent, which is
// what makes it worth unit testing without a browser.
export function formatDate(isoString) {
  return String(isoString).slice(0, 16).replace("T", " ");
}

export function materialItem(material) {
  return `<li><button type="button" class="material-item" data-material-id="${escapeHtml(
    material.material_id,
  )}">
      <span>${escapeHtml(material.title)}</span>
      <span>${escapeHtml(material.source)}</span>
      <span>${escapeHtml(formatDate(material.created_at))}</span>
    </button></li>`;
}

/**
 * How many questions (and objectives) one generation run produced, for the
 * feedback shown right after "Generar preguntas" succeeds.
 */
export function generationSummary({ questions_written, objectives_written }) {
  const questions =
    questions_written === 1 ? "1 pregunta generada" : `${questions_written} preguntas generadas`;
  if (!objectives_written) return `${questions}.`;
  const objectives =
    objectives_written === 1 ? "1 objetivo nuevo" : `${objectives_written} objetivos nuevos`;
  return `${questions} (${objectives}).`;
}

/**
 * Turns a generation failure into interface text, without inventing a
 * generic message that would hide what the backend actually said.
 *
 * A 503 means the backend has no API key configured - a configuration
 * problem, not a mistake by whoever clicked the button - so it is framed as
 * one while still showing the backend's own detail (already resolved by
 * `detailFrom`, so a FastAPI validation list never reaches here as
 * "[object Object]"). Every other status, including the 502 a failed
 * generation call returns, shows the backend's message unchanged: it is not
 * this function's place to guess a better one.
 */
export function describeGenerationError(err) {
  const message = (err && err.message) || "Error inesperado.";
  return err && err.status === 503 ? `Problema de configuración: ${message}` : message;
}

/**
 * A local file's name, stripped of its extension, as a starting point for a
 * material's title. Pure on purpose: it is the browser-side inference the
 * brief allows (saving a round trip), not a decision the server would make
 * differently, so it belongs next to the other DOM-free helpers rather than
 * inline in an event handler.
 */
export function titleFromFilename(filename) {
  return String(filename).replace(/\.[^./]+$/, "");
}

/**
 * One material's detail panel, including the "Generar preguntas" button and
 * its feedback line rendered in whatever state `generation` describes.
 *
 * Taking that state as a plain argument, rather than reading it off the DOM,
 * is what lets a re-render (reopening this same material while a generation
 * it started is still in flight) restore the running/succeeded/failed state
 * instead of losing it - see `views/material.js`, which is the only place
 * that owns the state itself.
 */
export function materialDetailView(material, generation) {
  const state = generation || { running: false, message: "", error: false };
  return `
      <article class="material-detail" data-material-id="${escapeHtml(material.material_id)}">
        <h3>${escapeHtml(material.title)}</h3>
        <p class="material-source">${escapeHtml(material.source)}</p>
        <pre class="material-body">${escapeHtml(material.body)}</pre>
        <button type="button" id="generate-button"${state.running ? " disabled" : ""}>Generar preguntas</button>
        <p id="generate-feedback" class="${state.error ? "error" : ""}">${escapeHtml(state.message || "")}</p>
      </article>
    `;
}
