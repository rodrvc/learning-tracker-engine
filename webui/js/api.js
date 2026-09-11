"use strict";

// The single place the API's base URL lives. Every call goes through
// `request` below, so moving the front end to its own repository later - or
// pointing it at a different backend - is a one-line change here, not a hunt
// through every view.
const API_BASE_URL = "";

/** Raised for both network failures and non-2xx responses, so a caller can
 * always show `err.message` to the person instead of swallowing the
 * failure - a silent failure is worse than a visible one. */
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError("No se pudo conectar con el servidor.", 0);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
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
};

export { ApiError };
