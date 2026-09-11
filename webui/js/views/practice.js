"use strict";

import { ApiError } from "../api.js";
import {
  practiceQuestionView,
  practiceResultView,
  practiceAlreadyRecordedView,
  describePracticeUnavailable,
} from "../format.js";
import { resolveKeyAction, isAlreadyRecorded, makeAttemptId } from "../practice-keys.js";

// Renders the practice view for one topic: one question at a time, answer
// it, see immediately whether it was right with the explanation, carry on
// (ACU-267). There is no route without a topic, same as material.js.
//
// State here (the current question, the selection, `phase`) is deliberately
// local to this call, not a module like material-state.js's generation
// tracker: losing it costs nothing. A next-question fetch is free to redo,
// and an in-flight answer is protected by its own `attempt_id` - a
// duplicate fire lands as the engine's own 409 ("already recorded" below),
// not a double-counted attempt. Unlike the material view's paid, slow
// generation call, so the same cross-render treatment does not apply here.
export async function renderPractice(container, api, topicId) {
  if (!topicId) {
    container.innerHTML =
      '<p class="empty-view">Elegí un tópico primero. <a href="#/topics">Ver tópicos</a></p>';
    return;
  }

  container.innerHTML = `
    <a href="#/topics/${encodeURIComponent(topicId)}" class="back-link">&larr; Tópico</a>
    <h2>Practicar</h2>
    <div id="practice-area"><p class="empty-view">Cargando...</p></div>
  `;
  const area = container.querySelector("#practice-area");

  // "answering" -> "submitting" -> "feedback" -> back to "answering" via a
  // fresh "loading". Every handler below checks `phase` first, and sets it
  // synchronously before the first `await`, so a second Enter or click
  // racing the first one has nothing left to act on.
  let phase = "loading";
  let question = null;
  let selectedKey = null;
  let attemptId = null;

  // On `document`, not `container`: right after a render nothing has focus
  // yet, and a listener on `container` only sees keys bubbling from one of
  // its own descendants - it would miss every question's first keypress.
  // Removed on the next hash change so it never outlives this render.
  //
  // A document-wide listener also sees keys meant elsewhere (review round
  // 1): Enter on a focused nav or back-link, or a Cmd/Ctrl/Alt shortcut.
  // Bailing when the target already owns Enter costs nothing - the option
  // and submit buttons produce the same action via their click handlers -
  // and `resolveKeyAction` itself refuses every modifier combination.
  function onKeydown(event) {
    if (event.target instanceof Element && event.target.closest("a, button, input, textarea, select")) {
      return;
    }
    const optionCount = question ? question.options.length : 0;
    const hasModifier = event.ctrlKey || event.metaKey || event.altKey;
    const action = resolveKeyAction(event.key, { phase, optionCount, hasModifier });
    if (!action) return;
    event.preventDefault();
    if (action.type === "select") select(question.options[action.index].key);
    else if (action.type === "submit") submit();
    else if (action.type === "next") loadNext();
  }
  function cleanup() {
    document.removeEventListener("keydown", onKeydown);
    window.removeEventListener("hashchange", cleanup);
  }
  document.addEventListener("keydown", onKeydown);
  window.addEventListener("hashchange", cleanup);

  function select(key) {
    if (phase !== "answering") return;
    selectedKey = key;
    paintQuestion();
  }

  function paintQuestion() {
    area.innerHTML = practiceQuestionView(question, {
      selectedKey,
      submitting: phase === "submitting",
    });
    area.querySelectorAll("[data-key]").forEach((button) => {
      button.addEventListener("click", () => select(button.dataset.key));
    });
    const submitButton = area.querySelector("#submit-answer");
    if (submitButton) submitButton.addEventListener("click", submit);
  }

  async function submit() {
    if (phase !== "answering") return;
    if (!selectedKey) {
      // A likely first keystroke here (review round 1): say why, not silence.
      paintQuestion();
      appendMessage("Elegí una opción antes de responder.");
      return;
    }
    phase = "submitting";
    paintQuestion();
    try {
      const answer = await api.answerQuestion(topicId, {
        question_id: question.question_id,
        attempt_id: attemptId,
        selected_key: selectedKey,
      });
      phase = "feedback";
      area.innerHTML = practiceResultView(answer);
    } catch (err) {
      if (isAlreadyRecorded(err)) {
        // Already recorded, not broken (SPEC C9): treated as success.
        phase = "feedback";
        area.innerHTML = practiceAlreadyRecordedView();
      } else {
        // Visible and retryable with the same `attemptId`: a retry that did
        // land server-side just meets the "already recorded" branch above.
        phase = "answering";
        paintQuestion();
        const message = err instanceof ApiError ? err.message : "Error inesperado.";
        appendMessage(`No se guardó la respuesta: ${message}`);
        return;
      }
    }
    area.querySelector("#next-question").addEventListener("click", loadNext);
  }

  function appendMessage(text) {
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = text;
    area.appendChild(p);
  }

  async function loadNext() {
    if (phase !== "feedback" && phase !== "loading") return;
    phase = "loading";
    area.innerHTML = '<p class="empty-view">Cargando...</p>';
    try {
      question = await api.nextQuestion(topicId);
      selectedKey = null;
      const crypto = globalThis.crypto;
      attemptId = makeAttemptId(crypto && crypto.randomUUID && crypto.randomUUID.bind(crypto));
      phase = "answering";
      paintQuestion();
    } catch (err) {
      phase = "unavailable";
      await paintUnavailable(err);
    }
  }

  async function paintUnavailable(err) {
    // The extra lookup only resolves the ambiguous 404 (see format.js);
    // skip it on an unknown topic (would just 404 again) and on a network
    // outage (status 0) - pointless in both, per review.
    let objectiveCount;
    const isUnknownTopic = err instanceof ApiError && err.message.startsWith("unknown topic:");
    if (err instanceof ApiError && err.status === 404 && !isUnknownTopic) {
      try {
        objectiveCount = (await api.getTopic(topicId)).objectives.length;
      } catch {
        objectiveCount = undefined; // best-effort refinement only; see format.js
      }
    }
    area.innerHTML = "";
    const p = document.createElement("p");
    p.className = "empty-view";
    p.textContent = describePracticeUnavailable(err, { objectiveCount, topicId });
    area.appendChild(p);
  }

  await loadNext();
}
