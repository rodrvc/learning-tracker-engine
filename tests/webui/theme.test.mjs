// Unit tests for the theme choice (webui/js/theme.js). What matters here is
// that the *default* is the brand's light theme and that nothing an OS or a
// corrupt storage value says can take that away - the bug this replaced was
// exactly that: `light-dark()` followed the OS, so a machine set to dark
// never showed the brand at all.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_THEME,
  THEMES,
  resolveTheme,
  nextTheme,
  themeToggleLabel,
} from "../../webui/js/theme.js";

test("the default theme is light - the brand system's own", () => {
  assert.equal(DEFAULT_THEME, "light");
});

test("a first visit, with nothing stored, resolves to light", () => {
  assert.equal(resolveTheme(null), "light");
  assert.equal(resolveTheme(undefined), "light");
});

test("a stored choice is honoured, both ways", () => {
  assert.equal(resolveTheme("dark"), "dark");
  assert.equal(resolveTheme("light"), "light");
});

test("a value this build does not know falls back to light, never to a blank", () => {
  // A blank would hand the choice back to the operating system, which is the
  // behaviour this module exists to stop.
  for (const junk of ["", "DARK", "auto", "system", "{}", 0, false]) {
    assert.equal(resolveTheme(junk), "light", `${JSON.stringify(junk)} did not fall back`);
  }
});

test("THEMES is exactly the two themes the stylesheet defines", () => {
  assert.deepEqual(THEMES, ["light", "dark"]);
});

test("toggling returns the other theme, and toggling twice returns the first", () => {
  assert.equal(nextTheme("light"), "dark");
  assert.equal(nextTheme("dark"), "light");
  assert.equal(nextTheme(nextTheme("light")), "light");
});

test("toggling from a junk value goes to dark, because junk resolves to light first", () => {
  assert.equal(nextTheme("nonsense"), "dark");
});

test("the toggle names the theme it switches to, not the one already showing", () => {
  // A control labelled with its current state reads as a status, not a button.
  assert.equal(themeToggleLabel("light"), "Tema oscuro");
  assert.equal(themeToggleLabel("dark"), "Tema claro");
});
