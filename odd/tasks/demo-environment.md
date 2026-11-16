# Demo environment (issue #81)

## Objective
A demo the owner shows to schools and Chilean public agencies: looks real, tells a story in 5 minutes.

## Scope (authorized)
- Extend the unified seed `scripts/seed_demo.py` (stays the only demo command) with an Azure track (AI-900 + AZ-900 public "skills measured" domains), Spanish synthetic notes per unit and hand-written Spanish multiple-choice questions. No OpenAI calls, no private material.
- Second organization "Servicio Público Demo": coordinator (org:admin) + 6-8 staff personas (strong, steady, struggling, stalled 2 weeks, never started), dates relative to today, due reviews today.
- `LEARNING_TRACKER_DEMO_MODE=true` (only with auth disabled; refuses to start with auth on): "Entorno de demostración" banner, persona switcher grouped by organization; one-command reset (`python -m scripts.seed_demo --reset`).
- `docs/demo.md` in Spanish: one-command start + 5-minute click-by-click script.
- Browser screenshots with agent-browser.

## Constraints
SPEC.md wins; code/docs English, UI copy Spanish; no section sign; branch on top of feat/68-due-reminders; PR base feat/68-due-reminders.

## TDD
Mode: off (no project/session TDD config). Runner: `.venv/bin/pytest`. Ordinary functional checks + new tests.

## Delivery
Strategy: ask-on-risk; forecast ~900 authored lines, mostly seed content data (questions/notes). Single PR on top of the stack.

## Tasks
- [x] T1 Azure content + public agency org + personas in seed, `--reset` (route: delegated writer, 2+ non-trivial files)
- [x] T2 Demo mode flag: config validation, banner, grouped persona switcher (route: delegated writer)
- [x] T3 docs/demo.md (route: delegated writer)
- [x] T4 Browser verification screenshots (route: inline)
- [ ] T5 Push, PR against feat/68-due-reminders, Orca worktree comment (route: inline)

## Progress / evidence
- T2 (demo mode): 8690ee1. T1 (seed, Azure content, agency org, --reset): 7d18ee4. T3 (docs/demo.md, dev-up demo seeding, demo-reset.sh, README): 8d47ebd.
- Tests: full pytest 828 passed (baseline 822), node tests 142 passed; Postgres on port 54381 via `docker compose -p lt81`.
- Route: single writer inline (delegation not available to the writer); seed with a pooled connection takes ~20 s.
- T4: agent-browser against demo mode (port 8781, fresh --reset seed): docs/demo-screenshots/{coordinator-org-view,student-progress,practice-question}.png; banner, grouped switcher and Vista docente verified.
- Pending: T5.
