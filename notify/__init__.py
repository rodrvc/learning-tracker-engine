"""Telling the learner what is due without them opening the app (issue #68).

Two halves, kept apart on purpose:

* :mod:`notify.digest` computes *what* to say. It reads the engine through
  :class:`~core.tracker.LearningTracker` and takes the date as a parameter,
  like everything in ``core/`` (SPEC I2): it never reads the system clock.
* :mod:`notify.senders` decides *where* it goes: the console, a file, or an
  SMTP server configured only through environment variables.

The entry point a cron runs is ``python -m scripts.send_due_digest``.
"""
