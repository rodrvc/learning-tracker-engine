# Per-user data (#58) and teacher view (#75)

Objective: a showable MVP where every learner sees only their own data, and an
org admin (teacher) sees a read-only view of their group's progress.

Problem: `profile_id` carries two axes (what is studied, who studies it); a valid
Clerk session today still reads one shared dataset.

Constraints: SPEC.md wins; auth disabled = one implicit local user with existing
behaviour and tests unchanged; user id only from the verified token `sub`; English
for code/docs, Spanish (Chile, neutral) for UI copy; no section-sign character;
no remote services touched besides `git push` + `gh pr create`.

TDD: off (no project/session TDD configuration found). Ordinary checks: full
pytest suite against Postgres from docker compose.

Delivery strategy: single-pr (two work-unit commits, one per issue).

## Tasks

- [x] T1 (#58, delegated: 4+ files) Scope data by (user_id, profile_id): migration
  0004, stores, tracker wiring, web deps from verified `sub`, implicit local user
  when auth off, tests. Commit `feat: ...` with `Closes #58` in PR.
- [ ] T2 (#75, delegated: 4+ files) Org/role from token (`o.id`/`o.rol`,
  `org_id`/`org_role`), membership record, read-only teacher endpoint + web UI
  view for `org:admin`, members see only own data, seed demo org (teacher + 3-4
  students with history), dev-only impersonation when auth is off, tests.
- [ ] T3 Push branch, open PR against main (Closes #58, Closes #75), update Orca
  worktree comment.

## Acceptance

- Auth off: full existing suite green, behaviour unchanged.
- Auth on: two users with the same topic id never see each other's attempts.
- Teacher view lists each member's level per topic, due count, never-practised.
- Seed + impersonation lets the teacher view be demoed with auth disabled.

## Progress / evidence

- T1 done: migration 0004_user_scope.sql; Postgres stores bound per user via
  `for_user()` (default `local`); `require_session` returns `Identity(sub)`;
  `get_resources` hands each request user-scoped stores. Route: delegated direct
  (single writer). Full suite vs Postgres (port 5460): 756 passed, 0 skipped
  (750 pre-existing + 6 new in tests/test_user_scope.py). Commit: see git log
  (`feat: scope topics and history by the signed-in user`).

