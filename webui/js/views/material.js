"use strict";

import { ApiError } from "../api.js";
import {
  materialItem,
  materialDetailView,
  titleFromFilename,
  generationSummary,
  describeGenerationError,
} from "../format.js";

/**
 * Renders the material view for one topic: upload a page of notes, list the
 * pages already there, open one and generate questions from it.
 *
 * There is no route without a topic - material always lives inside one - so
 * a missing `topicId` points back at the topics list instead of guessing.
 */
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

  // Generation's running/succeeded/failed state, keyed by material id and
  // held here rather than on the DOM. A re-render (reopening a material,
  // possibly a different one and back) throws the previous detail subtree
  // away; without this map that discarded the in-flight flag along with it,
  // which both hid whether a call was still running and let a second click
  // start a second paid one. `openMaterialId` is which material's panel is
  // on screen right now, so a call that resolves after the user has moved on
  // updates the map (nothing is lost - reopening shows the final state) but
  // does not repaint a panel that is no longer showing it.
  const generationState = new Map();
  let openMaterialId = null;

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      // Only fills fields that are still empty - the same rule title and
      // source already follow. The body is the one field a paste could
      // already be sitting in, so overwriting it unconditionally would
      // silently throw away typed work; this makes "pick a file" as safe as
      // the other two autofills instead of the odd one out.
      if (!bodyInput.value.trim()) bodyInput.value = text;
      if (!titleInput.value.trim()) titleInput.value = titleFromFilename(file.name);
      if (!sourceInput.value.trim()) sourceInput.value = file.name;
    } catch {
      uploadFeedback.textContent = "";
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
    detail.innerHTML = materialDetailView(material, generationState.get(material.material_id));
    detail
      .querySelector("#generate-button")
      .addEventListener("click", () => generate(material.material_id));
  }

  async function generate(materialId) {
    const current = generationState.get(materialId);
    if (current && current.running) return; // already running; nothing to start twice
    // Generation is slow and costs money: it has to be visible while it
    // runs, not just once it finishes or fails (ACU-266).
    generationState.set(materialId, {
      running: true,
      message: "Generando preguntas… puede tardar y tiene costo.",
      error: false,
    });
    paint(materialId);
    try {
      const result = await api.generateMaterial(topicId, materialId);
      generationState.set(materialId, {
        running: false,
        message: generationSummary(result),
        error: false,
      });
    } catch (err) {
      generationState.set(materialId, {
        running: false,
        message: describeGenerationError(err),
        error: true,
      });
    } finally {
      paint(materialId);
    }
  }

  /** Reflects `generationState` for `materialId` on screen, but only if its
   * panel is still the one open - see the note by `generationState` above. */
  function paint(materialId) {
    if (openMaterialId !== materialId) return;
    const state = generationState.get(materialId);
    const button = detail.querySelector("#generate-button");
    const feedback = detail.querySelector("#generate-feedback");
    if (!button || !feedback) return;
    button.disabled = Boolean(state && state.running);
    feedback.className = state && state.error ? "error" : "";
    feedback.textContent = (state && state.message) || "";
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    // Disabled for the whole request, not just while `await` is pending on
    // the next line: a material's id is minted server-side, so (unlike
    // creating a topic) a duplicate click's second POST cannot 409 on a
    // caller-supplied id - it just succeeds, and material has no delete to
    // undo it with.
    uploadButton.disabled = true;
    uploadFeedback.textContent = "Subiendo...";
    const title = titleInput.value.trim();
    const source = sourceInput.value.trim();
    const body = bodyInput.value;
    try {
      await api.uploadMaterial(topicId, { title, source, body });
      form.reset();
      uploadFeedback.textContent = "";
      await loadList();
    } catch (err) {
      // The backend decides what is valid (including the body size limit,
      // reported with the size in its own message) - shown as-is, never
      // replaced by a generic one here.
      uploadFeedback.textContent = "";
      showError(uploadFeedback, err);
    } finally {
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
