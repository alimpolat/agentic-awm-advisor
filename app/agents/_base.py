"""Shared helper for the stage agents: one structured Gemini call with a None-guard.

Usage
-----
    from app.agents._base import run_agent_sync
    result: MySchema = run_agent_sync("my_agent", contents_str, MySchema)

`agent_name` is BOTH the prompt filename stem (loaded via prompt_loader) and
the label used in the RuntimeError message.  `model` defaults to
settings.gemini_model_flash.
"""
from typing import Any, TypeVar

from pydantic import ValidationError

from app.llm.vertex_client import generate
from app.llm.prompt_loader import load_prompt
from app.settings import settings

T = TypeVar("T")


def run_agent_sync(
    agent_name: str,
    contents: str,
    schema: type[T],
    *,
    model: str | None = None,
) -> T:
    """Call Gemini with the agent's system prompt + a response_schema; return the parsed object.

    Parameters
    ----------
    agent_name:
        Used as the prompt filename stem (``{agent_name}.jinja2`` or similar)
        and as the label in the RuntimeError message.
    contents:
        The user-turn string sent to the model.
    schema:
        A Pydantic model class; passed to ``generate`` as ``response_schema``.
    model:
        Override the default flash model. Defaults to ``settings.gemini_model_flash``.

    Raises
    ------
    RuntimeError
        If the model returns no valid structured output after 2 attempts (one retry).
        A ValidationError on ``resp.parsed`` — which the google-genai SDK can raise when
        the model response violates a schema constraint (e.g. ``min_length``) — is caught
        and retried; the second failure surfaces as RuntimeError, not ValidationError.
    """
    chosen = model or settings.gemini_model_flash
    from app import agent_monitor

    agent_monitor.record_start(
        agent_name, f"thinking over {len(contents):,} chars → {schema.__name__} on {chosen}"
    )
    last_err: str | None = None
    for attempt in range(2):  # one retry
        try:
            resp = generate(
                model=chosen,
                contents=contents,
                system_instruction=load_prompt(agent_name),
                response_schema=schema,
            )
            parsed = resp.parsed  # may raise ValidationError on a non-conforming response
            if parsed is not None:
                u = getattr(resp, "usage_metadata", None)
                tin = getattr(u, "prompt_token_count", 0) or 0
                tout = getattr(u, "candidates_token_count", 0) or 0
                agent_monitor.record_done(
                    agent_name,
                    f"returned {schema.__name__} ({tin:,}→{tout:,} tokens)",
                    tokens_in=tin, tokens_out=tout,
                )
                return parsed
            last_err = f"empty parsed output (raw: {resp.text!r})"
        except ValidationError as e:
            last_err = f"schema validation failed: {e}"
    agent_monitor.record_error(agent_name, last_err or "no valid structured output")
    raise RuntimeError(
        f"{agent_name}: model returned no valid structured output after 2 attempts. "
        f"Last error: {last_err}"
    )


__all__ = ["run_agent_sync"]
