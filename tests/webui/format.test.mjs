// Unit tests for webui/js/format.js. escapeHtml must never silently
// regress to a no-op: a topic/objective name is user-entered and
// interpolated into markup, so that would be stored XSS, not a cosmetic bug.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  escapeHtml,
  topicItem,
  objectiveItem,
  formatDate,
  materialItem,
  generationSummary,
  describeGenerationError,
} from "../../webui/js/format.js";

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

test("formatDate keeps only the minute-precision, human part of the timestamp", () => {
  assert.equal(formatDate("2026-09-11T13:46:49.226000+00:00"), "2026-09-11 13:46");
});

test("materialItem escapes an attacker-controlled title and source", () => {
  const html = materialItem({
    material_id: "m1",
    title: "<script>alert(1)</script>",
    source: "<b>x</b>",
    created_at: "2026-09-11T13:46:49+00:00",
  });
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("&lt;script&gt;"), true);
});

test("materialItem carries the material id for the click handler to read", () => {
  const html = materialItem({
    material_id: "m 1",
    title: "t",
    source: "s",
    created_at: "2026-09-11T13:46:49+00:00",
  });
  assert.equal(html.includes('data-material-id="m 1"'), true);
});

test("generationSummary singularises a single question and omits objectives when none were written", () => {
  assert.equal(
    generationSummary({ questions_written: 1, objectives_written: 0 }),
    "1 pregunta generada.",
  );
});

test("generationSummary pluralises questions and objectives, and reports both", () => {
  assert.equal(
    generationSummary({ questions_written: 5, objectives_written: 2 }),
    "5 preguntas generadas (2 objetivos nuevos).",
  );
});

test("generationSummary singularises a single objective", () => {
  assert.equal(
    generationSummary({ questions_written: 3, objectives_written: 1 }),
    "3 preguntas generadas (1 objetivo nuevo).",
  );
});

test("describeGenerationError frames a 503 as a configuration problem, keeping the backend's detail", () => {
  assert.equal(
    describeGenerationError({ status: 503, message: "question generation is not configured: x" }),
    "Problema de configuración: question generation is not configured: x",
  );
});

test("describeGenerationError shows a non-503 failure's message unchanged", () => {
  assert.equal(
    describeGenerationError({ status: 502, message: "generation failed: timeout" }),
    "generation failed: timeout",
  );
});
