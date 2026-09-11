"use strict";

import { ApiError } from "../api.js";
import {
  practiceQuestionView,
  practiceResultView,
  practiceAlreadyRecordedView,
  describePracticeUnavailable,
} from "../format.js";
import { resolveKeyAction } from "../practice-keys.js";

// Renders the practice view for one topic: one question at a time, answer
// it, see immediately whether it was right with the explanation, carry on
// (ACU-267). There is no route without a topic, same as material.js.
//
// State here (the current question, the selection, `phase`) is deliberately
// local to this call, not a module like material-state.js's generation
// tracker: losing it costs nothing. A next-question fetch is free to redo;
// an in-flight answer is protected by its own `attempt_id`, so even a
// duplicate fire from a stale render lands as the engine's own 409, not a
// double-counted attempt (see the "already recorded" branch below). That is
// a different cost than the material view's paid, slow generation call,
// which is why that state had to survive a re-render and this does not -
// per the review note on ACU-266: the same treatment does not apply here by
// analogy.
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

  // On `document`, not `container`: a keydown event bubbles up through
  // whatever has focus, and right after a render nothing does (the person
  // studying has not clicked anything yet - this view exists precisely so
  // they never have to). A listener on `container` would only ever see
  // keys typed into one of its own descendants, missing exactly the first
  // keypress of every question. Removed on the next hash change, so
  // navigating elsewhere - including to a different topic's practice view -
  // does not leave a stale listener acting on a question nobody sees.
  function onKeydown(event) {
    const optionCount = question ? question.options.length : 0;
    const action = resolveKeyAction(event.key, { phase, optionCount });
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
    if (phase !== "answering" || !selectedKey) return;
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
      if (err instanceof ApiError && err.status === 409) {
        // Already recorded, not broken (SPEC C9): treated as success.
        phase = "feedback";
        area.innerHTML = practiceAlreadyRecordedView();
      } else {
        // A silent failure here is the worst outcome this screen can
        // produce (someone answering on, believing it is being recorded),
        // so this stays visible and answerable again with the same
        // `attemptId` - a retry that actually succeeded server-side just
        // meets the 409 branch above instead.
        phase = "answering";
        paintQuestion();
        showSubmitError(err);
        return;
      }
    }
    area.querySelector("#next-question").addEventListener("click", loadNext);
  }

  function showSubmitError(err) {
    const message = err instanceof ApiError ? err.message : "Error inesperado.";
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = `No se guardó la respuesta: ${message}`;
    area.appendChild(p);
  }

  async function loadNext() {
    if (phase !== "feedback" && phase !== "loading") return;
    phase = "loading";
    area.innerHTML = '<p class="empty-view">Cargando...</p>';
    try {
      question = await api.nextQuestion(topicId);
      selectedKey = null;
      attemptId = crypto.randomUUID();
      phase = "answering";
      paintQuestion();
    } catch (err) {
      phase = "unavailable";
      await paintUnavailable(err);
    }
  }

  async function paintUnavailable(err) {
    let objectiveCount;
    try {
      objectiveCount = (await api.getTopic(topicId)).objectives.length;
    } catch {
      objectiveCount = undefined; // best-effort refinement only; see format.js
    }
    // Built via textContent, not innerHTML: the "unknown topic: X" branch
    // of describePracticeUnavailable echoes the topic id verbatim, which is
    // attacker-controllable through the URL hash.
    area.innerHTML = "";
    const p = document.createElement("p");
    p.className = "empty-view";
    p.textContent = describePracticeUnavailable(err, objectiveCount);
    area.appendChild(p);
  }

  await loadNext();
}
