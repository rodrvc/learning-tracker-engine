"use strict";

import { ApiError } from "../api.js";
import {
  escapeHtml,
  practiceQuestionView,
  practiceResultView,
  practiceAlreadyRecordedView,
} from "../format.js";
import {
  describeScopedUnavailable,
  practicingLabel,
  selectionSize,
} from "../practice-scope.js";
import {
  resolveKeyAction,
  targetOwnsKey,
  isAlreadyRecorded,
  makeAttemptId,
} from "../practice-keys.js";

// Renders one practice session: one question at a time, answer it, see
// immediately whether it was right with the explanation, carry on
// (ACU-267). Reached from the picker (views/practice-picker.js), never from
// a route of its own, because a session is about a *selection* and a hash
// cannot hold one honestly: `#/practice/<goal>` names a goal, not the units
// and objectives that were ticked inside it.
//
// **The selection is a parameter, not state.** Every `next` call in this
// render carries the same one (issue #49, a set of rows rather than a single
// one since issue #62), so "siguiente" after an answer stays inside what was
// chosen instead of quietly widening back to the whole goal, and the header
// says what that selection is - by count once it is more than one thing
// (practice-scope.js) - for as long as the session lasts.
//
// State here (the current question, the selection, `phase`) is deliberately
// local to this call, not a module like material-state.js's generation
// tracker: losing it costs nothing. A next-question fetch is free to redo,
// and an in-flight answer is protected by its own `attempt_id` - a
// duplicate fire lands as the engine's own 409 ("already recorded" below),
// not a double-counted attempt. Unlike the material view's paid, slow
// generation call, so the same cross-render treatment does not apply here.
export async function renderPracticeSession(container, api, topicId, selection, onChangeScope) {
  container.innerHTML = `
    <p class="practice-scope">
      <button type="button" id="change-scope" class="back-link">Elegir otra cosa</button>
      <span class="practice-scope-name">${escapeHtml(practicingLabel(selection))}</span>
    </p>
    <div id="practice-area"><p class="empty-view">Cargando...</p></div>
  `;
  const area = container.querySelector("#practice-area");
  container.querySelector("#change-scope").addEventListener("click", () => {
    cleanup();
    onChangeScope();
  });

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
  // A document-wide listener also sees keys meant elsewhere: Enter on a
  // focused nav or back-link, or a Cmd/Ctrl/Alt shortcut. What the focused
  // element keeps is `targetOwnsKey`'s call; all this does is read the DOM
  // to say what kind of element has focus.
  function targetKind(target) {
    if (!(target instanceof Element)) return "none";
    if (target.closest("input, textarea, select, [contenteditable]")) return "text-entry";
    if (target.closest("a, button")) return "activatable";
    return "none";
  }
  function onKeydown(event) {
    const optionCount = question ? question.options.length : 0;
    const hasModifier = event.ctrlKey || event.metaKey || event.altKey;
    const action = resolveKeyAction(event.key, { phase, optionCount, hasModifier });
    if (!action) return;
    if (targetOwnsKey(targetKind(event.target), action)) return;
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
      question = await api.nextQuestion(topicId, selection);
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
    // outage (status 0) - pointless in both, per review. Also skipped on a
    // narrowed selection, where the endpoint's own three 404s already say
    // which case it is (see practice-scope.js).
    let objectiveCount;
    const narrowed = selectionSize(selection) > 0;
    const isUnknownTopic = err instanceof ApiError && err.message.startsWith("unknown topic:");
    if (!narrowed && err instanceof ApiError && err.status === 404 && !isUnknownTopic) {
      try {
        objectiveCount = (await api.getTopic(topicId)).objectives.length;
      } catch {
        objectiveCount = undefined; // best-effort refinement only; see format.js
      }
    }
    area.innerHTML = "";
    const p = document.createElement("p");
    p.className = "empty-view";
    p.textContent = describeScopedUnavailable(err, { selection, objectiveCount, topicId });
    area.appendChild(p);
  }

  await loadNext();
}
