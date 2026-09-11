// Unit tests for webui/js/api.js's request(), with `fetch` injected so
// nothing touches the network: a non-ok response must throw, a FastAPI 422
// list must become a readable message (not "[object Object]"), a network
// failure must throw rather than resolve, a 204 must not call .json(), and
// a caller's own headers must merge with the default instead of erasing it.

import { test } from "node:test";
import assert from "node:assert/strict";
import { request, detailFrom, ApiError } from "../../webui/js/api.js";

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
