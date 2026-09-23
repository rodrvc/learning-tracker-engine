"use strict";

import { ApiError } from "../api.js";
import { buildTree, goalView, summaryProgress, unitsView } from "../tree.js";
import {
  dueActionLabel,
  emptySelection,
  rowState,
  selectedActionLabel,
  toggleRow,
} from "../practice-scope.js";
import { renderPracticeSession } from "./practice.js";

// The screen (issue #49, made the only one by issue #69): every goal, each
// opening in place into its units and topics. It replaced the topic list,
// the topic detail and the progress screen, and now the practice tab too -
// that tab drew this same tree with checkboxes on it, so "there are two
// places here" was never true: there is one place, and practising is
// something done to it.
//
// **A tick covers everything under it.** Ticking a goal shows its units and
// its objectives ticked, ticking a unit shows its objectives ticked, and a
// parent only some of whose children are ticked is drawn `indeterminate` -
// the three states a tree of checkboxes means everywhere else. What the
// request says is a separate question, answered in `practice-scope.js`: the
// display is derived from the selection, and the selection stays the
// coarsest description of the set, so a fully ticked goal still sends no
// parameters at all. This file only reads the shape of the tree off the DOM
// and hands it over.
//
// **Two actions, above the tree, never merged** (issue #71). "Practicar lo
// que toca" is unscoped and always there; "Practicar lo marcado" appears
// only once something is ticked. Two buttons on purpose: the screen briefly
// had one that relabelled itself with the selection, and that took the
// suggested path away the moment a row was ticked - and that path is the one
// most people want most days. The rows carry no action of their own any
// more, only a checkbox, so there is exactly one way to say "these" and
// exactly one way to say "whatever is due".
//
// **Practising is a mode, not a location.** Either action hands the
// container to `renderPracticeSession`, which hands it back by calling a
// callback that renders this screen afresh. Fresh, not restored: the bar
// that just moved is the payoff of answering, and it only moves if the
// summary and the states are read again. What does carry over is where you
// were - the goal, the units unfolded, the selection if there was one.
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
export async function renderLearning(container, api, topicId, resume = {}) {
  // What a returning session hands back, all by value: this render throws
  // away every node the last one made, so a selection or an unfolded unit
  // survives as something to re-apply, never as a node to reuse.
  let selection = resume.selection || null;
  const openUnits = new Set(resume.openUnits || []);

  container.innerHTML = `
    <h2>Aprendiendo</h2>
    <div class="practice-actions">
      <button type="button" id="practice-start">${dueActionLabel(null)}</button>
      <button type="button" id="practice-selected" class="practice-selected" hidden></button>
    </div>
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
  const startButton = container.querySelector("#practice-start");
  const selectedButton = container.querySelector("#practice-selected");
  // The goal the top button practises and the one rendered unfolded. Set by
  // `load`, the only place that knows what goals exist.
  let openGoal = null;

  // Out of the tree and into a session. The open units are read off the DOM
  // *before* the session replaces it, so coming back lands on the same rows
  // with new numbers on them.
  function startSession(chosen) {
    if (!chosen) return;
    // Matched in JavaScript, not with an attribute selector: a goal id is
    // user-chosen text, and a selector built out of it would need an
    // escaping rule this file has no business owning.
    const units = [...goals.querySelectorAll(".tree-goal")]
      .filter((node) => node.dataset.topicId === chosen.topicId)
      .flatMap((node) => [...node.querySelectorAll(".tree-unit[open]")])
      .map((node) => node.dataset.domain)
      .filter(Boolean);
    renderPracticeSession(container, api, chosen.topicId, chosen, () => {
      renderLearning(container, api, chosen.topicId, { selection, openUnits: units });
    });
  }

  // Both actions, painted together because the only thing that separates
  // them is whether anything is ticked. The first never changes what it
  // offers: no scope, so the engine chooses (SPEC section 5.2). The second
  // is `hidden` rather than disabled while nothing is - a dead button is a
  // promise with no way to collect it, and a pair where one is always greyed
  // out reads as one control with two states, which is the thing issue #71
  // undid.
  function paintAction() {
    const many = goals.querySelectorAll(".tree-goal").length > 1;
    startButton.textContent = openGoal
      ? dueActionLabel(openGoal.due, many ? openGoal.name : null)
      : dueActionLabel(null);
    startButton.disabled = !openGoal;
    selectedButton.hidden = !selection;
    selectedButton.textContent = selectedActionLabel(selection) || "";
  }

  startButton.addEventListener("click", () => {
    if (openGoal) startSession(emptySelection(openGoal.topicId, openGoal.name));
  });

  selectedButton.addEventListener("click", () => startSession(selection));

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
    // Which goal is unfolded, and which one the top button practises: the
    // one the route names, so `#/learning/<id>` - and the `#/topics/<id>`,
    // `#/progress/<id>` and `#/practice/<id>` links that redirect to it -
    // lands on that goal open rather than on a list to hunt through.
    //
    // With no route it is the first goal, never nothing: the default action
    // is the one thing this screen may not lose, and a disabled button on
    // arrival loses it. It is not a guess either, because the label names
    // the goal it would drill as soon as there is more than one.
    const wantedId = (selection && selection.topicId) || topicId;
    const index = topics.findIndex((topic) => topic.topic_id === wantedId);
    const openIndex = index >= 0 ? index : 0;
    openGoal = {
      topicId: topics[openIndex].topic_id,
      name: topics[openIndex].name,
      // The engine's own count off `/summary`, never recounted here.
      due: summaries[openIndex] ? summaries[openIndex].due_objectives : null,
    };
    goals.innerHTML = topics
      .map((topic, i) =>
        goalView(
          { topicId: topic.topic_id, name: topic.name, progress: summaryProgress(summaries[i]) },
          '<p class="empty">Cargando...</p>',
          { open: i === openIndex },
        ),
      )
      .join("");
    // Nothing is preselected on arrival. The unscoped call has a button of
    // its own now, so ticking the goal for the visitor would put a second
    // button on screen offering the same thing under another name.
    goals.querySelectorAll(".tree-goal").forEach((node) => {
      // "toggle", not a click on the summary: `<details>` opens by keyboard
      // too, and those users would be left staring at "Cargando...".
      node.addEventListener("toggle", () => {
        if (node.open) fillGoal(node, api, openUnits, wireRow);
      });
      if (node.open) fillGoal(node, api, openUnits, wireRow);
    });
    wireRow();
    paintAction();
  }

  // Every checkbox the tree currently shows, wired and marked. Called again
  // after each lazy fill, because a goal's units only exist once it has been
  // opened. Per checkbox, not delegated on `goals`, for one reason: these sit
  // inside a `<summary>`, and a delegated listener on an ancestor only runs
  // after the summary folded the row shut.
  //
  // One shape per goal, not one per checkbox: reading it inside the loop
  // would walk every objective of a goal once per row of that goal.
  function wireRow() {
    const shapes = new Map();
    goals.querySelectorAll(".pick-check").forEach((input) => {
      const goal = input.closest(".tree-goal");
      if (!shapes.has(goal)) shapes.set(goal, shapeOf(goal));
      // By coverage, over every checkbox in the tree: a ticked goal marks
      // rows that are nowhere in `items`, and the boxes have to show that.
      const state = rowState(selection, rowOf(input), shapes.get(goal));
      input.checked = state === "on";
      // Not an attribute and not a class: `indeterminate` is a property, and
      // it is what makes the browser draw its own third mark and tell a
      // screen reader "mixed" without a role invented here.
      input.indeterminate = state === "partial";
      if (input.dataset.wired) return;
      input.dataset.wired = "1";
      // A checkbox cannot `preventDefault` without also cancelling its own
      // tick, so this one stops the click instead - it runs first, so the
      // summary never sees it.
      input.addEventListener("click", (event) => event.stopPropagation());
      input.addEventListener("change", () => {
        selection = toggleRow(selection, rowOf(input), shapeOf(input.closest(".tree-goal")));
        wireRow();
        paintAction();
      });
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

/** The row one checkbox sits in, described for `practice-scope.js`: the tree
 * already labels every ancestor (`data-topic-id`, `data-goal-label`,
 * `data-domain`, `data-objective-id`), so this is a lookup. It decides
 * nothing - every rule about what a row stands for, and about what may be
 * combined with what, lives in `toggleRow`. */
function rowOf(control) {
  const goal = control.closest(".tree-goal");
  const unit = control.closest(".tree-unit");
  const topic = control.closest(".tree-topic");
  const topicId = goal && goal.dataset.topicId;
  return {
    kind: control.dataset.pick,
    topicId,
    goalLabel: (goal && goal.dataset.goalLabel) || topicId,
    domain: unit && unit.dataset.domain,
    objectiveId: topic && topic.dataset.objectiveId,
    label: control.dataset.pickLabel,
  };
}

/** What one goal holds, as `practice-scope.js` needs it to expand a ticked
 * parent into its children: its units, each with the objectives that can
 * actually be practised, and whether it also holds objectives filed under no
 * unit at all.
 *
 * Read off the DOM rather than kept beside it, because the DOM is where the
 * truth already is: a `<details>` that is folded still holds its rows, so a
 * goal that has been opened once has its whole shape here whether or not any
 * unit is unfolded. A goal never opened reports no unit, which is exactly
 * right - nothing under it can have been ticked either.
 *
 * The objectives are found through their checkboxes, so "selectable" needs
 * no second definition: a row with no stored question has no checkbox, and
 * therefore is not in the shape. */
function shapeOf(goal) {
  if (!goal) return { units: [], ungrouped: false };
  const units = [...goal.querySelectorAll(".tree-unit")].map((unit) => ({
    code: unit.dataset.domain || null,
    label: labelOf(unit.querySelector(".tree-row .pick-check")),
    objectives: [...unit.querySelectorAll(".tree-topic .pick-check")].map((check) => ({
      id: check.closest(".tree-topic").dataset.objectiveId,
      label: labelOf(check),
    })),
  }));
  return {
    units: units.filter((unit) => unit.code),
    // The "Sin unidad" bucket, which has no domain to be named by.
    ungrouped: units.some((unit) => !unit.code),
  };
}

function labelOf(check) {
  return (check && check.dataset.pickLabel) || "";
}

// Once per goal per render: `dataset.loaded` is what stops a second open
// from firing the same two calls. The material link lives here, inside the
// goal, which is the whole of "material stops being a top-level tab": it is
// something one does to a goal, not a place to go. Practising is not beside
// it: it is the pair of actions at the top, fed by the checkboxes below.
async function fillGoal(node, api, openUnits, onFilled) {
  if (node.dataset.loaded) return;
  node.dataset.loaded = "1";
  const body = node.querySelector(".goal-body");
  const goalId = node.dataset.topicId;
  try {
    const [topic, states] = await Promise.all([api.getTopic(goalId), api.getStates(goalId)]);
    body.innerHTML = `
      <p class="goal-actions">
        <a href="#/material/${encodeURIComponent(goalId)}">Material</a>
      </p>
      ${unitsView(buildTree(topic, states, null).units)}
    `;
    // Re-unfolded by domain, not by position: coming back from a session
    // lands on the unit whose bar just moved, already open, and a unit that
    // has since gone is simply not found rather than opening its neighbour.
    body.querySelectorAll(".tree-unit").forEach((unit) => {
      if (openUnits.has(unit.dataset.domain)) unit.open = true;
    });
    onFilled();
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
