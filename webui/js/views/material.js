"use strict";

import { ApiError } from "../api.js";
import { escapeHtml, materialItem, generationSummary, describeGenerationError } from "../format.js";

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
      <button type="submit">Subir página</button>
    </form>
    <div id="upload-feedback" role="alert"></div>
    <h3>Páginas subidas</h3>
    <ul id="material-list" class="material-list"><li class="empty">Cargando...</li></ul>
    <div id="material-detail"></div>
  `;

  const list = container.querySelector("#material-list");
  const detail = container.querySelector("#material-detail");
  const form = container.querySelector("#upload-form");
  const uploadFeedback = container.querySelector("#upload-feedback");
  const titleInput = container.querySelector("#material-title-input");
  const sourceInput = container.querySelector("#material-source-input");
  const bodyInput = container.querySelector("#material-body-input");
  const fileInput = container.querySelector("#material-file-input");

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    bodyInput.value = await file.text();
    if (!titleInput.value.trim()) {
      titleInput.value = file.name.replace(/\.[^.]+$/, "");
    }
    if (!sourceInput.value.trim()) {
      sourceInput.value = file.name;
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
    detail.innerHTML = "<p>Cargando...</p>";
    try {
      const material = await api.getMaterial(topicId, materialId);
      renderDetail(material);
    } catch (err) {
      detail.innerHTML = "";
      showError(detail, err);
    }
  }

  function renderDetail(material) {
    detail.innerHTML = `
      <article class="material-detail">
        <h3>${escapeHtml(material.title)}</h3>
        <p class="material-source">${escapeHtml(material.source)}</p>
        <pre class="material-body">${escapeHtml(material.body)}</pre>
        <button type="button" id="generate-button">Generar preguntas</button>
        <p id="generate-feedback"></p>
      </article>
    `;
    const generateButton = detail.querySelector("#generate-button");
    const generateFeedback = detail.querySelector("#generate-feedback");
    generateButton.addEventListener("click", async () => {
      generateButton.disabled = true;
      generateFeedback.className = "";
      // Generation is slow and costs money: it has to be visible while it
      // runs, not just once it finishes or fails (ACU-266).
      generateFeedback.textContent = "Generando preguntas… puede tardar y tiene costo.";
      try {
        const result = await api.generateMaterial(topicId, material.material_id);
        generateFeedback.textContent = generationSummary(result);
      } catch (err) {
        generateFeedback.className = "error";
        generateFeedback.textContent = describeGenerationError(err);
      } finally {
        generateButton.disabled = false;
      }
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    uploadFeedback.textContent = "";
    const title = titleInput.value.trim();
    const source = sourceInput.value.trim();
    const body = bodyInput.value;
    try {
      await api.uploadMaterial(topicId, { title, source, body });
      form.reset();
      await loadList();
    } catch (err) {
      // The backend decides what is valid (including the body size limit,
      // reported with the size in its own message) - shown as-is, never
      // replaced by a generic one here.
      showError(uploadFeedback, err);
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
