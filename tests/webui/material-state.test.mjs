// Unit tests for webui/js/material-state.js: the state machine that has to
// survive a re-render of the material view (ACU-266 review - `renderMaterial`
// used to own this state itself, and the back-link/"Ver material" rebuild it
// on every visit). Besides the transitions, "survives a re-render" is tested
// by importing the module twice and checking the second import sees the
// first one's writes, the way two calls to `renderMaterial` would.

import { test } from "node:test";
import assert from "node:assert/strict";
import { createGenerationTracker, createUploadTracker } from "../../webui/js/material-state.js";

test("generation tracker: unknown material, then start/succeed/fail transitions", () => {
  const tracker = createGenerationTracker();
  assert.equal(tracker.get("m1"), undefined);
  tracker.start("m1", "Generando…");
  assert.deepEqual(tracker.get("m1"), { running: true, message: "Generando…", error: false });
  tracker.succeed("m1", "5 preguntas generadas.");
  assert.deepEqual(tracker.get("m1"), {
    running: false,
    message: "5 preguntas generadas.",
    error: false,
  });
  tracker.fail("m1", "Problema de configuración: x");
  assert.deepEqual(tracker.get("m1"), {
    running: false,
    message: "Problema de configuración: x",
    error: true,
  });
});

test("generation tracker keeps each material's state independent", () => {
  const tracker = createGenerationTracker();
  tracker.start("m1", "Generando…");
  tracker.succeed("m2", "1 pregunta generada.");
  assert.equal(tracker.get("m1").running, true);
  assert.equal(tracker.get("m2").running, false);
});

test("upload tracker: idle, then start/finish", () => {
  const tracker = createUploadTracker();
  assert.deepEqual(tracker.get(), { running: false, message: "" });
  tracker.start("Subiendo...");
  assert.deepEqual(tracker.get(), { running: true, message: "Subiendo..." });
  tracker.finish();
  assert.deepEqual(tracker.get(), { running: false, message: "" });
});

// The property the review's blocker turned on: `views/material.js` imports
// the pre-built `generationTracker`/`uploadTracker`, not the factories
// above, so that two calls to `renderMaterial` (two imports of this module,
// which the runtime resolves to the one already-evaluated module) observe
// the same state instead of each minting an empty one.
test("generationTracker and uploadTracker survive a re-render: a second import sees the first's writes", async () => {
  const firstRender = await import("../../webui/js/material-state.js");
  firstRender.generationTracker.start("survives", "Generando…");
  firstRender.uploadTracker.start("Subiendo...");
  const secondRender = await import("../../webui/js/material-state.js");
  assert.deepEqual(secondRender.generationTracker.get("survives"), {
    running: true,
    message: "Generando…",
    error: false,
  });
  assert.deepEqual(secondRender.uploadTracker.get(), { running: true, message: "Subiendo..." });
  secondRender.uploadTracker.finish();
});
