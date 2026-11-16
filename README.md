# learning-tracker

Learning tracking engine: it records attempts, computes a mastery level per
objective and schedules reviews. Independent of whatever subject is being
studied.

**Status:** under construction. The contract lives in `SPEC.md`.

## Principles

- **The history is the only source of truth.** Every aggregate (level, next
  review) is a recalculable projection. Nothing is stored that cannot be
  derived.
- **Time is injected, never read.** The engine does not call `now()`: it
  receives the date. That is what makes it possible to simulate months of study
  inside a test.
- **Modular.** `core/` knows nothing about storage, about the CLI or about the
  UI.

## Quickstart: run it locally

Requirements: Python 3.10+, Docker (for Postgres), and a shell (`scripts/dev-up.sh`
is bash).

```sh
git clone <this repo> learning-tracker && cd learning-tracker
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"          # pulls in fastapi, psycopg, the generator, ...

cp .env.example .env    # the defaults already match docker-compose.yml
scripts/dev-up.sh       # brings up Postgres, applies migrations, starts the API
```

If that last step dies on `port is already allocated`, something else on the
machine already owns 5432. Set `POSTGRES_PORT` in `.env` to a free port and
change the port in `LEARNING_TRACKER_DATABASE_URL` to match, then run it again.

Leave that running and open <http://127.0.0.1:8000> in a browser. That is the
whole application: a page with two tabs (Aprendiendo, Progreso; practising is a mode of the tree, and
Material opens from inside a goal) served by the same process that answers the API.

There is no sign-in step here: with no `LEARNING_TRACKER_CLERK_ISSUER`,
`scripts/dev-up.sh` sets `LEARNING_TRACKER_AUTH_DISABLED=true` and says so,
and every request is accepted. Authentication fails closed everywhere else:
starting the app (`python -m web.app`, the Docker image) with neither variable
set refuses to start, and setting both is a configuration error. Set the
issuer and `LEARNING_TRACKER_CLERK_PUBLISHABLE_KEY` to require a Clerk session
instead; nothing else in this quickstart changes.

To run the production image locally, or to deploy it on Railway, see
[`docs/deploy.md`](docs/deploy.md).

### Demo data

One command seeds a school-style demo, and the same data feeds the student's
Progreso tab and the teacher's organization table (issues #74, #75):

```sh
.venv/bin/python -m scripts.seed_demo   # after scripts/dev-up.sh; safe to run again
# then open http://127.0.0.1:8000/?demo=1
```

It creates the organization `org_demo`, a teacher (`demo_teacher`) and four
students, all synthetic, each with school subjects (units, objectives) and a
different backdated practice history: `demo_ana` strong and steady,
`demo_bruno` uneven, `demo_carla` just started, `demo_diego` stopped weeks ago
and has things due (only Historia). Re-running it neither duplicates nor fails.

Every learner's data is private to them (issue #58); an *organization admin* (a
teacher) additionally gets a read-only table of their organization's members:
per member and topic, the typical level, how many objectives are due and how
many were never practised (issue #75). Members never see each other's data.
With Clerk, the organization and role come from the verified session token
(`o.id` / `o.rol` in v2 tokens, `org_id` / `org_role` in v1) and the app records
each member it sees.

Without Clerk, you impersonate the seeded users. The impersonation exists
**only while authentication is explicitly off** (`LEARNING_TRACKER_AUTH_DISABLED=true`,
which `scripts/dev-up.sh` sets); with an issuer configured the headers are never
read, and a deploy with neither variable refuses to start. In the browser,
`?demo=1` adds a selector to the header: pick "Docente Demo (docente)" and a
"Vista docente" tab appears; pick a student and it disappears, and the student's
Progreso shows only their own topics. By hand, it is three headers:
`X-Dev-User`, `X-Dev-Org`, `X-Dev-Role`.

```sh
curl -H 'X-Dev-User: demo_teacher' -H 'X-Dev-Org: org_demo' -H 'X-Dev-Role: admin' \
  http://127.0.0.1:8000/org/progress
```

For a single topic with notes and generated questions instead, run
`.venv/bin/python -m scripts.seed_sample_data`.

### The path by hand, in the browser

1. **Tópicos** → create one, e.g. id `redes`, name `Redes`.
2. **Material** → pick that topic, upload a page of notes (title, source,
   the text itself), then click "Generar preguntas". Generation needs
   `OPENAI_API_KEY` in the process environment (`.env.example`); without it
   this one action fails with a clear error and everything else — creating
   topics, uploading, listing, practising, progress — keeps working.
3. **Practicar** → the topic serves its most urgent question (due first,
   then never-practised); answer a few, right and wrong.
4. **Progreso** → watch the level and score move as attempts land, and see
   the objective drop out of "due" right after you get it right.

### Stopping and cleaning up

`Ctrl-C` stops the API; `docker compose down` stops Postgres (add `-v` to
also delete its data volume, which is otherwise kept across restarts).

## Where the data lives

The web application above always talks to Postgres — `LEARNING_TRACKER_DATABASE_URL`
is required and there is no default that would silently point at somebody's
machine. `docker-compose.yml` runs that Postgres locally, on port 5432 by
default (override with `POSTGRES_PORT` if that port is taken, and update the
DSN in `.env` to match).

The CLI (`ui/`, see below) is a separate, older path that predates the web
application: it keeps its own store as JSON on disk, in the standard user
data directory of the operating system, controlled by `LEARNING_TRACKER_DATA`.
The two do not share data.

In the web application every row belongs to a user: the Clerk session's `sub`, or the
single implicit user `local` when authentication is off (migration `0004`).

## Layout

| Path | What it is |
| --- | --- |
| `SPEC.md` | The contract: levels, evolution, guarantees |
| `INTEGRATION.md` | How to connect the engine to a study source (notes, quiz, tutor agent) |
| `core/` | Pure engine, no I/O |
| `store/`, `content/` | Persistence: attempts/profiles and material/questions |
| `migrations/` | The SQL schema and the runner `scripts/dev-up.sh` calls |
| `generate/` | Turns a page of notes into objectives and questions (OpenAI, plus a deterministic stub used by the tests and by the sample load) |
| `web/` | The FastAPI backend: `web/config.py` is the full list of settings it reads |
| `webui/` | The front end it serves, static files, no build step |
| `scripts/` | `dev-up.sh`, `seed_demo.py` and `seed_sample_data.py`, described above |
| `ui/` | A standard-library CLI over the engine — see `ui/README.md` |
| `tests/` | Verification suite |

### The CLI

`ui/` is a separate command-line interface over the same engine, independent
of the web application above and predating it:

```sh
pip install .                       # puts the learning-tracker executable on the PATH
learning-tracker --help
```

Every subcommand, its data location and its backup story are in `ui/README.md`.
