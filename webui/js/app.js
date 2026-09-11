"use strict";

import { api, setTokenProvider } from "./api.js";
import { mountAuth } from "./auth.js";
import { parseHash, buildHash } from "./router.js";
import { renderTopics } from "./views/topics.js";
import { renderMaterial } from "./views/material.js";
import { renderPractice } from "./views/practice.js";
import { renderProgress } from "./views/progress.js";

const content = document.getElementById("view");
const authSlot = document.getElementById("auth");

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
window.addEventListener("DOMContentLoaded", async () => {
  // Wired before the first render: `setTokenProvider` decides whether
  // every subsequent `api` call carries a session, and a page that starts
  // rendering before Clerk reports its state would race a call against it.
  try {
    const config = await api.getAuthConfig();
    await mountAuth(config, authSlot, (getToken) => {
      setTokenProvider(getToken);
      // A session starting or ending changes what every view is allowed to
      // see, so it re-renders the current one rather than leaving stale
      // data (or a stale 401) on screen.
      render();
    });
  } catch {
    // No `/auth/config` reachable is a backend problem, not a reason to
    // leave the page blank: every view below still shows its own error the
    // first time an `api` call fails.
  }
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
