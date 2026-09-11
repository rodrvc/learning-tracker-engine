// Unit tests for webui/js/format.js. escapeHtml must never silently regress
// to a no-op: user-entered fields are interpolated into markup, so that
// would be stored XSS. Each interpolated field gets its own assertion, even
// when several share a test, so dropping any one escapeHtml call fails.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  escapeHtml,
  topicItem,
  objectiveItem,
  formatDate,
  materialItem,
  materialDetailView,
  titleFromFilename,
  generationSummary,
  describeGenerationError,
  practiceOptionsView,
  practiceQuestionView,
  practiceResultView,
  practiceAlreadyRecordedView,
  describePracticeUnavailable,
} from "../../webui/js/format.js";

test("escapeHtml neutralises every HTML-significant character", () => {
  assert.equal(escapeHtml(`<img onerror="x">&'`), "&lt;img onerror=&quot;x&quot;&gt;&amp;&#39;");
});

test("escapeHtml passes plain text through unchanged", () => {
  assert.equal(escapeHtml("AI-103"), "AI-103");
});

test("topicItem escapes an attacker-controlled name and objective_count", () => {
  const html = topicItem({ topic_id: "t1", name: "<script>n</script>", objective_count: "<b>2</b>" });
  assert.equal(html.includes("<script>n</script>"), false);
  assert.equal(html.includes("&lt;script&gt;n&lt;/script&gt;"), true);
  assert.equal(html.includes("<b>2</b>"), false);
  assert.equal(html.includes("&lt;b&gt;2&lt;/b&gt;"), true);
});

test("topicItem links to the topic's own id, percent-encoded", () => {
  assert.equal(topicItem({ topic_id: "a b", name: "x", objective_count: 0 }).includes('href="#/topics/a%20b"'), true);
});

test("objectiveItem escapes an attacker-controlled objective title", () => {
  // Both halves on purpose: asserting only the absence of the raw tag passes
  // just as happily when the title is dropped from the markup altogether.
  const html = objectiveItem({ title: "<img src=x onerror=alert(1)>" });
  assert.equal(html.includes("<img"), false);
  assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));
});

test("formatDate keeps only the minute-precision, human part of the timestamp", () => {
  assert.equal(formatDate("2026-09-11T13:46:49.226000+00:00"), "2026-09-11 13:46");
});

test("materialItem escapes title, source, the formatted date, and a material id that would break out of the data attribute", () => {
  const html = materialItem({
    material_id: '"><script>i</script>',
    title: "<script>t</script>",
    source: "<b>s</b>",
    created_at: "<img>xxxxxxxxxxxxxxxx",
  });
  assert.equal(html.includes("<script>t</script>"), false);
  assert.equal(html.includes("&lt;script&gt;t&lt;/script&gt;"), true);
  assert.equal(html.includes("<b>s</b>"), false);
  assert.equal(html.includes("&lt;b&gt;s&lt;/b&gt;"), true);
  assert.equal(html.includes("<img>"), false);
  assert.equal(html.includes("&lt;img&gt;"), true);
  assert.equal(html.includes("<script>i</script>"), false);
  assert.equal(html.includes('data-material-id="&quot;&gt;&lt;script&gt;i&lt;/script&gt;"'), true);
});

test("materialItem carries the material id for the click handler to read", () => {
  const html = materialItem({ material_id: "m 1", title: "t", source: "s", created_at: "2026-09-11T13:46:49+00:00" });
  assert.equal(html.includes('data-material-id="m 1"'), true);
});

test("titleFromFilename strips a single extension", () => {
  assert.equal(titleFromFilename("apuntes-clase-3.md"), "apuntes-clase-3");
});

test("titleFromFilename strips only the last extension, keeping earlier dots", () => {
  assert.equal(titleFromFilename("v1.2.notes.md"), "v1.2.notes");
});

test("titleFromFilename returns a name with no extension unchanged", () => {
  assert.equal(titleFromFilename("apuntes"), "apuntes");
});

test("materialDetailView escapes title, source, body, the message, and a material id that would break out of the data attribute", () => {
  const html = materialDetailView(
    {
      material_id: '"><script>i</script>',
      title: "<script>t</script>",
      source: "<b>s</b>",
      body: "<script>alert(document.cookie)</script>",
    },
    { running: false, message: "<script>m</script>", error: true },
  );
  assert.equal(html.includes("<script>t</script>"), false);
  assert.equal(html.includes("&lt;script&gt;t&lt;/script&gt;"), true);
  assert.equal(html.includes("<b>s</b>"), false);
  assert.equal(html.includes("&lt;b&gt;s&lt;/b&gt;"), true);
  assert.equal(html.includes("<script>alert(document.cookie)</script>"), false);
  assert.equal(html.includes("&lt;script&gt;alert(document.cookie)&lt;/script&gt;"), true);
  assert.equal(html.includes("<script>m</script>"), false);
  assert.equal(html.includes("&lt;script&gt;m&lt;/script&gt;"), true);
  assert.equal(html.includes("<script>i</script>"), false);
  assert.equal(html.includes('data-material-id="&quot;&gt;&lt;script&gt;i&lt;/script&gt;"'), true);
});

test("materialDetailView with no generation state renders an enabled button and empty feedback", () => {
  const html = materialDetailView({ material_id: "m1", title: "t", source: "s", body: "b" });
  assert.equal(html.includes("disabled"), false);
  assert.equal(html.includes('<p id="generate-feedback" class="">'), true);
});

test("materialDetailView disables the button while generation is running", () => {
  const html = materialDetailView(
    { material_id: "m1", title: "t", source: "s", body: "b" },
    { running: true, message: "Generando preguntas… puede tardar y tiene costo.", error: false },
  );
  assert.equal(html.includes('id="generate-button" disabled'), true);
  assert.equal(html.includes("Generando preguntas"), true);
});

test("materialDetailView marks a failed generation's feedback as an error and re-enables the button", () => {
  const html = materialDetailView(
    { material_id: "m1", title: "t", source: "s", body: "b" },
    { running: false, message: "Problema de configuración: x", error: true },
  );
  assert.equal(html.includes('id="generate-button" disabled'), false);
  assert.equal(html.includes('class="error"'), true);
  assert.equal(html.includes("Problema de configuración: x"), true);
});

test("generationSummary singularises a single question and omits objectives when none were written", () => {
  assert.equal(generationSummary({ questions_written: 1, objectives_written: 0 }), "1 pregunta generada.");
});

test("generationSummary pluralises questions and objectives, and reports both", () => {
  assert.equal(generationSummary({ questions_written: 5, objectives_written: 2 }), "5 preguntas generadas (2 objetivos nuevos).");
});

test("generationSummary singularises a single objective", () => {
  assert.equal(generationSummary({ questions_written: 3, objectives_written: 1 }), "3 preguntas generadas (1 objetivo nuevo).");
});

// Guards `=== 1` from being loosened to `<= 1`, which the count-of-5 test
// above does not catch (5 <= 1 is false, so that mutant stays plural there).
test("generationSummary pluralises zero questions and omits objectives", () => {
  assert.equal(generationSummary({ questions_written: 0, objectives_written: 0 }), "0 preguntas generadas.");
});

test("describeGenerationError frames a 503 as a configuration problem, keeping the backend's detail", () => {
  assert.equal(describeGenerationError({ status: 503, message: "question generation is not configured: x" }), "Problema de configuración: question generation is not configured: x");
});

test("describeGenerationError shows a non-503 failure's message unchanged", () => {
  assert.equal(describeGenerationError({ status: 502, message: "generation failed: timeout" }), "generation failed: timeout");
});

test("practiceOptionsView numbers every option and escapes an attacker-controlled key and text", () => {
  const html = practiceOptionsView(
    [
      { key: '"><script>k</script>', text: "<b>opt a</b>" },
      { key: "b", text: "opt b" },
    ],
    null,
  );
  assert.equal(html.includes("<script>k</script>"), false);
  assert.equal(html.includes("&lt;script&gt;k&lt;/script&gt;"), true);
  assert.equal(html.includes("<b>opt a</b>"), false);
  assert.equal(html.includes("&lt;b&gt;opt a&lt;/b&gt;"), true);
  assert.equal((html.match(/option-number">1</) || []).length, 1);
  assert.equal((html.match(/option-number">2</) || []).length, 1);
});

test("practiceOptionsView marks only the selected option, by key", () => {
  const html = practiceOptionsView(
    [
      { key: "a", text: "A" },
      { key: "b", text: "B" },
    ],
    "b",
  );
  assert.equal(html.includes('class="practice-option" data-key="a"'), true);
  assert.equal(html.includes('class="practice-option selected" data-key="b"'), true);
});

test("practiceQuestionView disables the submit button until an option is selected", () => {
  const question = {
    question_id: "q1",
    stem: "2+2?",
    options: [{ key: "a", text: "4" }],
  };
  const withoutSelection = practiceQuestionView(question, { selectedKey: null, submitting: false });
  assert.equal(withoutSelection.includes('id="submit-answer" disabled'), true);
  const withSelection = practiceQuestionView(question, { selectedKey: "a", submitting: false });
  assert.equal(withSelection.includes('id="submit-answer" disabled'), false);
});

test("practiceQuestionView disables the submit button while submitting, even with a selection", () => {
  const question = { question_id: "q1", stem: "2+2?", options: [{ key: "a", text: "4" }] };
  const html = practiceQuestionView(question, { selectedKey: "a", submitting: true });
  assert.equal(html.includes('id="submit-answer" disabled'), true);
});

test("practiceQuestionView escapes the stem", () => {
  const question = { question_id: "q1", stem: "<script>s</script>", options: [] };
  const html = practiceQuestionView(question, { selectedKey: null, submitting: false });
  assert.equal(html.includes("<script>s</script>"), false);
  assert.equal(html.includes("&lt;script&gt;s&lt;/script&gt;"), true);
});

test("practiceResultView marks a correct answer and escapes the explanation", () => {
  const html = practiceResultView({ correct: true, explanation: "<script>e</script>" });
  assert.equal(html.includes("Correcto"), true);
  assert.equal(html.includes('class="practice-verdict correct"'), true);
  assert.equal(html.includes("<script>e</script>"), false);
  assert.equal(html.includes("&lt;script&gt;e&lt;/script&gt;"), true);
});

test("practiceResultView marks an incorrect answer as an error, not correct", () => {
  const html = practiceResultView({ correct: false, explanation: "nope" });
  assert.equal(html.includes("Incorrecto"), true);
  assert.equal(html.includes('class="practice-verdict error"'), true);
  assert.equal(html.includes("Correcto<"), false);
});

test("practiceAlreadyRecordedView names no correctness, since the 409 response never carried one", () => {
  const html = practiceAlreadyRecordedView();
  assert.equal(html.includes("ya había quedado registrada"), true);
  assert.equal(html.includes("Correcto"), false);
  assert.equal(html.includes("Incorrecto"), false);
});

const AMBIGUOUS_404 = { status: 404, message: "nothing to study in topic t1: no objective is due or unstarted" };
const CONCLUSIVE_404 = { status: 404, message: "topic t1 has no question for any due or unstarted objective: o1" };

test("describePracticeUnavailable: an empty topic (objectiveCount 0) reads as no questions yet", () => {
  assert.equal(
    describePracticeUnavailable(AMBIGUOUS_404, { objectiveCount: 0 }),
    "Todavía no hay preguntas para este tema: subí material y generá preguntas.",
  );
});

// The conclusive 404 wins regardless of objectiveCount - checked first.
test("describePracticeUnavailable: conclusive 404 wins even with objectiveCount 0", () => {
  assert.equal(
    describePracticeUnavailable(CONCLUSIVE_404, { objectiveCount: 0 }),
    "Todavía no hay preguntas para los objetivos pendientes.",
  );
});

test("describePracticeUnavailable: objectives exist and have questions, but nothing is due", () => {
  assert.equal(describePracticeUnavailable(AMBIGUOUS_404, { objectiveCount: 3 }), "No hay nada vencido por ahora.");
});

// review round 1, B2: an unfetched objectiveCount must read as caught-up,
// never as "empty topic" - only a confirmed 0 may say that.
test("describePracticeUnavailable: an unknown objectiveCount reads as caught-up", () => {
  assert.equal(describePracticeUnavailable(AMBIGUOUS_404, {}), "No hay nada vencido por ahora.");
});

test("describePracticeUnavailable shows an unknown-topic 404 in Spanish, naming the topic", () => {
  const err = { status: 404, message: "unknown topic: t1" };
  assert.equal(describePracticeUnavailable(err, { topicId: "t1" }), 'No existe el tema "t1".');
});

test("describePracticeUnavailable shows a non-404 failure's message unchanged", () => {
  const err = { status: 0, message: "No se pudo conectar con el servidor." };
  assert.equal(describePracticeUnavailable(err, { objectiveCount: 3 }), "No se pudo conectar con el servidor.");
});
