# How to connect the engine to a study source

This engine does not know what you study. It has no questions, it does not grade, it knows
no syllabus. It keeps the books: what you practised, when you got it right and what is due
for review.

To be useful it needs a **source** that asks the questions — a notes repository, a question
bank, a tutor agent, an app — and that reports the results back to it. This document
explains that coupling, without tying itself to any subject.

---

## The division of labour

| What the engine provides | What the source provides |
| --- | --- |
| What is due for review today | The questions |
| The level per topic | Whoever grades |
| When something is being forgotten | The study material |
| The full history | The conversation with whoever studies |

The engine never decides whether an answer was correct. **The source decides that** and
tells the engine. A `--correct` may come from an automatic quiz, from a simulated exam or
from the person saying "I had this one down": the engine does not care, it only counts.

---

## The cycle

```
1. The source asks the engine what is due       ->  due
2. The source picks material from those topics
3. The source asks the person
4. The person answers
5. The source tells the engine how it went      ->  record --correct | --wrong
```

Without step 1, the source asks whatever comes to mind. With it, it asks **what is being
forgotten**. That is the whole value of the coupling.

Step 5 is mandatory: an attempt that is not recorded does not exist, and the engine cannot
infer it. If the session ends without recording anything, the level does not move — and
that is correct, because there is no evidence that any practice happened.

---

## Step 1 — Define the objectives

An **objective** is the smallest unit that makes sense to review on its own. The choice
determines the grain of everything else, so it is worth thinking through once:

| Source | Reasonable objective |
| --- | --- |
| Notes repository | One note |
| Course with modules | One module |
| Language | One grammar point or one vocabulary block |
| Certification syllabus | One domain, or one syllabus objective |

Two practical criteria:

- **Not so fine-grained that you never accumulate enough attempts** (with fewer than 2 the
  engine returns `UNASSESSED` on purpose), **nor so coarse that "I'm shaky on this" does not
  say where**.
- **Stable over time.** The `objective_id` is the key of the history: if it is renamed, the
  thread of what was practised is lost. Prefer a short identifier without accents
  (`rag-grounding`), not the full title of the material.

```bash
learning-tracker --data <RUTA> profile create <perfil> --name "<Nombre>"
learning-tracker --data <RUTA> --profile <perfil> objective add rag-grounding \
    --title "RAG y grounding"
```

Registering objectives is idempotent in practice: doing it twice does not duplicate
history, because the history lives in the attempts, not in the objective.

---

## Step 2 — Query before asking

```bash
learning-tracker --data <RUTA> --profile <perfil> due
```

Returns what is overdue, **most urgent first**. If it is empty, nothing is pending and it
is worth looking at what has not been touched yet:

```bash
learning-tracker --data <RUTA> --profile <perfil> unstarted   # nunca practicado
learning-tracker --data <RUTA> --profile <perfil> stale       # sin actividad reciente
learning-tracker --data <RUTA> --profile <perfil> summary     # cómo va el conjunto
```

`unstarted` and `due` are deliberately distinct: *"I have never seen this"* and *"it is due
for review"* are different things, and mixing them hides the material that is not covered.

---

## Step 3 — Record the result

```bash
learning-tracker --data <RUTA> --profile <perfil> record rag-grounding --correct
learning-tracker --data <RUTA> --profile <perfil> record rag-grounding --wrong
```

Useful options:

| Option | What for |
| --- | --- |
| `--kind quiz\|exercise\|lab\|exam_sim\|self_report` | Where the attempt came from |
| `--note "..."` | What exactly was missed |
| `--at ISO8601` | Record with a past date (a session not noted down at the time) |
| `--confidence N` | Stored, but **does not affect the computation** |
| `--id <attempt_id>` | Idempotency: repeating the same id raises `DuplicateAttemptError` |

One question, one `record`. Do not group five questions of a topic into a single attempt:
the engine weights by recency and needs the attempts separated to see the trend.

---

## Where the data lives

The engine does not choose the location: whoever invokes it passes it in, with `--data`.

**The recommendation is to keep it next to the study material**, not in a system folder.
The data belongs to that study, not to that machine:

```
tu-repo-de-estudio/
├── material/          <- los apuntes, preguntas, lo que sea
└── .learning/         <- attempts.json + profiles.json
```

Decide deliberately whether that directory goes into git:

- **Yes:** you gain history and synchronisation across machines. Since the history is
  append-only and every `attempt_id` is unique, a merge conflict is resolved by
  **joining the two lists** — there is no mutable state to reconcile.
- **No** (add it to `.gitignore`): if the repository is shared or made public, personal
  progress is not on display. In that case a periodic copy is advisable:
  `cp -R .learning ~/backups/<proyecto>-$(date +%Y%m%d)`.

---

## Integrating a tutor agent

If the source is an agent (Claude Code or another), the coupling is **instructions in its
`CLAUDE.md`**, not code. The minimal pattern:

```markdown
## Seguimiento del progreso

Los datos viven en `.learning/`. Usa siempre `--data .learning/` y el perfil `<perfil>`.

**Al empezar una sesión de estudio**, consulta qué toca:

    learning-tracker --data .learning/ --profile <perfil> due

Si `due` está vacío, mira `unstarted` para material sin cubrir.
Elige el material de esos temas, no otros.

**Tras cada pregunta que le hagas a la persona**, registra el resultado:

    learning-tracker --data .learning/ --profile <perfil> record <objetivo> --correct
    learning-tracker --data .learning/ --profile <perfil> record <objetivo> --wrong

Una pregunta, un registro. Usa `--note` para anotar qué se falló.
No cierres la sesión sin registrar: un intento no registrado no existe.
```

None of this is specific to a subject. Change the `<perfil>` and the objectives, and the
same block works for any syllabus.

---

## Integrating code

If the source is a program, skip the CLI and use the engine as a library. `core/` only
knows two Protocols (`AttemptStore`, `ProfileStore`), so you choose the storage:

```python
from core import LearningTracker
from store import JsonAttemptStore, JsonProfileStore, SystemClock

clock = SystemClock()
tracker = LearningTracker(
    profile_id="mi-perfil",
    attempts=JsonAttemptStore(".learning/attempts.json"),   # ruta de archivo,
    profiles=JsonProfileStore(".learning/profiles.json"),   # no de directorio
    clock=clock,
)

for objetivo in tracker.get_due():
    ...                                                      # preguntar
    tracker.record_attempt(
        objetivo.objective_id,
        correct=True,
        at=clock.now(),                                      # `at` es obligatorio
    )
```

Two details the signature imposes on purpose:

- The JSON stores take the **path of each file**, not that of the directory.
- `record_attempt` requires `at`. The engine never calls the clock on its own —
  whoever integrates decides which instant is recorded, and that is why months of study
  can be simulated in a test. The CLI fills it in with its clock when you do not pass `--at`.

To use different storage (a database, an API), implement the Protocols of
`core/storage.py`. The engine does not change: it does not know what is behind them.

The guarantees any implementation must meet are in the docstrings of
`core/storage.py`, and they are the ones that hold up the engine's invariants: atomic
`append` or exception (never a silent half-success), rejection of duplicate `attempt_id`,
and reads ordered by date.

---

## Integrating over HTTP

The engine also ships a small HTTP API (`web/`, mounted alongside the front end) with the
same topics/material/practice/progress surface the endpoints in `web/routers/` expose —
useful for a source that is itself a web app rather than a CLI or a Python process.

**ACU-278, breaking change for any caller of this API:** when the deployment sets
`LEARNING_TRACKER_CLERK_ISSUER`, every route under that API except `GET /health` and
`GET /auth/config` requires an `Authorization: Bearer <token>` header carrying a session
Clerk issued, and answers `401` without one, with an expired one or with one for a
different issuer. `GET /auth/config` reports whether this is switched on
(`{"enabled": ...}`, plus the public `publishableKey`/`issuer` a browser needs to start a
session) so a caller can tell which mode it is talking to instead of guessing from a 401.

When `LEARNING_TRACKER_CLERK_ISSUER` is unset — the default everywhere the test suite
runs — the API takes every request exactly as before this existed: no header, no session,
nothing to change in an existing integration. This does not partition data by caller: a
valid session is only proof that *someone* signed in, still against the one shared set of
topics (see `SPEC.md`, and the note on `profile_id` in the ACU-278 ticket).

**A source that grades something other than this engine's own quiz bank** — free text, a
written exercise, a spoken answer, a simulated exam — uses two routes in
`web/routers/ingest.py` instead of `POST .../practice/answer`:

```
POST /topics/{topic_id}/objectives
{"objectives": [{"objective_id": "...", "title": "...", "domain": "...", "weight": 1.0, "tags": [...]}]}

POST /topics/{topic_id}/objectives/{objective_id}/attempts
{"correct": true, "at": "2024-01-01T12:00:00Z", "kind": "exercise", "confidence": 0.8, "note": "...", "attempt_id": "..."}
```

Registering objectives is safe to repeat: a later call may send only `objective_id` and
`title`, and whatever it omits (`domain`, `weight`, `tags`) is merged onto what is already
stored rather than erased. To actually clear one of those fields, send it explicitly as
`null` (or `[]` for `tags`) rather than omitting it.

**`attempt_id` uniqueness is global**, one primary key shared by the whole engine, not
scoped to the topic in the URL — so **generate it as a UUID**, never as a per-topic or
per-session counter. A `409` here means that id was already used *somewhere* in the
engine: safe to treat as "my retry landed" only for a genuine retry of the same request.
A fresh id that happened to collide with an unrelated topic or objective was **discarded,
not saved** — the response names the collision as global for exactly this reason.

`at` must carry a timezone; a naive value is rejected with `422`, the same rule `?as_of=`
query parameters already follow on the progress routes.

---

## What to expect the first few days

The engine starts with no evidence, and it shows:

| Moment | What you will see |
| --- | --- |
| Attempt 1 on a topic | `UNASSESSED`. With fewer than 2 attempts it assigns no level |
| Attempts 2-3 | A level appears, still volatile |
| First week | `due` starts to make sense |
| After a month without touching a topic | It drops on its own, and shows up in `due` again |

It is not a bug that almost everything is in `UNASSESSED` or in `unstarted` at the start:
that is the difference between *"I don't know it"* and *"there is no evidence yet"*, and the
engine keeps it on purpose.

---

## Checking that everything is healthy

```bash
learning-tracker --data <RUTA> --profile <perfil> check
```

Compares counts and sums against what is on disk. Exits with code 1 if something does not
add up. Useful after editing the JSON by hand or synchronising across machines.

Since the history is the only source of truth and everything else is recomputed, almost
any mismatch fixes itself: there are no persisted aggregates that could end up corrupted.
