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
whole application: a page with four views (Tópicos, Material, Practicar,
Progreso) served by the same process that answers the API.

There is no sign-in step here: `LEARNING_TRACKER_CLERK_ISSUER` is unset by
default, which switches authentication off entirely (see `.env.example` and
`web/config.py`) — every request is accepted, exactly as the test suite
expects. Set that variable and `LEARNING_TRACKER_CLERK_PUBLISHABLE_KEY` to
require a Clerk session instead; nothing else in this quickstart changes.

### See it with data in it

Optional, and independent of the steps above:

```sh
.venv/bin/python -m scripts.seed_sample_data   # or just `python` with the venv activated
```

Creates one topic ("Redes de computadoras") with a page of synthetic notes,
a few generated questions and a short practice history old enough that one
objective already shows up as due for review. Nobody's real study material,
generated on the spot; safe to skip and start from an empty topic list
instead.

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
| `scripts/` | `dev-up.sh` and `seed_sample_data.py`, described above |
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
