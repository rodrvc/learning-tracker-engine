"use strict";

// Clerk (ACU-278), wired the way the rest of this front end is: no build
// step, no bundler. `clerkScriptUrl` and `authHeaders` are pure and DOM-free,
// unit tested under Node (tests/webui/auth.test.mjs); `mountAuth` is the one
// function here that touches `document` and a third-party script, so it is
// exercised by hand in the browser instead (see the PR description).

/** Clerk serves its own vanilla-JS bundle from the instance's frontend API -
 * no npm registry involved, despite the `/npm/` path. */
export function clerkScriptUrl(frontendApi) {
  return `${frontendApi}/npm/@clerk/clerk-js@5/dist/clerk.browser.js`;
}

/** `Authorization` header for a request, or no header at all. A `Bearer`
 * with an empty or missing token is worse than sending none: it reads as an
 * attempt to authenticate rather than as its absence. */
export function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Loads Clerk for this instance, mounts its prebuilt sign-in form or user
 * button into `mountEl` depending on session state, and calls `onToken`
 * with either a token-fetching function (signed in) or `null` (signed out,
 * or auth switched off).
 *
 * `config` is `GET /auth/config`'s body (`web/app.py`): `{enabled,
 * publishableKey, issuer}`. When `enabled` is false, this returns
 * immediately, `onToken(null)`, and Clerk's script is never loaded - a
 * deployment that never configured Clerk pulls in no third-party code.
 */
export async function mountAuth(config, mountEl, onToken, doc = document) {
  if (!config.enabled) {
    onToken(null);
    return;
  }
  await loadScript(clerkScriptUrl(config.issuer), config.publishableKey, doc);
  const clerk = doc.defaultView.Clerk;
  await clerk.load();
  const render = () => {
    mountEl.innerHTML = "";
    if (clerk.session) {
      clerk.mountUserButton(mountEl);
      onToken(() => clerk.session.getToken());
    } else {
      clerk.mountSignIn(mountEl);
      onToken(null);
    }
  };
  clerk.addListener(render);
  render();
}

function loadScript(src, publishableKey, doc) {
  return new Promise((resolve, reject) => {
    const script = doc.createElement("script");
    script.async = true;
    script.crossOrigin = "anonymous";
    script.setAttribute("data-clerk-publishable-key", publishableKey);
    script.src = src;
    script.addEventListener("load", () => resolve());
    script.addEventListener("error", () => reject(new Error(`could not load ${src}`)));
    doc.head.appendChild(script);
  });
}
