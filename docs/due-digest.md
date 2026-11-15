# Daily due digest

Tells each learner what is due today without them opening the app (issue
#68). Once a day a cron runs:

```sh
python -m scripts.send_due_digest [--sender console|file|smtp] [--out PATH] [--as-of ISO]
```

For every configured recipient it computes, from the engine, the objectives
due for review in the topics they follow (`LearningTracker.get_due`, SPEC
section 5.2), names the most overdue ones, and adds a link that opens the
topic in the web app. **A recipient with nothing due gets nothing**: a
reminder that arrives every day regardless teaches people to ignore it.

Exit codes: `0` sent or silent, `1` a send or a database read failed, `2`
configuration error.

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `LEARNING_TRACKER_DATABASE_URL` | yes | Same DSN as the web app |
| `LEARNING_TRACKER_SCHEMA` | no | Same schema as the web app (default `learning`) |
| `LEARNING_TRACKER_DIGEST_RECIPIENTS` | yes | JSON: email -> list of topic ids, or `"*"` for all |
| `LEARNING_TRACKER_PUBLIC_URL` | no | Public URL of the web app, for the links (default `http://127.0.0.1:8000`) |
| `LEARNING_TRACKER_SMTP_HOST` | smtp only | SMTP server |
| `LEARNING_TRACKER_SMTP_FROM` | smtp only | Sender address |
| `LEARNING_TRACKER_SMTP_PORT` | no | Default 587 (`starttls`), 465 (`ssl`), 25 (`none`) |
| `LEARNING_TRACKER_SMTP_SECURITY` | no | `starttls` (default), `ssl` or `none` |
| `LEARNING_TRACKER_SMTP_USER` / `LEARNING_TRACKER_SMTP_PASSWORD` | no | Both or neither |

Example recipients mapping:

```json
{"ana@example.com": ["redes-de-computadoras"], "profe@example.com": "*"}
```

The mapping is a stop-gap: the engine has no per-user data yet. When topics
belong to users, it is replaced by a query; the digest and the senders do not
change. SMTP uses the standard library only, so any provider (Resend, SES,
Postmark, Gmail...) works through its SMTP endpoint.

## Whose clock

The digest is computed at the moment the job runs (`--as-of` overrides it).
"Due" is an instant, not a calendar day, so the only time decision is when
the cron fires. Railway cron schedules are in **UTC**: `0 11 * * *` is 08:00
in Chile during summer time (UTC-3) and 07:00 in winter (UTC-4). One schedule
for the whole deployment; per-learner hours come with per-user data.

## Railway cron setup

1. In the same Railway project, add a new service from the same repository
   (it shares the build with the web service).
2. Variables: reference the web service's `LEARNING_TRACKER_DATABASE_URL`
   (and `LEARNING_TRACKER_SCHEMA` if set), then add
   `LEARNING_TRACKER_DIGEST_RECIPIENTS`, `LEARNING_TRACKER_PUBLIC_URL` and the
   `LEARNING_TRACKER_SMTP_*` variables.
3. Settings -> Deploy -> Custom Start Command:
   `python -m scripts.send_due_digest --sender smtp`
4. Settings -> Cron Schedule: `0 11 * * *`.
5. The job must exit when done (it does); Railway skips a run if the
   previous one is still running. Its output (who got a digest, who was
   skipped) is in the service's deploy logs.

To try it before sending real email, start with `--sender console` and read
the deploy logs.

## Locally

```sh
scripts/dev-up.sh && python -m scripts.seed_sample_data
LEARNING_TRACKER_DIGEST_RECIPIENTS='{"me@example.com": "*"}' \
  python -m scripts.send_due_digest
```
