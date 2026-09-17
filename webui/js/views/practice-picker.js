"use strict";

import { ApiError } from "../api.js";
import { buildTree, goalView, summaryProgress, unitsView } from "../tree.js";
import { practiceButtonLabel, sameScope, scopeFromPick } from "../practice-scope.js";
import { renderPracticeSession } from "./practice.js";

// The practice tab (issue #49): the same tree the learning tab draws, in
// pick mode, plus one action button. Picking a row and practising it are
// two steps on purpose - a click that started a session would make the tree
// unbrowsable, and half the point of this screen is seeing where you stand
// before deciding what to drill.
//
// **Loading mirrors learning.js deliberately**: goal bars eager (one
// `/summary` per goal, all in flight), units lazy on the first open - the
// same data at the same cost, which is cheaper than a shared loader both
// tabs would have to parameterise by mode, title, actions and empty text.
//
// The session replaces this screen inside the same container rather than
// navigating: a selection is not representable in a hash (see practice.js),
// so a route would have to forget it.
export async function renderPractice(container, api, topicId, initialSelection = null) {
  // Handed back in when a session returns here: the picker re-renders from
  // scratch, so the selection travels as a value and is re-marked by
  // comparison, never as a node the re-render has already thrown away.
  let selection = initialSelection;

  container.innerHTML = `
    <h2>Practicar</h2>
    <p class="pick-help">Elegí una meta, una unidad o un objetivo. Sin elegir nada más fino, practicás lo que el motor diga que toca.</p>
    <button type="button" id="practice-start" disabled>${practiceButtonLabel(null)}</button>
    <div id="goals"><p class="empty">Cargando...</p></div>
    <div id="pick-feedback" role="alert"></div>
  `;
  const goals = container.querySelector("#goals");
  const feedback = container.querySelector("#pick-feedback");
  const startButton = container.querySelector("#practice-start");

  function paintAction() {
    startButton.textContent = practiceButtonLabel(selection);
    startButton.disabled = !selection;
  }

  // By value, over every button currently in the tree: a goal's units
  // arrive after its first open, so the selected one may not have existed
  // when it was picked (it does when the selection is restored on return).
  function markSelection() {
    goals.querySelectorAll(".pick").forEach((button) => {
      button.setAttribute("aria-pressed", String(sameScope(selection, scopeOf(button))));
    });
  }

  function select(button) {
    const scope = scopeOf(button);
    if (!scope) return;
    // A second click on the chosen row clears it: with no way to unselect,
    // the only way back to "the engine picks" would be reloading the tab.
    selection = sameScope(selection, scope) ? null : scope;
    markSelection();
    paintAction();
  }

  goals.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest(".pick") : null;
    if (!button) return;
    // Inside a <summary>: without this, choosing a goal or a unit would
    // also fold the row shut, which reads as the click having done
    // something else entirely.
    event.preventDefault();
    select(button);
  });

  startButton.addEventListener("click", () => {
    if (!selection) return;
    const chosen = selection;
    renderPracticeSession(container, api, chosen.topicId, chosen, () => {
      renderPractice(container, api, chosen.topicId, chosen);
    });
  });

  async function load() {
    feedback.textContent = "";
    let topics;
    try {
      topics = await api.listTopics();
    } catch (err) {
      goals.innerHTML = "";
      showError(feedback, err);
      return;
    }
    if (!topics.length) {
      goals.innerHTML =
        '<p class="empty">Todavía no hay metas. Creá una en Aprendiendo.</p>';
      return;
    }
    const summaries = await Promise.all(
      topics.map((topic) => api.getSummary(topic.topic_id).catch(() => null)),
    );
    // Which goal opens: the selection's own goal when there is one (coming
    // back from a session lands on what was being practised), otherwise the
    // one the route names (`#/practice/<id>`, the link inside a goal on the
    // learning tab), otherwise the only one there is.
    const wanted = (selection && selection.topicId) || topicId;
    const opened =
      topics.find((topic) => topic.topic_id === wanted) ||
      (topics.length === 1 ? topics[0] : null);
    goals.innerHTML = topics
      .map((topic, i) =>
        goalView(
          { topicId: topic.topic_id, name: topic.name, progress: summaryProgress(summaries[i]) },
          '<p class="empty">Cargando...</p>',
          { mode: "pick", open: opened !== null && topic.topic_id === opened.topic_id },
        ),
      )
      .join("");
    // Preselected rather than left empty, so the button offers the
    // unscoped practice the tab has always had ("lo que toca") instead of
    // demanding a choice before anything can be practised at all.
    if (!selection && opened) {
      selection = scopeFromPick("goal", { topicId: opened.topic_id, label: opened.name });
    }
    goals.querySelectorAll(".tree-goal").forEach((node) => {
      node.addEventListener("toggle", () => {
        if (node.open) fillGoal(node, api, markSelection);
      });
      if (node.open) fillGoal(node, api, markSelection);
    });
    markSelection();
    paintAction();
  }

  await load();
}

/** The scope one pick button stands for, read off the row it sits in: the
 * tree already labels every ancestor (`data-topic-id`, `data-domain`,
 * `data-objective-id`), so this is a lookup, and every rule about what may
 * be combined lives in `scopeFromPick`. */
function scopeOf(button) {
  const goal = button.closest(".tree-goal");
  const unit = button.closest(".tree-unit");
  const topic = button.closest(".tree-topic");
  return scopeFromPick(button.dataset.pick, {
    topicId: goal && goal.dataset.topicId,
    domain: unit && unit.dataset.domain,
    objectiveId: topic && topic.dataset.objectiveId,
    label: button.dataset.pickLabel,
  });
}

// Once per goal per render, same contract as learning.js's: `dataset.loaded`
// stops a second open from firing the same two calls, and a failed fetch
// clears it so the next open retries instead of staying broken.
async function fillGoal(node, api, onFilled) {
  if (node.dataset.loaded) return;
  node.dataset.loaded = "1";
  const body = node.querySelector(".goal-body");
  const goalId = node.dataset.topicId;
  try {
    const [topic, states] = await Promise.all([api.getTopic(goalId), api.getStates(goalId)]);
    body.innerHTML = unitsView(buildTree(topic, states, null).units, { mode: "pick" });
    onFilled();
  } catch (err) {
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
