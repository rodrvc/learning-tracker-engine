"use strict";

import { api, setDevIdentity, setTokenProvider } from "./api.js";
import { mountAuth } from "./auth.js";
import { parseHash, buildHash } from "./router.js";
import { renderLearning } from "./views/learning.js";
import { renderMaterial } from "./views/material.js";
import { renderOrg } from "./views/org.js";
import { DEMO_IDENTITIES, demoEnabled, loadIdentity, saveIdentity } from "./dev-identity.js";
import { initTheme } from "./theme.js";

const content = document.getElementById("view");
const authSlot = document.getElementById("auth");

// Before the first render: the stored theme decides what `light-dark()`
// resolves to, so applying it late would show a flash of the other one.
initTheme(document.getElementById("theme-toggle"));

function highlightNav(view) {
  document.querySelectorAll("nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === view);
  });
}

async function render() {
  const { view, param } = parseHash(location.hash);
  highlightNav(view);
  if (view === "learning") {
    await renderLearning(content, api, param);
  } else if (view === "material") {
    await renderMaterial(content, api, param);
  } else if (view === "org") {
    await renderOrg(content, api);
  }
}

// The teacher view is a tab only for an organization admin. `/me` is a hint
// for what to show; the server still refuses everyone else on `/org/progress`.
async function syncTeacherLink() {
  const nav = document.querySelector("nav");
  nav.querySelector('a[data-view="org"]')?.remove();
  try {
    const me = await api.getMe();
    if (!me.is_teacher) return;
  } catch {
    return;
  }
  const link = document.createElement("a");
  link.href = buildHash("org");
  link.dataset.view = "org";
  link.textContent = "Vista docente";
  nav.appendChild(link);
  highlightNav(parseHash(location.hash).view);
}

// Demo-only (`?demo=1`, authentication off): pick who the page acts as, so the
// teacher view can be shown without Clerk. See dev-identity.js.
function mountDevSelector(slot) {
  const select = document.createElement("select");
  select.setAttribute("aria-label", "Identidad de demostración");
  for (const identity of DEMO_IDENTITIES) {
    const option = document.createElement("option");
    option.value = identity.id;
    option.textContent = identity.label;
    select.appendChild(option);
  }
  const current = loadIdentity(localStorage);
  select.value = current.id;
  setDevIdentity(current);
  select.addEventListener("change", async () => {
    const chosen = loadIdentity({ getItem: () => select.value });
    saveIdentity(localStorage, chosen.id);
    setDevIdentity(chosen);
    await syncTeacherLink();
    if (parseHash(location.hash).view === "org" && !chosen.id) location.hash = buildHash("learning");
    else render();
  });
  slot.appendChild(select);
}

window.addEventListener("hashchange", render);
window.addEventListener("DOMContentLoaded", async () => {
  // Wired before the first render: `setTokenProvider` decides whether
  // every subsequent `api` call carries a session, and a page that starts
  // rendering before Clerk reports its state would race a call against it.
  try {
    const config = await api.getAuthConfig();
    if (!config.enabled && demoEnabled(location.search, localStorage)) {
      mountDevSelector(authSlot);
    }
    await mountAuth(config, authSlot, (getToken) => {
      setTokenProvider(getToken);
      syncTeacherLink();
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
  await syncTeacherLink();
  // Setting `location.hash` itself fires "hashchange", so rendering
  // unconditionally here too used to render twice per load - two concurrent
  // fetches, the first one's DOM nodes pulled out from under it. Only the
  // branch that does not already trigger the event renders directly.
  if (location.hash) {
    render();
  } else {
    location.hash = buildHash("learning");
  }
});
