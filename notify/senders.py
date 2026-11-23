"""Where a digest goes. Pluggable: anything with ``send(message)`` is a sender.

* :class:`ConsoleSender` (the default) prints the message. Safe anywhere,
  including a cron whose logs are the only place anyone looks.
* :class:`FileSender` appends it to a file, for a demo or an audit trail.
* :class:`SmtpSender` sends real email through any SMTP server, configured
  only by environment variables. Standard library ``smtplib``, no provider
  SDK: switching provider is changing four variables, not a dependency.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Mapping, Protocol, TextIO

#: SMTP settings. Host and sender address are required to use SMTP at all.
SMTP_HOST_VAR = "LEARNING_TRACKER_SMTP_HOST"
SMTP_PORT_VAR = "LEARNING_TRACKER_SMTP_PORT"
SMTP_USER_VAR = "LEARNING_TRACKER_SMTP_USER"
SMTP_PASSWORD_VAR = "LEARNING_TRACKER_SMTP_PASSWORD"
SMTP_FROM_VAR = "LEARNING_TRACKER_SMTP_FROM"
#: ``starttls`` (default, port 587), ``ssl`` (port 465) or ``none``.
SMTP_SECURITY_VAR = "LEARNING_TRACKER_SMTP_SECURITY"

DEFAULT_SMTP_PORTS = {"starttls": 587, "ssl": 465, "none": 25}


@dataclass(frozen=True)
class Message:
    """One rendered digest addressed to one recipient."""

    to: str
    subject: str
    body: str


class Sender(Protocol):
    def send(self, message: Message) -> None: ...


class ConsoleSender:
    """Writes the message to a stream (stdout by default)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def send(self, message: Message) -> None:
        import sys

        stream = self._stream or sys.stdout
        stream.write(_as_text(message))
        stream.flush()


class FileSender:
    """Appends the message to a file, creating it if needed."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def send(self, message: Message) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(_as_text(message))


def _as_text(message: Message) -> str:
    return (
        f"To: {message.to}\nSubject: {message.subject}\n\n{message.body}\n"
        + "-" * 60
        + "\n"
    )


class SmtpConfigError(RuntimeError):
    """SMTP was requested but a required variable is missing or invalid."""


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    sender: str
    security: str = "starttls"
    user: str | None = None
    password: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "SmtpSettings":
        host = env.get(SMTP_HOST_VAR) or ""
        sender = env.get(SMTP_FROM_VAR) or ""
        missing = [name for name, value in ((SMTP_HOST_VAR, host), (SMTP_FROM_VAR, sender)) if not value]
        if missing:
            raise SmtpConfigError(f"missing required environment variable(s): {', '.join(missing)}")
        security = (env.get(SMTP_SECURITY_VAR) or "starttls").lower()
        if security not in DEFAULT_SMTP_PORTS:
            raise SmtpConfigError(
                f"{SMTP_SECURITY_VAR} must be one of {sorted(DEFAULT_SMTP_PORTS)}, got {security!r}"
            )
        raw_port = env.get(SMTP_PORT_VAR)
        try:
            port = int(raw_port) if raw_port else DEFAULT_SMTP_PORTS[security]
        except ValueError as exc:
            raise SmtpConfigError(f"{SMTP_PORT_VAR} must be an integer, got {raw_port!r}") from exc
        user = env.get(SMTP_USER_VAR) or None
        password = env.get(SMTP_PASSWORD_VAR) or None
        if (user is None) != (password is None):
            raise SmtpConfigError(f"set both {SMTP_USER_VAR} and {SMTP_PASSWORD_VAR}, or neither")
        return cls(host=host, port=port, sender=sender, security=security, user=user, password=password)


class SmtpSender:
    """Sends each message as a plain-text email.

    Args:
        settings: connection settings, usually :meth:`SmtpSettings.from_env`.
        smtp_factory: builds the connection; injected so tests never open a
            socket. Defaults to ``smtplib.SMTP`` / ``smtplib.SMTP_SSL``.
    """

    def __init__(
        self,
        settings: SmtpSettings,
        smtp_factory: Callable[[str, int], smtplib.SMTP] | None = None,
    ) -> None:
        self._settings = settings
        if smtp_factory is None:
            smtp_factory = smtplib.SMTP_SSL if settings.security == "ssl" else smtplib.SMTP
        self._factory = smtp_factory

    def send(self, message: Message) -> None:
        email = EmailMessage()
        email["From"] = self._settings.sender
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.body)
        with self._factory(self._settings.host, self._settings.port) as smtp:
            if self._settings.security == "starttls":
                smtp.starttls()
            if self._settings.user is not None:
                smtp.login(self._settings.user, self._settings.password or "")
            smtp.send_message(email)
