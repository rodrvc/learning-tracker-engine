"use strict";

// State that has to outlive one render of the material view. `app.js` calls
// `renderMaterial` fresh on every `hashchange`, including the back-link to
// the topic and "Ver material" (the only way in), so anything declared
// inside `renderMaterial` is rebuilt empty on that trip - but a generation
// or an upload can still be running. A module is evaluated once no matter
// how many times something imports it (the guarantee `api.js`'s `ApiError`
// already relies on), so the trackers built once below are the one thing
// here a re-render does not throw away; `views/material.js` imports them
// rather than building its own. No DOM here: a state machine over plain
// objects, unit tested the way format.js is.

/** One material's generation state, keyed by material id. */
export function createGenerationTracker() {
  const byMaterialId = new Map();
  return {
    get: (materialId) => byMaterialId.get(materialId),
    start: (materialId, message) =>
      byMaterialId.set(materialId, { running: true, message, error: false }),
    succeed: (materialId, message) =>
      byMaterialId.set(materialId, { running: false, message, error: false }),
    fail: (materialId, message) =>
      byMaterialId.set(materialId, { running: false, message, error: true }),
  };
}

/** The upload form's in-flight state - one topic's material view has exactly
 * one upload form, so unlike generation this needs no key. */
export function createUploadTracker() {
  let state = { running: false, message: "" };
  return {
    get: () => state,
    start: (message) => {
      state = { running: true, message };
    },
    finish: () => {
      state = { running: false, message: "" };
    },
  };
}

// Built once, at import time: this is what makes the state survive a
// re-render, by giving every caller the same object instead of a fresh one.
export const generationTracker = createGenerationTracker();
export const uploadTracker = createUploadTracker();
