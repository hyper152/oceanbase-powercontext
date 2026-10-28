"""Provenance for a coding-model answer.

Every code change in this solution is produced by a MiniMax model.  Two
different paths can produce the answer and both are recorded the same way:

``api``
    The answer comes from the MiniMax HTTP API.  The request carries the
    retrieved context pack, and the response carries the model's answer.

``session``
    The answer comes from the MiniMax model that runs inside the agent
    session.  The session model is driven by exactly the same prompt and
    context pack, but the platform account may have no usable quota, so the
    HTTP endpoint cannot be used.  The answer text is written to a file and
    stamped with the digests of the prompt and of the context pack, so the
    chain "retrieved context -> prompt -> model answer -> applied diff" stays
    verifiable.

The module never stores a credential and never keeps a private reasoning
trace: only the public answer text and its digests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["ORIGIN_API", "ORIGIN_SESSION", "ModelAnswer"]

ORIGIN_API = "api"
ORIGIN_SESSION = "session"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelAnswer:
    """One model answer together with the digests of its inputs."""

    model: str
    origin: str
    content: str
    prompt: str = ""
    context_pack: dict[str, Any] = field(default_factory=dict)
    api_attempt: dict[str, Any] | None = None
    answer_path: str | None = None
    generated_at: str = field(default_factory=_now)

    @property
    def answer_sha256(self) -> str:
        return _sha256_text(self.content)

    @property
    def prompt_sha256(self) -> str:
        return _sha256_text(self.prompt)

    @property
    def context_pack_sha256(self) -> str:
        return _sha256_text(json.dumps(self.context_pack, ensure_ascii=False, sort_keys=True))

    def to_response_json(self) -> dict[str, Any]:
        """Render the answer in the shape that ``sddctx apply`` consumes."""
        return {
            "schema": "sddctx.model-answer.v1",
            "generated_at": self.generated_at,
            "status": "ok",
            "model": self.model,
            "origin": self.origin,
            "answer_file": self.answer_path,
            "answer_sha256": self.answer_sha256,
            "prompt_sha256": self.prompt_sha256,
            "context_pack_sha256": self.context_pack_sha256,
            "api_attempt": self.api_attempt,
            "note": (
                "The API key is never stored and the model's private reasoning trace is discarded. "
                "The digests bind this answer to the exact prompt and context pack it was produced from."
            ),
            "content": self.content,
        }

    def to_json(self) -> dict[str, Any]:
        payload = self.to_response_json()
        payload["context_pack"] = self.context_pack
        payload["prompt"] = self.prompt
        return payload


def load_model_answer(
    answer_path: str | Path,
    *,
    model: str,
    origin: str = ORIGIN_SESSION,
    prompt_path: str | Path | None = None,
    context_pack_path: str | Path | None = None,
    api_attempt_path: str | Path | None = None,
) -> ModelAnswer:
    """Read a model answer from disk and bind it to its prompt and context pack."""
    if origin not in (ORIGIN_API, ORIGIN_SESSION):
        raise ValueError(f"unknown origin: {origin}")  # noqa: TRY003

    answer_file = Path(answer_path)
    content = answer_file.read_text(encoding="utf-8")

    prompt = ""
    if prompt_path is not None:
        prompt = Path(prompt_path).read_text(encoding="utf-8")

    context_pack: dict[str, Any] = {}
    if context_pack_path is not None:
        context_pack = json.loads(Path(context_pack_path).read_text(encoding="utf-8"))

    api_attempt: dict[str, Any] | None = None
    if api_attempt_path is not None:
        api_attempt = json.loads(Path(api_attempt_path).read_text(encoding="utf-8"))

    return ModelAnswer(
        model=model,
        origin=origin,
        content=content,
        prompt=prompt,
        context_pack=context_pack,
        api_attempt=api_attempt,
        answer_path=str(answer_file),
    )
