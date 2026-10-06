# Progress dashboard

Issue: rodrvc/learning-tracker-engine#74. Branch: feat/74-progress-dashboard.
Route: direct inline, single writer (UI-only change plus one seed script).
TDD: not configured; ordinary functional checks (`pytest`, which also runs `node --test tests/webui`).

## Objective
A friendly "Progreso" tab showing knowledge bars per goal and per unit, with
objectives grouped in calm bands and the next scheduled reviews.

## Scope
- New tab `#/progress[/<topic_id>]`, Spanish copy, built from existing endpoints
  (`/topics`, `/topics/{id}`, `/objectives/states`, `/summary`). No backend change,
  no new scoring: bands are a grouping of the engine level, bars are engine scores.
- Friendlier wording: "Repaso pendiente" instead of "Vencido", "Por reforzar" instead of "Debil".
- School-style synthetic seed `scripts/seed_school_data.py`.

## Tasks
- [x] T1 Pure model + markup `webui/js/progress.js` with Node tests
- [x] T2 View, route, nav tab, styles (calm green / blue / amber)
- [x] T3 Soften labels in the Aprendiendo tree (+ tests)
- [x] T4 School seed + engine-backed spread test
- [x] T5 Run against a throwaway Postgres and capture screenshots

## Acceptance
- Progreso renders bars from engine states only; existing seed untouched; suite green.

## Checks / progress
- `.venv/bin/python -m pytest -q` and `node --test tests/webui` (see commit message / final report).
- Verified visually on a throwaway stack (Postgres :5544, API :8011), torn down afterwards.
