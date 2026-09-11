"use strict";

import { ApiError } from "../api.js";
import {
  materialItem,
  materialDetailView,
  titleFromFilename,
  generationSummary,
  describeGenerationError,
} from "../format.js";
import { generationTracker, uploadTracker } from "../material-state.js";

// Renders the material view for one topic: upload a page of notes, list the
// pages already there, open one and generate questions from it. There is no
// route without a topic, so a missing `topicId` points back at the topics
// list. `generationTracker`/`uploadTracker` (material-state.js) are
// imported, not built here: this function reruns on every visit, including
// the back-link to the topic and the only way back in, so state it owned
// itself would be discarded on exactly those two links.
export async function renderMaterial(container, api, topicId) {
  if (!topicId) {
    container.innerHTML =
      '<p class="empty-view">Elegí un tópico primero. <a href="#/topics">Ver tópicos</a></p>';
    return;
  }

  container.innerHTML = `
    <a href="#/topics/${encodeURIComponent(topicId)}" class="back-link">&larr; Tópico</a>
    <h2>Material</h2>
    <form id="upload-form" class="material-form">
      <input id="material-title-input" placeholder="título" required />
      <input id="material-source-input" placeholder="fuente (ej: apuntes-clase-3.md)" required />
      <label for="material-file-input">Archivo markdown, o pegá el texto abajo</label>
      <input id="material-file-input" type="file" accept=".md,text/markdown,text/plain" />
      <textarea id="material-body-input" placeholder="texto de la página de apuntes" rows="8" required></textarea>
      <button type="submit" id="upload-button">Subir página</button>
    </form>
    <div id="upload-feedback" role="alert"></div>
    <h3>Páginas subidas</h3>
    <ul id="material-list" class="material-list"><li class="empty">Cargando...</li></ul>
    <div id="material-detail"></div>
  `;

  const list = container.querySelector("#material-list");
  const detail = container.querySelector("#material-detail");
  const form = container.querySelector("#upload-form");
  const uploadButton = container.querySelector("#upload-button");
  const uploadFeedback = container.querySelector("#upload-feedback");
  const titleInput = container.querySelector("#material-title-input");
  const sourceInput = container.querySelector("#material-source-input");
  const bodyInput = container.querySelector("#material-body-input");
  const fileInput = container.querySelector("#material-file-input");

  // Guards openMaterial()'s own race (clicking a second item before the
  // first one's fetch resolves) - scoped to this render on purpose, since a
  // newer render replaces these list buttons entirely.
  let openMaterialId = null;

  // An upload already in flight from before this render (started, then the
  // user came back via the back-link) has to look that way immediately.
  paintUpload();

  fileInput.addEventListener("change", async () => {
    uploadFeedback.textContent = "";
    const file = fileInput.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      // Only fills empty fields, so picking a file never discards a typed body.
      if (!bodyInput.value.trim()) bodyInput.value = text;
      if (!titleInput.value.trim()) titleInput.value = titleFromFilename(file.name);
      if (!sourceInput.value.trim()) sourceInput.value = file.name;
    } catch {
      const el = document.createElement("p");
      el.className = "error";
      el.textContent = "No se pudo leer el archivo.";
      uploadFeedback.appendChild(el);
    }
  });

  async function loadList() {
    list.innerHTML = '<li class="empty">Cargando...</li>';
    try {
      const materials = await api.listMaterial(topicId);
      list.innerHTML = materials.length
        ? materials.map(materialItem).join("")
        : '<li class="empty">Todavía no hay material.</li>';
      list.querySelectorAll("[data-material-id]").forEach((button) => {
        button.addEventListener("click", () => openMaterial(button.dataset.materialId));
      });
    } catch (err) {
      list.innerHTML = "";
      showError(list, err);
    }
  }

  async function openMaterial(materialId) {
    openMaterialId = materialId;
    detail.innerHTML = "<p>Cargando...</p>";
    try {
      const material = await api.getMaterial(topicId, materialId);
      // The user may have clicked a different page while this fetch was in
      // flight; that later click already owns `detail` and must win.
      if (openMaterialId !== materialId) return;
      renderDetail(material);
    } catch (err) {
      if (openMaterialId !== materialId) return;
      detail.innerHTML = "";
      showError(detail, err);
    }
  }

  function renderDetail(material) {
    detail.innerHTML = materialDetailView(material, generationTracker.get(material.material_id));
    detail
      .querySelector("#generate-button")
      .addEventListener("click", () => generate(material.material_id));
  }

  async function generate(materialId) {
    const current = generationTracker.get(materialId);
    if (current && current.running) return; // already running; nothing to start twice
    // Generation is slow and costs money: it must be visible while it runs.
    generationTracker.start(materialId, "Generando preguntas… puede tardar y tiene costo.");
    paintGeneration(materialId);
    try {
      const result = await api.generateMaterial(topicId, materialId);
      generationTracker.succeed(materialId, generationSummary(result));
    } catch (err) {
      generationTracker.fail(materialId, describeGenerationError(err));
    } finally {
      paintGeneration(materialId);
    }
  }

  // Looked up fresh via `container` (app.js's one stable #view element,
  // shared by every render), not the closure's `detail`: a generate() call
  // started before a back-link/forward round trip must resolve against
  // whichever render is current, not the detached one it began in.
  function paintGeneration(materialId) {
    const article = container.querySelector("#material-detail article");
    if (!article || article.dataset.materialId !== materialId) return;
    const state = generationTracker.get(materialId);
    article.querySelector("#generate-button").disabled = Boolean(state && state.running);
    const feedback = article.querySelector("#generate-feedback");
    feedback.className = state && state.error ? "error" : "";
    feedback.textContent = (state && state.message) || "";
  }

  /** Reflects `uploadTracker` on the (freshly rendered) upload button. */
  function paintUpload() {
    const state = uploadTracker.get();
    uploadButton.disabled = state.running;
    uploadFeedback.textContent = state.running ? state.message : "";
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (uploadTracker.get().running) return; // already running; nothing to start twice
    // A material's id is minted server-side, so a duplicate POST cannot 409
    // like a topic's would - it just succeeds, with no delete to undo it.
    uploadTracker.start("Subiendo...");
    paintUpload();
    const title = titleInput.value.trim();
    const source = sourceInput.value.trim();
    const body = bodyInput.value;
    try {
      await api.uploadMaterial(topicId, { title, source, body });
      uploadFeedback.textContent = "";
      form.reset();
      await loadList();
    } catch (err) {
      // Shown as-is (e.g. the backend's 413 with its own size), not replaced.
      uploadFeedback.textContent = "";
      showError(uploadFeedback, err);
    } finally {
      uploadTracker.finish();
      uploadButton.disabled = false;
    }
  });

  await loadList();
}

function showError(container, err) {
  const message = err instanceof ApiError ? err.message : "Error inesperado.";
  const el = document.createElement("p");
  el.className = "error";
  el.textContent = message;
  container.appendChild(el);
}
