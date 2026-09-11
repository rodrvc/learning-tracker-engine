"use strict";

import { api } from "./api.js";
import { parseHash, buildHash } from "./router.js";
import { renderTopics } from "./views/topics.js";
import { renderMaterial } from "./views/material.js";
import { renderPractice } from "./views/practice.js";
import { renderProgress } from "./views/progress.js";

const content = document.getElementById("view");

function highlightNav(view) {
  document.querySelectorAll("nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === view);
  });
}

async function render() {
  const { view, param } = parseHash(location.hash);
  highlightNav(view);
  if (view === "topics") {
    await renderTopics(content, api, param);
  } else if (view === "material") {
    await renderMaterial(content, api, param);
  } else if (view === "practice") {
    await renderPractice(content, api, param);
  } else if (view === "progress") {
    await renderProgress(content, api, param);
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("DOMContentLoaded", () => {
  // Setting `location.hash` itself fires "hashchange", so rendering
  // unconditionally here too used to render twice per load - two concurrent
  // fetches, the first one's DOM nodes pulled out from under it. Only the
  // branch that does not already trigger the event renders directly.
  if (location.hash) {
    render();
  } else {
    location.hash = buildHash("topics");
  }
});
