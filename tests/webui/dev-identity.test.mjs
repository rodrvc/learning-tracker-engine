// Unit tests for webui/js/dev-identity.js (the demo identity selector's logic).

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEMO_IDENTITIES,
  devHeaders,
  demoEnabled,
  loadIdentity,
  saveIdentity,
} from "../../webui/js/dev-identity.js";

function memoryStorage(initial = {}) {
  const data = { ...initial };
  return {
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => {
      data[key] = String(value);
    },
  };
}

test("the local user sends no dev headers at all", () => {
  assert.deepEqual(devHeaders(null), {});
  assert.deepEqual(devHeaders(DEMO_IDENTITIES[0]), {});
});

test("a teacher sends user, org, role and name", () => {
  const teacher = DEMO_IDENTITIES.find((identity) => identity.id === "demo_teacher");
  assert.deepEqual(devHeaders(teacher), {
    "X-Dev-User": "demo_teacher",
    "X-Dev-Org": "org_demo",
    "X-Dev-Role": "org:admin",
    "X-Dev-Name": "Docente Demo",
  });
});

test("the selector is opt-in via ?demo=1 and then remembered", () => {
  const storage = memoryStorage();
  assert.equal(demoEnabled("", storage), false);
  assert.equal(demoEnabled("?demo=1", storage), true);
  assert.equal(demoEnabled("", storage), true);
});

test("a stored choice round-trips and an unknown one falls back to local", () => {
  const storage = memoryStorage();
  saveIdentity(storage, "demo_ana");
  assert.equal(loadIdentity(storage).id, "demo_ana");
  saveIdentity(storage, "someone-else");
  assert.equal(loadIdentity(storage).id, "");
});

test("a storage that throws still yields the local user", () => {
  const broken = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
  };
  assert.equal(loadIdentity(broken).id, "");
  assert.equal(demoEnabled("?demo=1", broken), false);
  saveIdentity(broken, "demo_ana");
});
