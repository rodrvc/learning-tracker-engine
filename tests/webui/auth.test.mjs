// Unit tests for webui/js/auth.js's DOM-free logic: the two pure functions,
// and mountAuth's no-op branch (auth switched off), which needs no document
// at all. The branch that actually loads Clerk's script and mounts its
// widgets is DOM- and network-heavy by nature and is checked by hand in the
// browser instead (see the PR description) rather than faked into a false
// sense of coverage here.

import { test } from "node:test";
import assert from "node:assert/strict";
import { clerkScriptUrl, authHeaders, mountAuth } from "../../webui/js/auth.js";

test("clerkScriptUrl builds Clerk's vanilla-JS bundle URL under the instance's frontend API", () => {
  assert.equal(
    clerkScriptUrl("https://example-app.clerk.accounts.example"),
    "https://example-app.clerk.accounts.example/npm/@clerk/clerk-js@5/dist/clerk.browser.js",
  );
});

test("authHeaders carries a bearer token when one is given", () => {
  assert.deepEqual(authHeaders("abc123"), { Authorization: "Bearer abc123" });
});

test("authHeaders adds no header at all for a missing token", () => {
  assert.deepEqual(authHeaders(null), {});
  assert.deepEqual(authHeaders(undefined), {});
  assert.deepEqual(authHeaders(""), {});
});

test("mountAuth is a no-op when auth is switched off: no script, onToken(null)", async () => {
  let receivedToken = "not called";
  const doc = {
    createElement() {
      throw new Error("must not load a script when auth is disabled");
    },
  };
  await mountAuth({ enabled: false }, null, (token) => {
    receivedToken = token;
  }, doc);
  assert.equal(receivedToken, null);
});
