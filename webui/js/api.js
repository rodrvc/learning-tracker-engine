"use strict";

// Single place the API's base URL lives, so moving the front end to its own
// repository later is a one-line change here, not a hunt through every view.
const API_BASE_URL = "";

/** Raised for a network failure and a non-2xx response alike, so a caller can
 * always show `err.message` - a silent failure is worse than a visible one. */
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * FastAPI sends `detail` as a plain string for a handwritten 409/404/etc.,
 * but as a *list* of `{msg, loc, ...}` objects for a 422 validation error.
 * `detail || fallback` used to hand that list straight to `Error`, which
 * stringifies an object to `"[object Object]"` - visible, but empty of
 * information.
 */
export function detailFrom(body, fallback) {
  const detail = body && body.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((item) => (item && item.msg) || JSON.stringify(item)).join("; ");
  }
  return fallback;
}

export async function request(path, options = {}, fetchImpl = globalThis.fetch) {
  let response;
  try {
    response = await fetchImpl(`${API_BASE_URL}${path}`, {
      ...options,
      // After `...options`, not before: spreading it last is what makes a
      // caller's own `headers` merge with this default instead of erasing it.
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new ApiError("No se pudo conectar con el servidor.", 0);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = detailFrom(await response.json(), detail);
    } catch {
      // No JSON body to read the detail from; keep the status text.
    }
    throw new ApiError(detail, response.status);
  }
  return response.status === 204 ? null : response.json();
}

export const api = {
  listTopics: () => request("/topics"),
  createTopic: (topicId, name) =>
    request("/topics", {
      method: "POST",
      body: JSON.stringify({ topic_id: topicId, name }),
    }),
  getTopic: (topicId) => request(`/topics/${encodeURIComponent(topicId)}`),
  listMaterial: (topicId) => request(`/topics/${encodeURIComponent(topicId)}/material`),
  getMaterial: (topicId, materialId) =>
    request(`/topics/${encodeURIComponent(topicId)}/material/${encodeURIComponent(materialId)}`),
  uploadMaterial: (topicId, { title, source, body }) =>
    request(`/topics/${encodeURIComponent(topicId)}/material`, {
      method: "POST",
      body: JSON.stringify({ title, source, body }),
    }),
  generateMaterial: (topicId, materialId) =>
    request(
      `/topics/${encodeURIComponent(topicId)}/material/${encodeURIComponent(materialId)}/generate`,
      { method: "POST" },
    ),
  // No `correct_key`, no `explanation` in the response - the practice
  // endpoint withholds the solution on purpose (see web/routers/practice.py).
  nextQuestion: (topicId) => request(`/topics/${encodeURIComponent(topicId)}/practice/next`),
  answerQuestion: (topicId, { question_id, attempt_id, selected_key }) =>
    request(`/topics/${encodeURIComponent(topicId)}/practice/answer`, {
      method: "POST",
      body: JSON.stringify({ question_id, attempt_id, selected_key }),
    }),
  // The three progress reads (ACU-268): the level breakdown, what is due
  // and what was never practised. Every field on what they return is
  // already derived by the engine (web/routers/progress.py) - this client
  // adds no query parameter of its own that would let this layer pick a
  // date or a threshold in the engine's place.
  getSummary: (topicId) => request(`/topics/${encodeURIComponent(topicId)}/summary`),
  getDue: (topicId) => request(`/topics/${encodeURIComponent(topicId)}/objectives/due`),
  getUnstarted: (topicId) =>
    request(`/topics/${encodeURIComponent(topicId)}/objectives/unstarted`),
};

export { ApiError };
