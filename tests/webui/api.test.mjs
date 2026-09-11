// Unit tests for webui/js/api.js's request(), with `fetch` injected so
// nothing touches the network: a non-ok response must throw, a FastAPI 422
// list must become a readable message (not "[object Object]"), a network
// failure must throw rather than resolve, a 204 must not call .json(), and
// a caller's own headers must merge with the default instead of erasing it.

import { test } from "node:test";
import assert from "node:assert/strict";
import { request, detailFrom, ApiError, api } from "../../webui/js/api.js";

function fakeFetch({ ok, status = 200, statusText = "", json, throwJson = false }) {
  const calls = [];
  const impl = async (url, options) => {
    calls.push({ url, options });
    return { ok, status, statusText, json: async () => (throwJson ? Promise.reject() : json) };
  };
  impl.calls = calls;
  return impl;
}

test("a 2xx response resolves with the parsed body", async () => {
  const body = await request("/topics", {}, fakeFetch({ ok: true, json: { topic_id: "t1" } }));
  assert.deepEqual(body, { topic_id: "t1" });
});

test("a non-ok response throws ApiError instead of resolving", async () => {
  const fetchImpl = fakeFetch({ ok: false, status: 404, json: { detail: "unknown topic: t1" } });
  await assert.rejects(() => request("/topics/t1", {}, fetchImpl), ApiError);
  await assert.rejects(() => request("/topics/t1", {}, fetchImpl), {
    message: "unknown topic: t1",
  });
});

test("detailFrom joins a FastAPI 422 validation list into a readable message", () => {
  assert.equal(detailFrom({ detail: [{ msg: "field required" }] }, "fallback"), "field required");
});

test("detailFrom falls back when detail is missing or empty", () => {
  assert.equal(detailFrom({}, "fallback"), "fallback");
  assert.equal(detailFrom({ detail: [] }, "fallback"), "fallback");
});

test("a network failure throws ApiError rather than resolving", async () => {
  const fetchImpl = async () => Promise.reject(new TypeError("network down"));
  await assert.rejects(() => request("/topics", {}, fetchImpl), ApiError);
});

test("a 204 response resolves to null without reading a body", async () => {
  const fetchImpl = fakeFetch({ ok: true, status: 204, throwJson: true });
  assert.equal(await request("/topics/t1", { method: "DELETE" }, fetchImpl), null);
});

test("the request goes to API_BASE_URL + path", async () => {
  const fetchImpl = fakeFetch({ ok: true, json: [] });
  await request("/topics", {}, fetchImpl);
  assert.equal(fetchImpl.calls[0].url, "/topics");
});

test("a caller's own headers are merged with, not dropped by, the default", async () => {
  const fetchImpl = fakeFetch({ ok: true, json: {} });
  await request("/topics", { headers: { "X-Test": "1" } }, fetchImpl);
  const sent = fetchImpl.calls[0].options.headers;
  assert.equal(sent["Content-Type"], "application/json");
  assert.equal(sent["X-Test"], "1");
});

// The `api` object's material methods go through the default `fetch`
// (globalThis.fetch), unlike request()'s other tests above which inject
// their own - so these stub the global instead, and restore it after.
async function withStubbedFetch(json, run) {
  const original = globalThis.fetch;
  const fetchImpl = fakeFetch({ ok: true, json });
  globalThis.fetch = fetchImpl;
  try {
    await run(fetchImpl);
  } finally {
    globalThis.fetch = original;
  }
}

test("api.listMaterial requests the topic's material collection with GET", async () => {
  await withStubbedFetch([], async (fetchImpl) => {
    await api.listMaterial("t 1");
    assert.equal(fetchImpl.calls[0].url, "/topics/t%201/material");
    // Not a mutation of style: listing must not be the POST that creates a
    // material, or every page load would upload an empty one.
    assert.equal(fetchImpl.calls[0].options.method, undefined);
  });
});

test("api.getMaterial requests one material by id, both segments encoded", async () => {
  await withStubbedFetch({}, async (fetchImpl) => {
    await api.getMaterial("t 1", "m 1");
    assert.equal(fetchImpl.calls[0].url, "/topics/t%201/material/m%201");
  });
});

test("api.uploadMaterial posts title, source and body, the topic id encoded", async () => {
  await withStubbedFetch({}, async (fetchImpl) => {
    await api.uploadMaterial("t 1", { title: "T", source: "S", body: "B" });
    assert.equal(fetchImpl.calls[0].url, "/topics/t%201/material");
    assert.equal(fetchImpl.calls[0].options.method, "POST");
    assert.deepEqual(JSON.parse(fetchImpl.calls[0].options.body), {
      title: "T",
      source: "S",
      body: "B",
    });
  });
});

test("api.generateMaterial posts to the material's generate endpoint, both segments encoded", async () => {
  await withStubbedFetch({}, async (fetchImpl) => {
    await api.generateMaterial("t 1", "m 1");
    assert.equal(fetchImpl.calls[0].url, "/topics/t%201/material/m%201/generate");
    assert.equal(fetchImpl.calls[0].options.method, "POST");
  });
});
