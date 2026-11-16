"use strict";

// Demo identities for showing the teacher view without Clerk (issue #75).
//
// Only meaningful when the server runs with authentication OFF: that is the one
// mode in which it reads the `X-Dev-*` headers built here (web/auth.py). With
// authentication on the headers are ignored, so a stale choice stored in this
// browser cannot grant anything. The ids match `scripts/seed_demo.py`.
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

/** `identities` defaults to the built-in list; demo mode (`/demo/config`)
 * passes the ones the server read from the seeded organizations. */
export function loadIdentity(storage, identities = DEMO_IDENTITIES) {
  try {
    const id = storage.getItem(STORAGE_KEY);
    return identities.find((identity) => identity.id === id) || identities[0];
  } catch {
    return identities[0];
  }
}

/** The switcher's entries for a `/demo/config` answer: the local user first,
 * then one group per organization. `flat` is every identity, for lookups. */
export function demoGroups(config) {
  const groups = (config.groups || []).filter((group) => group.identities.length > 0);
  return { local: DEMO_IDENTITIES[0], groups, flat: [DEMO_IDENTITIES[0], ...groups.flatMap((g) => g.identities)] };
}

export function saveIdentity(storage, id) {
  try {
    storage.setItem(STORAGE_KEY, id);
  } catch {
    // A browser that refuses storage still works for this page load.
  }
}
