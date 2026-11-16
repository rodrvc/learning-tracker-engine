"""The one demo command: a school-style organization with a teacher and students.

``python -m scripts.seed_demo`` creates the organization ``org_demo``, a teacher
(``demo_teacher``, ``org:admin``) and four students. Each student has the same
two school subjects (units, objectives) but a different, backdated practice
history: one strong and steady, one uneven, one who just started, one who
stopped weeks ago and has everything due. So a student's Progreso dashboard
and the teacher's organization table tell the same story (issues #74, #75).

Everything is synthetic: made-up study subjects and people. It writes straight
to the Postgres stores so it can backdate attempts through
``LearningTracker.record_attempt``'s injected ``at`` (the HTTP API deliberately
cannot, SPEC I2). Units are carried in ``Objective.domain``.

Retry-safe: every write is keyed by a deterministic id, an existing profile or
attempt is left alone, so running it again (or after a crash half way) neither
duplicates nor fails.

Usage, from the repo root, after ``scripts/dev-up.sh`` has applied migrations
(the app then runs with authentication off; open the page with ``?demo=1`` to
switch between the teacher and a student, see README.md, "Demo data")::

    python -m scripts.seed_demo
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from core.clock import FixedClock
from core.errors import DuplicateAttemptError, UnknownProfileError
from core.models import Objective, Profile
from core.tracker import LearningTracker
from store.members import PostgresMemberStore
from store.postgres import PostgresAttemptStore, PostgresProfileStore
from web.config import DATABASE_URL_VAR, SCHEMA_VAR

ORG_ID = "org_demo"
TEACHER = ("demo_teacher", "Docente Demo")


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


def _lapsed(practice: Practice) -> Practice:
    """The same practice, but it all happened a month or more ago."""
    return replace(practice, last_days_ago=practice.last_days_ago + 38)


def _uneven(practice: Practice) -> Practice:
    """Every third hit becomes a miss: knows some of it, forgets the rest."""
    pattern = "".join("w" if i % 3 == 2 else r for i, r in enumerate(practice.pattern))
    return replace(practice, pattern=pattern)


def _beginner(practice: Practice) -> Practice:
    """Only the first two attempts, done recently."""
    return replace(practice, pattern=practice.pattern[:2], last_days_ago=min(practice.last_days_ago, 1))


@dataclass(frozen=True)
class Student:
    user_id: str
    name: str
    topics: tuple[SeedTopic, ...]
    #: Turns the catalogue's practice into this student's own.
    shape: Callable[[Practice], Practice]
    #: Objectives (by position within a topic) this student has not reached.
    skip_from: int | None = None


STUDENTS = (
    Student("demo_ana", "Ana Rojas", TOPICS, lambda p: p),
    Student("demo_bruno", "Bruno Soto", TOPICS, _uneven, skip_from=10),
    Student("demo_carla", "Carla Munoz", TOPICS, _beginner, skip_from=4),
    Student("demo_diego", "Diego Pino", (HISTORIA,), _lapsed),
)


def attempt_times(practice: Practice, now: datetime) -> list[tuple[bool, datetime]]:
    """Dates for each result of ``practice``, oldest first."""
    count = len(practice.pattern)
    last = now - timedelta(days=practice.last_days_ago)
    return [
        (result == "c", last - timedelta(days=(count - 1 - index) * practice.spacing_days))
        for index, result in enumerate(practice.pattern)
    ]


def personal_practice(student: Student, topic: SeedTopic) -> dict[str, Practice | None]:
    """Objective id -> this student's practice (``None``: never practised)."""
    out: dict[str, Practice | None] = {}
    for position, objective in enumerate(topic.objectives):
        reached = student.skip_from is None or position < student.skip_from
        out[objective.objective_id] = (
            student.shape(objective.practice) if objective.practice and reached else None
        )
    return out


def seed_student_topic(
    student: Student,
    topic: SeedTopic,
    profiles: PostgresProfileStore,
    attempts: PostgresAttemptStore,
    now: datetime,
) -> int:
    """Writes one student's topic; returns the number of new attempts."""
    try:
        profiles.get_profile(topic.topic_id)
    except UnknownProfileError:
        profiles.save_profile(Profile(profile_id=topic.topic_id, name=topic.name, objectives={}))
    profiles.upsert_objectives(
        topic.topic_id,
        [Objective(objective_id=o.objective_id, title=o.title, domain=o.unit) for o in topic.objectives],
    )
    tracker = LearningTracker(topic.topic_id, profiles, attempts, FixedClock(now))
    recorded = 0
    for objective_id, practice in personal_practice(student, topic).items():
        if practice is None:
            continue
        for index, (correct, at) in enumerate(attempt_times(practice, now)):
            try:
                tracker.record_attempt(
                    objective_id=objective_id,
                    correct=correct,
                    at=at,
                    attempt_id=f"demo-{student.user_id}-{objective_id}-{index + 1}",
                )
            except DuplicateAttemptError:
                continue
            recorded += 1
    return recorded


def main() -> int:
    dsn = os.environ.get(DATABASE_URL_VAR)
    if not dsn:
        print(f"error: set {DATABASE_URL_VAR} first (see .env.example)", file=sys.stderr)
        return 2
    schema = os.environ.get(SCHEMA_VAR) or "learning"
    now = datetime.now(timezone.utc)

    members = PostgresMemberStore.from_dsn(dsn, schema=schema)
    members.upsert(ORG_ID, TEACHER[0], "org:admin", now, display_name=TEACHER[1])
    new_attempts = 0
    for student in STUDENTS:
        members.upsert(ORG_ID, student.user_id, "org:member", now, display_name=student.name)
        profiles = PostgresProfileStore.from_dsn(dsn, schema=schema, user_id=student.user_id)
        attempts = PostgresAttemptStore.from_dsn(dsn, schema=schema, user_id=student.user_id)
        for topic in student.topics:
            new_attempts += seed_student_topic(student, topic, profiles, attempts, now)
    print(
        f"organization '{ORG_ID}': teacher '{TEACHER[0]}' and {len(STUDENTS)} students ready "
        f"({new_attempts} new attempt(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
