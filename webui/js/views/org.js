"use strict";

import { escapeHtml, levelLabel } from "../format.js";

// The teacher view (issue #75): a read-only table of the organization's
// members, one row per member and topic. Every number comes straight from
// `GET /org/progress`, which runs the engine's own summary over each member's
// data; nothing is computed here. Only an organization admin gets a 200 from
// that route, and the nav link to this view is only offered to them, but the
// server is what enforces it - a 403 here is shown as a plain message.
export async function renderOrg(container, api) {
  container.innerHTML = `
    <h2>Vista docente</h2>
    <p class="empty">Cargando...</p>
  `;
  let report;
  try {
    report = await api.getOrgProgress();
  } catch (err) {
    const message =
      err.status === 403
        ? "Esta vista es solo para docentes de la organización."
        : err.message;
    container.innerHTML = `<h2>Vista docente</h2><p class="error">${escapeHtml(message)}</p>`;
    return;
  }

  const rows = [];
  for (const member of report.members) {
    if (member.topics.length === 0) {
      rows.push(
        `<tr><td>${escapeHtml(member.display_name)}</td><td colspan="6" class="muted">Aún no tiene tópicos</td></tr>`,
      );
      continue;
    }
    for (const topic of member.topics) {
      rows.push(`<tr>
        <td>${escapeHtml(member.display_name)}</td>
        <td>${escapeHtml(topic.name)}</td>
        <td><span class="level-chip" data-level="${escapeHtml(topic.level)}">${escapeHtml(levelLabel(topic.level))}</span></td>
        <td class="num">${topic.total_objectives}</td>
        <td class="num">${topic.due_objectives}</td>
        <td class="num">${topic.unstarted_objectives}</td>
        <td class="num">${topic.total_attempts}</td>
      </tr>`);
    }
  }

  container.innerHTML = `
    <h2>Vista docente</h2>
    <p class="org-note">Solo lectura. Nivel típico = nivel mediano de los objetivos del tópico. "Por repasar" son los objetivos que ya toca repasar; "Sin practicar", los que nunca se han intentado.</p>
    ${
      report.members.length === 0
        ? '<p class="empty">Todavía no hay estudiantes en esta organización.</p>'
        : `<div class="org-table-wrap"><table class="org-table">
      <thead><tr>
        <th>Estudiante</th><th>Tópico</th><th>Nivel típico</th>
        <th class="num">Objetivos</th><th class="num">Por repasar</th>
        <th class="num">Sin practicar</th><th class="num">Intentos</th>
      </tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table></div>`
    }
  `;
}
