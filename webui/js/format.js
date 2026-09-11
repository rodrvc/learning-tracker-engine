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

// A local file's name, stripped of its extension: the browser-side
// inference the brief allows (saving a round trip), pure enough to belong
// here rather than inline in an event handler.
export function titleFromFilename(filename) {
  return String(filename).replace(/\.[^./]+$/, "");
}

// One material's detail panel, rendered in whatever `generation` state says
// (running/succeeded/failed/none) - a plain argument rather than the DOM, so
// a re-render can restore it. See material-state.js for where that state
// actually lives.
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

// The practice view (ACU-267): one question at a time, keyboard-first. A
// number picks an option, so each option carries its number visibly; the
// selected one is marked, never which one is *correct* - the endpoint never
// tells this layer that until an answer is submitted (and even then, only
// whether the chosen key was right, never the correct one - see
// web/routers/practice.py's AnswerOut).
export function practiceOptionsView(options, selectedKey) {
  return options
    .map(
      (option, index) => `<li>
        <button type="button" class="practice-option${
          option.key === selectedKey ? " selected" : ""
        }" data-key="${escapeHtml(option.key)}">
          <span class="option-number">${index + 1}</span>
          <span class="option-text">${escapeHtml(option.text)}</span>
        </button>
      </li>`,
    )
    .join("");
}

export function practiceQuestionView(question, { selectedKey, submitting }) {
  return `
    <article class="practice-question" data-question-id="${escapeHtml(question.question_id)}">
      <p class="practice-stem">${escapeHtml(question.stem)}</p>
      <ul class="practice-options">${practiceOptionsView(question.options, selectedKey)}</ul>
      <button type="button" id="submit-answer"${
        submitting || !selectedKey ? " disabled" : ""
      }>Responder (Enter)</button>
    </article>
  `;
}

// The graded result: correctness and the explanation the backend withheld
// until now, never the correct option itself (AnswerOut has no
// `correct_key` either - "correct" answers only whether the chosen key was
// right).
export function practiceResultView(answer) {
  return `
    <article class="practice-result">
      <p class="practice-verdict${answer.correct ? " correct" : " error"}">${
        answer.correct ? "Correcto" : "Incorrecto"
      }</p>
      <p class="practice-explanation">${escapeHtml(answer.explanation)}</p>
      <button type="button" id="next-question">Siguiente (Enter)</button>
    </article>
  `;
}

// A 409 means the engine already has this attempt recorded (SPEC C9) -
// success, not failure - but the response that would have carried
// `correct`/`explanation` is the one that never reached the browser, so
// there is nothing honest to grade here beyond saying so.
export function practiceAlreadyRecordedView() {
  return `
    <article class="practice-result">
      <p class="practice-verdict">Esta respuesta ya había quedado registrada.</p>
      <button type="button" id="next-question">Siguiente (Enter)</button>
    </article>
  `;
}

/**
 * Turns "nothing to practise" into the specific reason, per ACU-267: say
 * which nothing. The practice endpoint's two 404s are told apart by their
 * own wording (see web/routers/practice.py's `next_question`); an empty
 * topic (no objectives at all, `objectiveCount` falsy) is a third case
 * that endpoint cannot name by itself, since it 404s the same way a fully
 * caught-up topic does - the caller resolves it by also checking the
 * topic's objective count.
 */
export function describePracticeUnavailable(err, objectiveCount) {
  const message = (err && err.message) || "Error inesperado.";
  if (err && err.status === 404) {
    if (message.startsWith("unknown topic:")) return message;
    if (!objectiveCount) {
      return "Todavía no hay preguntas para este tema: subí material y generá preguntas.";
    }
    if (message.includes("no question for any due or unstarted")) {
      return "Todavía no hay preguntas para los objetivos pendientes.";
    }
    return "No hay nada vencido por ahora.";
  }
  return message;
}
