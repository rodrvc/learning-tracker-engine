"""The web backend: a FastAPI application over the engine in ``core/``.

This package only wires the engine to HTTP. It holds no business rules of its
own: those live in ``core/`` (see SPEC.md) and this layer imports and calls
``LearningTracker`` directly, never through a subprocess.

Vocabulary translation: the product calls the study subject a **topic**; the
engine calls the same thing a **profile** (``core.models.Profile``,
``ProfileStore``). That translation happens only at the edge of this
package (request/response models in ``web/routers/``) and nowhere else —
internally everything below the HTTP layer keeps saying "profile", matching
the engine's own vocabulary.
"""

from __future__ import annotations
