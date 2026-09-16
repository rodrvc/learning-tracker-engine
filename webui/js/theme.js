"use strict";

// The theme choice. Acuaria Labs' system is the light one by decision, so
// light is what this application *is* - not "whatever the operating system
// happens to be set to". `light-dark()` keyed off the OS preference meant a
// machine in dark mode never saw the brand at all.
//
// The dark theme stays, but it is now a choice someone makes here and it is
// remembered. The resolution is a pure function so it is testable under the
// Node runner without a DOM, which is where this repo puts logic like this.

export const THEMES = ["light", "dark"];
export const DEFAULT_THEME = "light";
export const STORAGE_KEY = "learning-tracker:theme";

/** The theme to use given whatever was stored, which may be anything at all:
 * absent on a first visit, or a stale value from an older build. Anything not
 * a theme this build knows resolves to the default rather than to a blank
 * attribute that would silently hand control back to the OS. */
export function resolveTheme(stored) {
  return THEMES.includes(stored) ? stored : DEFAULT_THEME;
}

export function nextTheme(current) {
  return resolveTheme(current) === "dark" ? "light" : "dark";
}

/** What the toggle should say and announce. It names the theme it switches
 * *to*, because a control labelled with the state it is already in reads as
 * a status, not as a button. */
export function themeToggleLabel(current) {
  return nextTheme(current) === "dark" ? "Tema oscuro" : "Tema claro";
}

// --- The DOM edge, kept to these three functions ------------------------

function readStored() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private windows and blocked site data throw on access. A theme is a
    // convenience; losing it must not take the page down with it.
    return null;
  }
}

export function applyTheme(theme, button) {
  const resolved = resolveTheme(theme);
  document.documentElement.dataset.theme = resolved;
  if (button) {
    button.textContent = themeToggleLabel(resolved);
    button.setAttribute("aria-label", `Cambiar a ${themeToggleLabel(resolved).toLowerCase()}`);
  }
  return resolved;
}

export function initTheme(button) {
  let current = applyTheme(readStored(), button);
  if (!button) return;
  button.addEventListener("click", () => {
    current = applyTheme(nextTheme(current), button);
    try {
      localStorage.setItem(STORAGE_KEY, current);
    } catch {
      // Unwritable storage means the choice lasts this page only, which is
      // better than refusing to switch at all.
    }
  });
}
