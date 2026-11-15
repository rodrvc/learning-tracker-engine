"""Tests of the daily due digest (issue #68): ``notify/`` and its cron script.

Everything runs over ``InMemory*`` stores with injected dates, and no test
opens a socket: the SMTP sender is exercised through a fake factory.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from core.clock import FixedClock
from core.models import Objective, Profile
from core.tracker import LearningTracker
from notify.digest import build_digest, practice_url, render_subject, render_text
from notify.senders import (
    ConsoleSender,
    FileSender,
    Message,
    SmtpConfigError,
    SmtpSender,
    SmtpSettings,
)
from scripts import send_due_digest
from store.memory import InMemoryAttemptStore, InMemoryProfileStore

NOW = datetime(2026, 11, 15, 11, 0, tzinfo=timezone.utc)
BASE = "https://tracker.example"


def _stores():
    profiles = InMemoryProfileStore()
    attempts = InMemoryAttemptStore()
    profiles.save_profile(
        Profile(
            profile_id="redes",
            name="Redes",
            objectives={
                "osi": Objective("osi", "Capas del modelo OSI"),
                "ip": Objective("ip", "Direccionamiento IPv4"),
                "tcp": Objective("tcp", "TCP frente a UDP"),
                "new": Objective("new", "Nunca practicado"),
            },
        )
    )
    profiles.save_profile(
        Profile(profile_id="calc", name="Cálculo", objectives={"lim": Objective("lim", "Límites")})
    )
    tracker = LearningTracker("redes", profiles, attempts, FixedClock(NOW))
    # A miss schedules the next review one day later (SPEC section 4.2):
    # osi missed 10 days ago -> ~9 days overdue; ip missed 3 days ago -> ~2.
    tracker.record_attempt(objective_id="osi", correct=False, at=NOW - timedelta(days=10))
    tracker.record_attempt(objective_id="ip", correct=False, at=NOW - timedelta(days=3))
    # tcp answered just now: not due yet.
    tracker.record_attempt(objective_id="tcp", correct=True, at=NOW - timedelta(minutes=5))
    return profiles, attempts


def test_digest_names_due_objectives_in_urgency_order():
    profiles, attempts = _stores()
    digest = build_digest(profiles, attempts, NOW, BASE)
    assert [t.topic_id for t in digest.topics] == ["redes"]  # calc has nothing due
    topic = digest.topics[0]
    assert topic.due_count == 2
    assert [item.objective_id for item in topic.named] == ["osi", "ip"]
    assert topic.named[0].title == "Capas del modelo OSI"
    assert topic.named[0].days_overdue > topic.named[1].days_overdue >= 1
    assert topic.practice_url == "https://tracker.example/#/learning/redes"


def test_unstarted_objectives_are_not_reported_as_due():
    profiles, attempts = _stores()
    digest = build_digest(profiles, attempts, NOW, BASE)
    assert "new" not in {item.objective_id for t in digest.topics for item in t.named}


def test_nothing_due_means_empty_digest_and_no_render():
    profiles, attempts = _stores()
    digest = build_digest(profiles, attempts, NOW, BASE, topic_ids=["calc"])
    assert digest.is_empty
    with pytest.raises(ValueError):
        render_text(digest)


def test_digest_depends_only_on_as_of():
    profiles, attempts = _stores()
    early = NOW - timedelta(days=20)
    assert build_digest(profiles, attempts, early, BASE).is_empty


def test_archived_topics_are_skipped():
    profiles, attempts = _stores()
    profiles.set_archived("redes", True)
    assert build_digest(profiles, attempts, NOW, BASE).is_empty


def test_named_list_is_capped_and_rest_is_counted():
    profiles, attempts = _stores()
    digest = build_digest(profiles, attempts, NOW, BASE, named_per_topic=1)
    text = render_text(digest)
    assert "Capas del modelo OSI" in text
    assert "Direccionamiento IPv4" not in text
    assert "y 1 más" in text


def test_rendered_copy_is_spanish_and_links_to_practice():
    profiles, attempts = _stores()
    digest = build_digest(profiles, attempts, NOW, BASE)
    assert render_subject(digest) == "Hoy tienes 2 repasos pendientes"
    text = render_text(digest)
    assert "Redes - 2 por repasar" in text
    assert "atrasado" in text
    assert "Practicar: https://tracker.example/#/learning/redes" in text


def test_practice_url_strips_trailing_slash():
    assert practice_url("https://x.example/", "t") == "https://x.example/#/learning/t"


# ------------------------------------------------------------------ senders


def test_console_sender_writes_message():
    stream = io.StringIO()
    ConsoleSender(stream).send(Message("a@example.com", "Asunto", "Cuerpo"))
    assert "To: a@example.com" in stream.getvalue()
    assert "Cuerpo" in stream.getvalue()


def test_file_sender_appends(tmp_path):
    path = tmp_path / "out" / "digests.log"
    sender = FileSender(path)
    sender.send(Message("a@example.com", "S1", "B1"))
    sender.send(Message("b@example.com", "S2", "B2"))
    content = path.read_text(encoding="utf-8")
    assert "B1" in content and "B2" in content


class FakeSmtp:
    instances: list["FakeSmtp"] = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.calls: list[str] = []
        self.sent = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")

    def send_message(self, message):
        self.sent.append(message)


def test_smtp_settings_from_env_defaults_and_errors():
    settings = SmtpSettings.from_env(
        {"LEARNING_TRACKER_SMTP_HOST": "smtp.example", "LEARNING_TRACKER_SMTP_FROM": "no-reply@example.com"}
    )
    assert (settings.port, settings.security, settings.user) == (587, "starttls", None)
    with pytest.raises(SmtpConfigError, match="LEARNING_TRACKER_SMTP_HOST"):
        SmtpSettings.from_env({})
    with pytest.raises(SmtpConfigError):
        SmtpSettings.from_env(
            {
                "LEARNING_TRACKER_SMTP_HOST": "h",
                "LEARNING_TRACKER_SMTP_FROM": "f@example.com",
                "LEARNING_TRACKER_SMTP_USER": "only-user",
            }
        )


def test_smtp_sender_uses_starttls_and_login_without_network():
    FakeSmtp.instances.clear()
    settings = SmtpSettings(host="smtp.example", port=587, sender="no-reply@example.com", user="u", password="p")
    SmtpSender(settings, smtp_factory=FakeSmtp).send(Message("a@example.com", "Asunto", "Cuerpo"))
    smtp = FakeSmtp.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example", 587)
    assert smtp.calls == ["starttls", "login:u", "quit"]
    sent = smtp.sent[0]
    assert sent["To"] == "a@example.com" and sent["Subject"] == "Asunto"
    assert "Cuerpo" in sent.get_content()


# ------------------------------------------------------------------- script


def test_parse_recipients():
    parsed = send_due_digest.parse_recipients(json.dumps({"a@example.com": ["redes"], "b@example.com": "*"}))
    assert parsed == {"a@example.com": ["redes"], "b@example.com": None}
    for bad in (None, "", "[]", "{}", "not json", '{"nope": "*"}', '{"a@example.com": 3}'):
        with pytest.raises(send_due_digest.ConfigError):
            send_due_digest.parse_recipients(bad)


class RecordingSender:
    def __init__(self, fail_for=()):
        self.sent: list[Message] = []
        self.fail_for = set(fail_for)

    def send(self, message):
        if message.to in self.fail_for:
            raise OSError("boom")
        self.sent.append(message)


def test_run_sends_only_to_recipients_with_something_due():
    profiles, attempts = _stores()
    sender = RecordingSender()
    log = io.StringIO()
    code = send_due_digest.run(
        profiles,
        attempts,
        sender,
        {"a@example.com": ["redes"], "b@example.com": ["calc"], "c@example.com": None},
        NOW,
        BASE,
        log=log,
    )
    assert code == 0
    assert [m.to for m in sender.sent] == ["a@example.com", "c@example.com"]
    assert "b@example.com: nothing due, nothing sent" in log.getvalue()


def test_run_keeps_going_after_a_failed_send():
    profiles, attempts = _stores()
    sender = RecordingSender(fail_for={"a@example.com"})
    code = send_due_digest.run(
        profiles, attempts, sender, {"a@example.com": None, "c@example.com": None}, NOW, BASE, log=io.StringIO()
    )
    assert code == 1
    assert [m.to for m in sender.sent] == ["c@example.com"]


def test_main_reports_config_errors_without_touching_the_database(capsys):
    assert send_due_digest.main([], env={}) == 2
    assert "LEARNING_TRACKER_DIGEST_RECIPIENTS" in capsys.readouterr().err
    env = {"LEARNING_TRACKER_DIGEST_RECIPIENTS": '{"a@example.com": "*"}'}
    assert send_due_digest.main(["--sender", "smtp"], env=env) == 2
    assert send_due_digest.main(["--as-of", "2026-11-15T11:00:00"], env=env) == 2
    assert send_due_digest.main([], env=env) == 2  # no database URL
    assert "LEARNING_TRACKER_DATABASE_URL" in capsys.readouterr().err
