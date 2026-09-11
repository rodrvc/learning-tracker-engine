// Unit tests for webui/js/format.js. escapeHtml must never silently
// regress to a no-op: a topic/objective name is user-entered and
// interpolated into markup, so that would be stored XSS, not a cosmetic bug.

import { test } from "node:test";
import assert from "node:assert/strict";
import { escapeHtml, topicItem, objectiveItem } from "../../webui/js/format.js";

test("escapeHtml neutralises every HTML-significant character", () => {
  assert.equal(escapeHtml(`<img onerror="x">&'`), "&lt;img onerror=&quot;x&quot;&gt;&amp;&#39;");
});

test("escapeHtml passes plain text through unchanged", () => {
  assert.equal(escapeHtml("AI-103"), "AI-103");
});

test("topicItem escapes an attacker-controlled topic name", () => {
  const html = topicItem({ topic_id: "t1", name: "<script>alert(1)</script>", objective_count: 2 });
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("&lt;script&gt;"), true);
});

test("topicItem links to the topic's own id, percent-encoded", () => {
  assert.equal(topicItem({ topic_id: "a b", name: "x", objective_count: 0 }).includes('href="#/topics/a%20b"'), true);
});

test("objectiveItem escapes an attacker-controlled objective title", () => {
  assert.equal(objectiveItem({ title: "<img src=x onerror=alert(1)>" }).includes("<img"), false);
});
