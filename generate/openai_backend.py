"""The real ``QuestionGenerator``, backed by the OpenAI API.

Uses the official ``openai`` SDK (the ``generate`` extra in
``pyproject.toml``, installed in CI so this module's one untested branch,
building a real client, still gets a static check). No raw HTTP and no
compatibility shim. ``core/`` keeps zero runtime dependencies; this package is
where the network-facing seam lives, in the same spirit as
``store/postgres.py``: a thin adapter behind a ``Protocol``, constructed with
an injectable client so it can be tested without ever reaching the network.

Everything about what makes a question worth answering lives in
``generate.prompting``, not here. This module is only transport: build the
request, turn the provider's failures into this package's own errors, hand the
parsed result over. That split is what made changing provider a small change
rather than a rewrite.

Structured output goes through ``client.responses.parse(text_format=...)``,
which validates the response against the schema before it is returned. The
model returns its refusals as a field rather than as an exception, so that is
checked explicitly: a refusal is a distinct event from a malformed response,
and reporting one as the other sends whoever debugs it looking for a schema
bug that is not there.
"""

from __future__ import annotations

import random
from typing import Sequence

import openai

from content.models import Material
from core.clock import Clock
from core.models import Objective

from .errors import GenerationError, MissingCredentialsError
from .generator import GenerationResult
from .prompting import (
    DEFAULT_MAX_TOKENS,
    _GenerationSchema,
    _SYSTEM_PROMPT,
    _existing_objectives_digest,
    _target_question_count,
    build_result,
)

DEFAULT_MODEL = "gpt-5"


class OpenAIGenerator:
    """``QuestionGenerator`` backed by the OpenAI API.

    Args:
        client: an ``openai.OpenAI``-shaped object. Built with no arguments
            (it resolves the key from the environment itself) when not
            supplied. Tests inject a fake here so no network call is made.
        model: overridable so a caller is not stuck patching a module
            constant to test or tune it.
        max_output_tokens: same reasoning as ``model``.
        random_source: source of the option-shuffle randomness. Injectable
            for determinism in tests, exactly like ``now: Clock``.
    """

    def __init__(
        self,
        client: object | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = DEFAULT_MAX_TOKENS,
        random_source: random.Random | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._random = random_source or random.Random()

    def generate(
        self,
        material: Material,
        existing_objectives: Sequence[Objective],
        *,
        now: Clock,
    ) -> GenerationResult:
        """See ``generate.generator.QuestionGenerator.generate``."""
        try:
            # Built inside the guard on purpose. With no credential resolvable
            # the SDK raises from the constructor, not from the request, so
            # building it outside would have let that escape unhandled and
            # surface as a 500 - the shape of failure this package exists to
            # prevent, on the most ordinary configuration mistake there is.
            client = self._client or openai.OpenAI()
        except openai.OpenAIError as exc:
            raise MissingCredentialsError(
                "no OpenAI credential is configured, so question generation is "
                "unavailable. Everything else keeps working."
            ) from exc

        try:
            response = client.responses.parse(
                model=self._model,
                max_output_tokens=self._max_output_tokens,
                instructions=_SYSTEM_PROMPT,
                input=(
                    "Existing objectives for this topic:\n"
                    f"{_existing_objectives_digest(existing_objectives)}\n\n"
                    f"Produce {_target_question_count(material)} questions.\n\n"
                    f"Material title: {material.title}\n"
                    f"Material:\n{material.body}"
                ),
                text_format=_GenerationSchema,
            )

            # A refusal comes back as a field, not as an exception. It is a
            # distinct event from a malformed response and must not be
            # reported as one.
            refusal = _refusal_of(response)
            if refusal:
                raise GenerationError(
                    f"the model refused to generate questions for this material: {refusal}"
                )

            # ``output_parsed`` is None when nothing parsed, which a refusal
            # already covers above but an incomplete or filtered response
            # does not. Guard it rather than letting a bare AttributeError
            # stand in for "malformed".
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                status = getattr(response, "status", None)
                raise GenerationError(
                    f"the model produced no structured output (status={status!r})"
                )

            return build_result(
                self._random, material, existing_objectives, parsed, now.now()
            )
        except openai.AuthenticationError as exc:
            raise MissingCredentialsError(
                "OpenAI rejected the configured credential (or none is configured); "
                "question generation is unavailable until a valid one is set up. "
                "Everything else keeps working."
            ) from exc
        except GenerationError:
            raise
        except Exception as exc:  # SDK errors, network errors, schema mismatches
            raise GenerationError(f"could not generate questions: {exc}") from exc


def _refusal_of(response: object) -> str | None:
    """The model's refusal text, when it refused.

    The refusal lives on an output content item rather than at the top level,
    so this walks for it instead of reading one attribute. Written
    defensively because it runs on the one path no test exercises against the
    real API: a shape change here must not turn a refusal into an unrelated
    crash.
    """
    for item in getattr(response, "output", None) or ():
        for part in getattr(item, "content", None) or ():
            refusal = getattr(part, "refusal", None)
            if refusal:
                return str(refusal)
    return None


__all__ = ["OpenAIGenerator", "DEFAULT_MODEL"]
