"""Optional school-flavoured sample load, for demos and screenshots.

Sibling of ``scripts.seed_sample_data`` (which stays as it was): instead of
one topic it creates two school subjects, each with named units, objectives
and a practice history with a realistic spread - most objectives well
learned, some "on track", one or two that need reinforcement, one never
practised, and reviews coming up over the next days.

Everything is synthetic: made-up study subjects, no names of real people or
institutions. Like the other seed, it writes straight to the Postgres stores
so it can backdate attempts through ``LearningTracker.record_attempt``'s
injected ``at`` (the HTTP API deliberately cannot, SPEC I2).

Units are carried in ``Objective.domain``, which the interface shows as the
unit name, so the unit label is the domain string itself.

Usage, from the repo root, after ``scripts/dev-up.sh`` has applied migrations::

    python -m scripts.seed_school_data
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.clock import FixedClock
from core.errors import UnknownProfileError
from core.models import Objective, Profile
from core.tracker import LearningTracker
from store.postgres import PostgresAttemptStore, PostgresProfileStore
from web.config import DATABASE_URL_VAR, SCHEMA_VAR


@dataclass(frozen=True)
class Practice:
    """A made-up practice history for one objective.

    ``pattern`` lists the results from oldest to newest ("c" hit, "w" miss).
    The newest attempt happened ``last_days_ago`` days ago and the earlier
    ones are ``spacing_days`` apart going back.
    """

    pattern: str
    last_days_ago: float
    spacing_days: float = 2.0


@dataclass(frozen=True)
class SeedObjective:
    objective_id: str
    title: str
    unit: str
    practice: Practice | None = None


@dataclass(frozen=True)
class SeedTopic:
    topic_id: str
    name: str
    objectives: tuple[SeedObjective, ...]


U1 = "U1 · Independencia"
U2 = "U2 · Organización de la República"
U3 = "U3 · Guerra del Pacífico"
U4 = "U4 · Cambios del siglo XX"

HISTORIA = SeedTopic(
    topic_id="historia-de-chile-2-medio",
    name="Historia de Chile · 2° Medio",
    objectives=(
        SeedObjective("ind-crisis-monarquia", "Crisis de la monarquía española y primeras juntas", U1, Practice("cccccccc", 3)),
        SeedObjective("ind-patrias", "Patria Vieja, Reconquista y Patria Nueva", U1, Practice("wccccccc", 6)),
        SeedObjective("ind-figuras", "Figuras de la Independencia: O'Higgins, Carrera y San Martín", U1, Practice("cwcccccc", 4)),
        SeedObjective("org-ensayos", "Ensayos constitucionales de 1823 a 1830", U2, Practice("wcccwcc", 2)),
        SeedObjective("org-conservadora", "La república conservadora y la Constitución de 1833", U2, Practice("ccccccc", 1)),
        SeedObjective("org-territorio", "Expansión territorial y el Estrecho de Magallanes", U2, Practice("cwwcwc", 2)),
        SeedObjective("pac-causas", "Causas y antecedentes del conflicto", U3, Practice("ccwcccc", 5)),
        SeedObjective("pac-campanas", "Campañas marítima y terrestre", U3, Practice("wcwccwc", 0.5, 1)),
        SeedObjective("pac-ancon", "Tratado de Ancón y sus consecuencias", U3, Practice("cccccc", 8, 3)),
        SeedObjective("xx-social", "Cuestión social y movimiento obrero", U4, Practice("ccccwcc", 1)),
        SeedObjective("xx-industria", "Crisis de 1929 e industrialización por sustitución de importaciones", U4, Practice("cccccc", 10, 3)),
        SeedObjective("xx-reformas", "Reformas de mediados del siglo XX y Reforma Agraria", U4, Practice("cwcwcw", 4)),
        SeedObjective("xx-democracia", "Quiebre democrático y retorno a la democracia", U4),
    ),
)

B1 = "U1 · La célula y sus partes"
B2 = "U2 · Energía en la célula"

BIOLOGIA = SeedTopic(
    topic_id="biologia-la-celula",
    name="Biología · La célula",
    objectives=(
        SeedObjective("cel-teoria", "Teoría celular y tipos de célula", B1, Practice("ccccccc", 2)),
        SeedObjective("cel-organelos", "Organelos y sus funciones", B1, Practice("cccwccc", 1)),
        SeedObjective("cel-membrana", "Membrana plasmática y transporte", B1, Practice("wcwccc", 3)),
        SeedObjective("ene-fotosintesis", "Fotosíntesis", B2, Practice("cccccc", 9, 3)),
        SeedObjective("ene-respiracion", "Respiración celular", B2, Practice("cwcwwc", 3)),
        SeedObjective("ene-fermentacion", "Fermentación", B2),
    ),
)

TOPICS = (HISTORIA, BIOLOGIA)


def attempt_times(practice: Practice, now: datetime) -> list[tuple[bool, datetime]]:
    """Dates for each result of ``practice``, oldest first."""
    count = len(practice.pattern)
    last = now - timedelta(days=practice.last_days_ago)
    return [
        (result == "c", last - timedelta(days=(count - 1 - index) * practice.spacing_days))
        for index, result in enumerate(practice.pattern)
    ]


def seed_topic(
    topic: SeedTopic,
    profiles: PostgresProfileStore,
    attempts: PostgresAttemptStore,
    now: datetime,
) -> str:
    try:
        profiles.get_profile(topic.topic_id)
    except UnknownProfileError:
        pass
    else:
        return f"topic '{topic.topic_id}' already exists - skipped."

    profiles.save_profile(Profile(profile_id=topic.topic_id, name=topic.name, objectives={}))
    profiles.upsert_objectives(
        topic.topic_id,
        [
            Objective(objective_id=o.objective_id, title=o.title, domain=o.unit)
            for o in topic.objectives
        ],
    )
    tracker = LearningTracker(topic.topic_id, profiles, attempts, FixedClock(now))
    recorded = 0
    for objective in topic.objectives:
        if objective.practice is None:
            continue
        for index, (correct, at) in enumerate(attempt_times(objective.practice, now)):
            tracker.record_attempt(
                objective_id=objective.objective_id,
                correct=correct,
                at=at,
                attempt_id=f"school-{objective.objective_id}-{index + 1}",
            )
            recorded += 1
    return (
        f"topic '{topic.topic_id}' ready: {len(topic.objectives)} objective(s), "
        f"{recorded} attempt(s)."
    )


def main() -> int:
    dsn = os.environ.get(DATABASE_URL_VAR)
    if not dsn:
        print(f"error: set {DATABASE_URL_VAR} first (see .env.example)", file=sys.stderr)
        return 2
    schema = os.environ.get(SCHEMA_VAR) or "learning"

    profiles = PostgresProfileStore.from_dsn(dsn, schema=schema)
    attempts = PostgresAttemptStore.from_dsn(dsn, schema=schema)
    now = datetime.now(timezone.utc)
    for topic in TOPICS:
        print(seed_topic(topic, profiles, attempts, now))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
