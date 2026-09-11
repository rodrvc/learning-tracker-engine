"""Optional sample load: one topic, a page of notes, generated questions and
a short practice history - so the application can be *seen* with data in it
right after `scripts/dev-up.sh`, with no clicking required first.

Everything here is synthetic, generated on the spot from a made-up paragraph
by `generate.stub.StubGenerator` - the deterministic generator the test suite
runs against. It needs no `OPENAI_API_KEY` and it is nobody's real study
material.

It writes straight to the Postgres stores rather than calling the HTTP API,
for one reason: the API's `POST /topics/{id}/practice/answer` deliberately
takes no date and always uses the server clock (SPEC I2), so it cannot
produce an attempt from ten days ago. Backdating history is exactly what
`LearningTracker.record_attempt`'s injected `at` is for, and this script is
the one place outside the test suite that is allowed to use it that way.

Usage, from the repo root, after `scripts/dev-up.sh` has applied migrations::

    python -m scripts.seed_sample_data
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from content.models import Material
from content.postgres import PostgresMaterialStore, PostgresQuestionStore
from core.clock import FixedClock
from core.errors import UnknownProfileError
from core.models import Profile
from core.tracker import LearningTracker
from generate.stub import StubGenerator
from store.postgres import PostgresAttemptStore, PostgresProfileStore
from web.config import DATABASE_URL_VAR, SCHEMA_VAR

TOPIC_ID = "redes-de-computadoras"
TOPIC_NAME = "Redes de computadoras"
MATERIAL_ID = "sample-material-1"
MATERIAL_TITLE = "Modelo OSI y direccionamiento IP"
MATERIAL_SOURCE = "apunte de ejemplo"
MATERIAL_BODY = """
El modelo OSI organiza la comunicacion de red en siete capas. La capa de
enlace de datos entrega tramas dentro de una misma red local. La capa de red
se encarga del enrutamiento entre redes distintas usando direcciones IP. Una
direccion IPv4 tiene 32 bits y se escribe en cuatro octetos separados por
puntos. La mascara de subred determina que parte de la direccion identifica
la red y cual identifica el host. El protocolo TCP garantiza entrega
ordenada y confirmada; UDP no ofrece esas garantias pero tiene menor
sobrecarga.
""".strip()


def main() -> int:
    dsn = os.environ.get(DATABASE_URL_VAR)
    if not dsn:
        print(f"error: set {DATABASE_URL_VAR} first (see .env.example)", file=sys.stderr)
        return 2
    schema = os.environ.get(SCHEMA_VAR) or "learning"

    profiles = PostgresProfileStore.from_dsn(dsn, schema=schema)
    attempts = PostgresAttemptStore.from_dsn(dsn, schema=schema)
    materials = PostgresMaterialStore.from_dsn(dsn, schema=schema)
    questions = PostgresQuestionStore.from_dsn(dsn, schema=schema)

    try:
        profiles.get_profile(TOPIC_ID)
    except UnknownProfileError:
        pass
    else:
        print(f"topic '{TOPIC_ID}' already exists - nothing to do, open the app.")
        return 0

    now = datetime.now(timezone.utc)
    profiles.save_profile(Profile(profile_id=TOPIC_ID, name=TOPIC_NAME, objectives={}))

    material = materials.add(
        Material(
            material_id=MATERIAL_ID,
            topic_id=TOPIC_ID,
            title=MATERIAL_TITLE,
            source=MATERIAL_SOURCE,
            body=MATERIAL_BODY,
            created_at=now - timedelta(days=12),
        )
    )

    result = StubGenerator().generate(material, [], now=FixedClock(material.created_at))
    if not result.objectives:
        raise AssertionError("StubGenerator did not propose an objective for an empty topic")
    objective_id = result.objectives[0].objective_id
    profiles.upsert_objectives(TOPIC_ID, result.objectives)
    questions.replace_for_material(material.material_id, result.questions)

    # A history that lands the objective at a visible, non-zero level and,
    # crucially, overdue: the last attempt is a miss ~10 days ago, which
    # schedules the next review a single day later (SPEC section 4.2) - long
    # past due by the time anyone opens the app.
    history = [
        (True, now - timedelta(days=12, hours=1)),
        (True, now - timedelta(days=11)),
        (True, now - timedelta(days=10, hours=12)),
        (False, now - timedelta(days=10)),
    ]
    tracker = LearningTracker(TOPIC_ID, profiles, attempts, FixedClock(now))
    for index, (correct, at) in enumerate(history):
        tracker.record_attempt(
            objective_id=objective_id,
            correct=correct,
            at=at,
            attempt_id=f"sample-attempt-{index + 1}",
        )

    print(
        f"topic '{TOPIC_ID}' ready: 1 material, {len(result.questions)} question(s), "
        f"{len(history)} attempt(s) recorded on '{objective_id}' (now overdue for review)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
