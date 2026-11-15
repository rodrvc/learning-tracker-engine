# Deploying learning-tracker

The repository builds one container image (`Dockerfile`) that serves the API
and the web UI from the same process. It follows the Acuaria product contract
(`acuaria-workspace/docs/product-contract.md`, sections 1, 2 and 5).

## What the container does on start

`python -m web.app --migrate`, in this order:

1. Reads and validates every setting below. A missing or contradictory
   setting prints one `error: ...` line and exits with code 2, before the
   database is touched.
2. Applies pending migrations to `LEARNING_TRACKER_SCHEMA`. Re-running is a
   no-op, so this is safe on every deploy and every restart.
3. Serves on `0.0.0.0:$PORT`.

Any failure exits non-zero, so the platform keeps the previous deploy running.

## Health check

`GET /health`, public (no session):

- `200 {"status": "ok"}` when the database answers **and** the schema is
  migrated (it reads `<schema>.schema_migrations`).
- `503 {"status": "unhealthy"}` otherwise. The body never names the host,
  user or database; the cause goes to the log.

On Railway: Settings, Deploy, *Healthcheck Path* = `/health`.

## Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `LEARNING_TRACKER_DATABASE_URL` | yes | Postgres DSN. On Railway: `${{Postgres.DATABASE_URL}}` (or the product's own database and role, contract section 4). |
| `LEARNING_TRACKER_SCHEMA` | no | Schema for the tables. Default `learning`. |
| `PORT` | injected | Port to listen on. Railway sets it; default `8000`. |
| `LEARNING_TRACKER_WEB_PORT` | no | Overrides `PORT` when set. |
| `LEARNING_TRACKER_WEB_HOST` | no | Bind address. The image sets `0.0.0.0`; outside the image the default is `127.0.0.1`. |
| `LEARNING_TRACKER_CLERK_ISSUER` | yes, unless auth is disabled | Clerk Frontend API URL, e.g. `https://clerk.acuarialabs.cl`. Sessions are verified against `<issuer>/.well-known/jwks.json`, RS256 only. |
| `LEARNING_TRACKER_CLERK_PUBLISHABLE_KEY` | with the issuer | Served to the browser by `GET /auth/config`. Public. |
| `LEARNING_TRACKER_CLERK_AUTHORIZED_PARTIES` | recommended | Comma-separated origins accepted in the token's `azp` claim, e.g. `https://learning.acuarialabs.cl`. All products share one Clerk instance; without this a token minted for another product's origin is accepted. |
| `LEARNING_TRACKER_AUTH_DISABLED` | no | `true`/`1`/`yes` turns authentication off. Local or single-user installs only. |
| `OPENAI_API_KEY` | for question generation | Without it only "Generar preguntas" fails; everything else works. |

### Authentication fails closed

| Issuer | `AUTH_DISABLED` | Result |
|---|---|---|
| set | unset / false | Every data route requires a valid Clerk session. |
| unset | true | No session checks. |
| unset | unset / false | **Refuses to start.** |
| set | true | **Refuses to start** (contradictory). |

A token is accepted only if its signature verifies, it carries `exp` and
`sub`, `iss` equals the issuer, and (when authorized parties are set) `azp` is
one of them. Anything else is `401`.

## Run the image locally

```sh
docker compose up -d --wait postgres
docker build -t learning-tracker .
docker run --rm -p 8000:8000 \
  -e LEARNING_TRACKER_DATABASE_URL=postgresql://learning_tracker:learning_tracker@host.docker.internal:5432/learning_tracker \
  -e LEARNING_TRACKER_AUTH_DISABLED=true \
  learning-tracker
curl -i http://127.0.0.1:8000/health
```

(Match the port to `POSTGRES_PORT` if you changed it.)

## Railway

1. New service from this repository; Railway detects the `Dockerfile`.
2. Add a Postgres database and set the variables above on the service.
3. Healthcheck path `/health`.
4. Custom domain under `acuarialabs.cl` (e.g. `learning.acuarialabs.cl`) so the
   Clerk session is shared across products, and put that origin in
   `LEARNING_TRACKER_CLERK_AUTHORIZED_PARTIES`.
