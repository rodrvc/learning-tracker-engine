"""The one demo command: two synthetic organizations a client can be shown.

``python -m scripts.seed_demo`` creates

* ``org_demo``, a school: a teacher (``demo_teacher``, ``org:admin``) and four
  students over two school subjects, each with a different backdated practice
  history (issues #74, #75), and
* ``org_servicio_publico``, a public agency: a coordinator
  (``demo_sp_coordinacion``, ``org:admin``) and seven staff members training on
  Azure (AI-900 and AZ-900, content in ``scripts/demo_content_azure.py``): one
  strong, two steady, two struggling, one who stopped two weeks ago and one who
  never started. Each has notes and multiple-choice questions to practise, and
  several have reviews due today.

So a student's Progreso, the coordinator's organization table and the daily
digest (``docs/due-digest.md``) tell one story (issue #81, ``docs/demo.md``).

Everything is synthetic: made-up study subjects and people, no private
material and no model call (it needs no API key). It writes straight to the
Postgres stores so it can backdate attempts through
``LearningTracker.record_attempt``'s injected ``at`` (the HTTP API deliberately
cannot, SPEC I2). Every date is relative to the moment it runs, so the demo
never goes stale. Units are carried in ``Objective.domain``.

Retry-safe: every write is keyed by a deterministic id, an existing profile or
attempt is left alone, so running it again (or after a crash half way) neither
duplicates nor fails. Dates are the exception to "again changes nothing": a
second run does not move the first run's attempts, so a demo seeded last week
looks a week older. ``--reset`` deletes the demo organizations' data (the fixed
demo user ids and the two demo organizations, nothing else) and seeds it back
to the known state relative to now.

Usage, from the repo root, after ``scripts/dev-up.sh`` has applied migrations::

    python -m scripts.seed_demo            # seed (or top up)
    python -m scripts.seed_demo --reset    # wipe the demo data and reseed it
"""


from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg_pool import ConnectionPool

from content.models import Material, Question
from content.postgres import PostgresMaterialStore, PostgresQuestionStore
from core.clock import FixedClock
from core.errors import DuplicateAttemptError, UnknownProfileError
from core.models import Objective, Profile
from core.tracker import LearningTracker
from store.members import PostgresMemberStore
from store.postgres import ConnectionProvider, PostgresAttemptStore, PostgresProfileStore
from web.config import DATABASE_URL_VAR, SCHEMA_VAR
from web.demo import PUBLIC_SERVICE_ORG_ID, SCHOOL_ORG_ID

from .demo_content_azure import COURSES, NOTES_SOURCE, Course

ORG_ID = SCHOOL_ORG_ID
TEACHER = ("demo_teacher", "Docente Demo")
COORDINATOR = ("demo_sp_coordinacion", "Marcela Fuentes")


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


def seed_topic(
    user_id: str,
    topic: SeedTopic,
    practice: dict[str, Practice | None],
    profiles: PostgresProfileStore,
    attempts: PostgresAttemptStore,
    now: datetime,
) -> int:
    """Writes one learner's topic; returns the number of new attempts."""
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
    for objective_id, history in practice.items():
        if history is None:
            continue
        for index, (correct, at) in enumerate(attempt_times(history, now)):
            try:
                tracker.record_attempt(
                    objective_id=objective_id,
                    correct=correct,
                    at=at,
                    attempt_id=f"demo-{user_id}-{objective_id}-{index + 1}",
                )
            except DuplicateAttemptError:
                continue
            recorded += 1
    return recorded


def seed_student_topic(
    student: Student,
    topic: SeedTopic,
    profiles: PostgresProfileStore,
    attempts: PostgresAttemptStore,
    now: datetime,
) -> int:
    """Writes one student's topic; returns the number of new attempts."""
    return seed_topic(student.user_id, topic, personal_practice(student, topic), profiles, attempts, now)


# --- The public agency: Azure training ---------------------------------------


def _azure_topic(course: Course) -> SeedTopic:
    return SeedTopic(
        topic_id=course.topic_id,
        name=course.name,
        objectives=tuple(
            SeedObjective(objective.objective_id, objective.title, unit.name)
            for unit in course.units
            for objective in unit.objectives
        ),
    )


AI_900_TOPIC, AZ_900_TOPIC = (_azure_topic(course) for course in COURSES)
AZURE_TOPICS = (AI_900_TOPIC, AZ_900_TOPIC)
_COURSE_BY_TOPIC = {course.topic_id: course for course in COURSES}


@dataclass(frozen=True)
class Staff:
    """A member of the public agency. ``cycle`` is dealt out over the
    objectives in order, so one persona gets a believable mix, not a flat line."""

    user_id: str
    name: str
    topics: tuple[SeedTopic, ...]
    cycle: tuple[Practice, ...]
    #: How many objectives of each topic they reached; ``None`` is all of them.
    reach: int | None = None


STAFF = (
    # Strong and steady: practises every few days, mostly right.
    Staff(
        "demo_sp_camila", "Camila Araya", AZURE_TOPICS,
        (Practice("ccccccc", 1, 4), Practice("cccwcccc", 2, 4), Practice("cccccc", 4, 5), Practice("cwccccc", 0.5, 5)),
    ),
    # Steady: a few slips, comes back regularly.
    Staff(
        "demo_sp_felipe", "Felipe Gutiérrez", AZURE_TOPICS,
        (Practice("cwcccwc", 1, 4), Practice("ccwcc", 1, 5), Practice("wcccc", 3, 6), Practice("cccwcc", 0.5, 4)),
    ),
    Staff(
        "demo_sp_javiera", "Javiera Muñoz", (AI_900_TOPIC,),
        (Practice("ccwccc", 1, 5), Practice("cwcc", 3, 6), Practice("cccw", 6, 6)),
        reach=11,
    ),
    # Struggling: practises, but keeps missing; needs help.
    Staff(
        "demo_sp_sebastian", "Sebastián Vega", AZURE_TOPICS,
        (Practice("wwcwcw", 1, 3), Practice("wcwwcw", 2, 4), Practice("wwcw", 3, 5)),
    ),
    Staff(
        "demo_sp_daniela", "Daniela Poblete", (AI_900_TOPIC,),
        (Practice("wcwwcwc", 2, 4), Practice("wwcw", 1, 5), Practice("cwwc", 4, 5)),
        reach=12,
    ),
    # Stalled: was doing fine, then stopped about two weeks ago.
    Staff(
        "demo_sp_ignacio", "Ignacio Tapia", AZURE_TOPICS,
        (Practice("cwcccc", 15, 4), Practice("ccwcc", 16, 5), Practice("wcccw", 14, 4)),
        reach=9,
    ),
    # Never started: enrolled in the topics, no attempts.
    Staff("demo_sp_constanza", "Constanza Bravo", AZURE_TOPICS, (), reach=0),
)

ORG_ADMINS = ((ORG_ID, TEACHER), (PUBLIC_SERVICE_ORG_ID, COORDINATOR))

#: Every user id the seed creates. ``--reset`` deletes exactly these, never anything else.
DEMO_USER_IDS = (
    TEACHER[0],
    COORDINATOR[0],
    *(student.user_id for student in STUDENTS),
    *(person.user_id for person in STAFF),
)
DEMO_ORG_IDS = (ORG_ID, PUBLIC_SERVICE_ORG_ID)


def staff_practice(person: Staff, topic: SeedTopic) -> dict[str, Practice | None]:
    """Objective id -> this person's practice (``None``: never practised)."""
    reach = len(topic.objectives) if person.reach is None else person.reach
    return {
        objective.objective_id: person.cycle[position % len(person.cycle)]
        if position < reach and person.cycle
        else None
        for position, objective in enumerate(topic.objectives)
    }


def seed_azure_content(
    user_id: str,
    course: Course,
    materials: PostgresMaterialStore,
    questions: PostgresQuestionStore,
    now: datetime,
) -> int:
    """One page of notes per unit and its questions; returns the question count.

    Ids carry the user: material and question ids are unique across users, and
    each learner owns their own copy of the content (issue #58).
    """
    total = 0
    for unit in course.units:
        material_id = f"demo-{user_id}-{course.topic_id}-{unit.unit_id}"
        if not materials.exists(material_id):
            materials.add(
                Material(
                    material_id=material_id,
                    topic_id=course.topic_id,
                    title=unit.notes_title,
                    source=NOTES_SOURCE,
                    body=unit.notes,
                    created_at=now - timedelta(days=45),
                )
            )
        built = [
            Question(
                question_id=f"{material_id}-{objective.objective_id}-q{number}",
                topic_id=course.topic_id,
                objective_id=objective.objective_id,
                stem=item.stem,
                options=tuple(zip("ABCD", item.options)),
                correct_key="ABCD"[item.correct],
                explanation=item.explanation,
                material_id=material_id,
                created_at=now - timedelta(days=45),
            )
            for objective in unit.objectives
            for number, item in enumerate(objective.questions, start=1)
        ]
        questions.replace_for_material(material_id, built)
        total += len(built)
    return total


def seed_staff(person: Staff, connect: ConnectionProvider, schema: str, now: datetime) -> int:
    """Seeds one staff member's topics, notes and questions; returns new attempts."""
    profiles = PostgresProfileStore(connect, schema=schema, user_id=person.user_id)
    attempts = PostgresAttemptStore(connect, schema=schema, user_id=person.user_id)
    materials = PostgresMaterialStore(connect, schema=schema, user_id=person.user_id)
    questions = PostgresQuestionStore(connect, schema=schema, user_id=person.user_id)
    new_attempts = 0
    for topic in person.topics:
        new_attempts += seed_topic(
            person.user_id, topic, staff_practice(person, topic), profiles, attempts, now
        )
        seed_azure_content(person.user_id, _COURSE_BY_TOPIC[topic.topic_id], materials, questions, now)
    return new_attempts


def reset(dsn: str, schema: str) -> None:
    """Deletes the demo organizations' data, and only that.

    The scope is the fixed ``DEMO_USER_IDS`` and ``DEMO_ORG_IDS``: another
    user's rows, the implicit local user's included, are never matched. Attempts
    are append-only everywhere else (SPEC I1); this is the one place allowed to
    delete them, because they are synthetic and exist to be re-seeded.
    """
    users, orgs = list(DEMO_USER_IDS), list(DEMO_ORG_IDS)
    with psycopg.connect(dsn) as conn:
        # Questions before materials (foreign key); objectives go with their profile.
        for table in ("attempts", "questions", "materials", "profiles"):
            conn.execute(f"DELETE FROM {schema}.{table} WHERE user_id = ANY(%s)", (users,))
        conn.execute(f"DELETE FROM {schema}.org_members WHERE org_id = ANY(%s)", (orgs,))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the demo organizations.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the demo organizations' data first and reseed to the known state",
    )
    args = parser.parse_args(argv)
    dsn = os.environ.get(DATABASE_URL_VAR)
    if not dsn:
        print(f"error: set {DATABASE_URL_VAR} first (see .env.example)", file=sys.stderr)
        return 2
    schema = os.environ.get(SCHEMA_VAR) or "learning"
    now = datetime.now(timezone.utc)

    if args.reset:
        reset(dsn, schema)
        print("demo data deleted.")
    # One pool for the whole run: a connection per store call made the seed
    # take minutes (about a thousand attempts, each needing several calls).
    with ConnectionPool(conninfo=dsn, min_size=1, max_size=2, open=True) as pool:
        connect = pool.connection
        members = PostgresMemberStore(connect, schema=schema)
        for org_id, (user_id, name) in ORG_ADMINS:
            members.upsert(org_id, user_id, "org:admin", now, display_name=name)
        new_attempts = 0
        for student in STUDENTS:
            members.upsert(ORG_ID, student.user_id, "org:member", now, display_name=student.name)
            profiles = PostgresProfileStore(connect, schema=schema, user_id=student.user_id)
            attempts = PostgresAttemptStore(connect, schema=schema, user_id=student.user_id)
            for topic in student.topics:
                new_attempts += seed_student_topic(student, topic, profiles, attempts, now)
        for person in STAFF:
            members.upsert(PUBLIC_SERVICE_ORG_ID, person.user_id, "org:member", now, display_name=person.name)
            new_attempts += seed_staff(person, connect, schema, now)
    print(
        f"organization '{ORG_ID}': teacher '{TEACHER[0]}' and {len(STUDENTS)} students ready; "
        f"organization '{PUBLIC_SERVICE_ORG_ID}': coordinator '{COORDINATOR[0]}' and "
        f"{len(STAFF)} staff ready ({new_attempts} new attempt(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
