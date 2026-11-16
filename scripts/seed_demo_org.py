"""Optional demo load for the teacher view (issue #75): one organization, one
teacher and four students, each with a backdated practice history.

Everything is synthetic. It writes straight to the Postgres stores for the same
reason ``scripts/seed_sample_data.py`` does: the HTTP API always uses the server
clock, and a believable history needs attempts from weeks ago.

Run it against a database the migrations have been applied to, then start the
app with authentication OFF (``LEARNING_TRACKER_CLERK_ISSUER`` unset) and pick
an identity in the header selector (open the page with ``?demo=1``), or send the
``X-Dev-*`` headers by hand - see README.md, "Teacher view"::

    python -m scripts.seed_demo_org

Safe to run twice: a student who already has the demo topic is skipped.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from content.models import Material
from content.postgres import PostgresMaterialStore, PostgresQuestionStore
from core.clock import FixedClock
from core.errors import UnknownProfileError
from core.models import Objective, Profile
from core.tracker import LearningTracker
from generate.stub import StubGenerator
from store.members import PostgresMemberStore
from store.postgres import PostgresAttemptStore, PostgresProfileStore
from web.config import DATABASE_URL_VAR, SCHEMA_VAR

ORG_ID = "org_demo"
TEACHER = ("demo_teacher", "Docente Demo")
TOPIC_ID = "redes-de-computadoras"
TOPIC_NAME = "Redes de computadoras"
MATERIAL_TITLE = "Modelo OSI y direccionamiento IP"
MATERIAL_BODY = (
    "El modelo OSI organiza la comunicacion de red en siete capas. La capa de "
    "red se encarga del enrutamiento entre redes distintas usando direcciones "
    "IP. Una direccion IPv4 tiene 32 bits y se escribe en cuatro octetos. El "
    "protocolo TCP garantiza entrega ordenada y confirmada; UDP no ofrece esas "
    "garantias pero tiene menor sobrecarga."
)

#: Objectives added on top of the one the stub generator proposes, so a topic
#: has enough rows for the students' histories to differ.
EXTRA_OBJECTIVES = (
    Objective(objective_id="osi-capas", title="Describir las capas del modelo OSI", domain="Fundamentos"),
    Objective(objective_id="ipv4-direccionamiento", title="Calcular direcciones y mascaras IPv4", domain="Direccionamiento"),
    Objective(objective_id="tcp-udp", title="Distinguir TCP de UDP", domain="Transporte"),
)

#: (user_id, display name, history) where history maps an objective id (or
#: ``"*generated*"`` for the generator's own) to (correct, days ago) attempts.
STUDENTS = (
    (
        "demo_ana",
        "Ana Rojas",
        {
            "osi-capas": [(True, 20), (True, 17), (True, 14), (True, 10), (True, 6), (True, 3)],
            "ipv4-direccionamiento": [(True, 18), (True, 12), (True, 7), (True, 4), (True, 2)],
            "tcp-udp": [(True, 9), (True, 5), (True, 2), (True, 1)],
            "*generated*": [(True, 8), (True, 4), (True, 1)],
        },
    ),
    (
        "demo_bruno",
        "Bruno Soto",
        {
            "osi-capas": [(True, 15), (False, 11), (True, 7), (True, 3)],
            "ipv4-direccionamiento": [(False, 13), (False, 9), (True, 5)],
            "*generated*": [(True, 8), (False, 2)],
        },
    ),
    (
        "demo_carla",
        "Carla Munoz",
        {"osi-capas": [(True, 2), (False, 1)]},
    ),
    (
        "demo_diego",
        "Diego Pino",
        {
            "osi-capas": [(True, 45), (True, 44), (True, 42)],
            "ipv4-direccionamiento": [(False, 40)],
            "*generated*": [(True, 38)],
        },
    ),
)


def main() -> int:
    dsn = os.environ.get(DATABASE_URL_VAR)
    if not dsn:
        print(f"error: set {DATABASE_URL_VAR} first (see .env.example)", file=sys.stderr)
        return 2
    schema = os.environ.get(SCHEMA_VAR) or "learning"
    now = datetime.now(timezone.utc)

    members = PostgresMemberStore.from_dsn(dsn, schema=schema)
    members.upsert(ORG_ID, TEACHER[0], "org:admin", now, display_name=TEACHER[1])

    seeded = 0
    for user_id, name, history in STUDENTS:
        members.upsert(ORG_ID, user_id, "org:member", now, display_name=name)
        profiles = PostgresProfileStore.from_dsn(dsn, schema=schema, user_id=user_id)
        try:
            profiles.get_profile(TOPIC_ID)
        except UnknownProfileError:
            pass
        else:
            continue
        attempts = PostgresAttemptStore.from_dsn(dsn, schema=schema, user_id=user_id)
        materials = PostgresMaterialStore.from_dsn(dsn, schema=schema, user_id=user_id)
        questions = PostgresQuestionStore.from_dsn(dsn, schema=schema, user_id=user_id)

        profiles.save_profile(Profile(profile_id=TOPIC_ID, name=TOPIC_NAME, objectives={}))
        material = materials.add(
            Material(
                material_id=f"{user_id}-material-1",
                topic_id=TOPIC_ID,
                title=MATERIAL_TITLE,
                source="apunte de ejemplo",
                body=MATERIAL_BODY,
                created_at=now - timedelta(days=50),
            )
        )
        generated = StubGenerator().generate(material, [], now=FixedClock(material.created_at))
        profiles.upsert_objectives(TOPIC_ID, [*generated.objectives, *EXTRA_OBJECTIVES])
        questions.replace_for_material(material.material_id, generated.questions)

        generated_id = generated.objectives[0].objective_id
        tracker = LearningTracker(TOPIC_ID, profiles, attempts, FixedClock(now))
        for objective_id, rows in history.items():
            objective_id = generated_id if objective_id == "*generated*" else objective_id
            for index, (correct, days_ago) in enumerate(rows):
                tracker.record_attempt(
                    objective_id=objective_id,
                    correct=correct,
                    at=now - timedelta(days=days_ago),
                    attempt_id=f"{user_id}-{objective_id}-{index}",
                )
        seeded += 1

    print(
        f"organization '{ORG_ID}': teacher '{TEACHER[0]}' and {len(STUDENTS)} students ready "
        f"({seeded} newly seeded)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
