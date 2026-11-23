"use strict";

// Demo identities for showing the teacher view without Clerk (issue #75).
//
// Only meaningful when the server runs with authentication OFF: that is the one
// mode in which it reads the `X-Dev-*` headers built here (web/auth.py). With
// authentication on the headers are ignored, so a stale choice stored in this
// browser cannot grant anything. The ids match `scripts/seed_demo_org.py`.
//
// Pure and DOM-free (unit tested under Node), apart from the storage object the
// caller hands in.

export const DEMO_ORG = "org_demo";

export const DEMO_IDENTITIES = [
  { id: "", label: "Usuario local (sin identidad)" },
  { id: "demo_teacher", label: "Docente Demo (docente)", org: DEMO_ORG, role: "org:admin", name: "Docente Demo" },
  { id: "demo_ana", label: "Ana Rojas (estudiante)", org: DEMO_ORG, role: "org:member", name: "Ana Rojas" },
  { id: "demo_bruno", label: "Bruno Soto (estudiante)", org: DEMO_ORG, role: "org:member", name: "Bruno Soto" },
  { id: "demo_carla", label: "Carla Munoz (estudiante)", org: DEMO_ORG, role: "org:member", name: "Carla Munoz" },
  { id: "demo_diego", label: "Diego Pino (estudiante)", org: DEMO_ORG, role: "org:member", name: "Diego Pino" },
];

const STORAGE_KEY = "lt-dev-identity";
const DEMO_FLAG_KEY = "lt-demo";

/** Headers for a chosen demo identity; none at all for the local user. */
export function devHeaders(identity) {
  if (!identity || !identity.id) return {};
  const headers = { "X-Dev-User": identity.id };
  if (identity.org) headers["X-Dev-Org"] = identity.org;
  if (identity.role) headers["X-Dev-Role"] = identity.role;
  if (identity.name) headers["X-Dev-Name"] = identity.name;
  return headers;
}

/** The selector is opt-in: `?demo=1` turns it on and the choice is remembered,
 * so a plain local run of the application looks exactly as it always did. */
export function demoEnabled(search, storage) {
  try {
    if (new URLSearchParams(search).get("demo") === "1") storage.setItem(DEMO_FLAG_KEY, "1");
    return storage.getItem(DEMO_FLAG_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadIdentity(storage) {
  try {
    const id = storage.getItem(STORAGE_KEY);
    return DEMO_IDENTITIES.find((identity) => identity.id === id) || DEMO_IDENTITIES[0];
  } catch {
    return DEMO_IDENTITIES[0];
  }
}

export function saveIdentity(storage, id) {
  try {
    storage.setItem(STORAGE_KEY, id);
  } catch {
    // A browser that refuses storage still works for this page load.
  }
}
