"use strict";

import { api } from "./api.js";
import { parseHash, buildHash } from "./router.js";
import { renderTopics } from "./views/topics.js";

// The three views ACU-252 still owes. Declared here, by name, so a visit
// shows an honest "not built yet" instead of nothing - see router.js for why
// they are recognised routes rather than absent ones.
const STUB_LABELS = {
  material: "Material",
  practice: "Practicar",
  progress: "Progreso",
};

const content = document.getElementById("view");

function renderStub(view) {
  content.innerHTML = `<p class="empty-view">${STUB_LABELS[view]} todavía no está construido.</p>`;
}

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
  } else {
    renderStub(view);
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("DOMContentLoaded", () => {
  if (!location.hash) {
    location.hash = buildHash("topics");
  }
  render();
});
