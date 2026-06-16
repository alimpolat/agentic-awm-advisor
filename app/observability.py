"""OpenTelemetry / Phoenix tracing for the Agentic AWM Advisor.

Architecture note
-----------------
The project uses google-genai SDK (`client.models.generate_content`) directly —
there is no auto-instrumentor for this SDK in the current dependency set.
We therefore patch the module-level `generate` function in `app.llm.vertex_client`
with a manual OpenInference span wrapper, and add CHAIN spans around each stage
in `app.orchestrator`.

Usage (dev / eval only)
-----------------------
    from app.observability import init_tracing
    init_tracing(launch_ui=True)          # starts Phoenix UI on :6006
    # … run generate_brief() …

Safety gate
-----------
`launch_ui=True` is NEVER called from app/main.py (which would bind :6006 on the
Cloud Run / HF container).  The gate is explicit: callers must opt-in.
The env var PHOENIX_TRACING=1 can also trigger the UI launch when set before
importing this module.

Span hierarchy produced
-----------------------
  [AGENT]  generate_brief
    [CHAIN]  stage_1_opportunity_scout
      [LLM]    gemini/opportunity_scout
    [CHAIN]  stage_2_client_insights
      [LLM]    gemini/client_insights
    [CHAIN]  stage_3a_planner
      [LLM]    gemini/planner
    [CHAIN]  stage_3b_intel_gathering
      [LLM]    gemini/intel_gathering
    [CHAIN]  stage_3c_macro
      [LLM]    gemini/macro
    [CHAIN]  stage_3d_portfolio
      [LLM]    gemini/portfolio
    [CHAIN]  stage_3e_news
      [LLM]    gemini/news
    [CHAIN]  stage_4_synthesizer
      [LLM]    gemini/synthesizer
"""
from __future__ import annotations

import functools
import json
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

# ---------------------------------------------------------------------------
# Module-level tracer (set by init_tracing)
# ---------------------------------------------------------------------------

_tracer: trace.Tracer | None = None
_initialized: bool = False


def get_tracer() -> trace.Tracer:
    """Return the module-level tracer (falls back to no-op if not initialised)."""
    if _tracer is not None:
        return _tracer
    return trace.get_tracer("agentic-awm-advisor")


# ---------------------------------------------------------------------------
# Public init
# ---------------------------------------------------------------------------


def init_tracing(launch_ui: bool = False) -> None:
    """Wire Phoenix tracing for the POC.

    Parameters
    ----------
    launch_ui:
        If True, start the Phoenix local UI on port 6006 THEN register the
        OTLP exporter pointing at it.  Only use this in eval/dev scripts.
        NEVER call with launch_ui=True from app/main.py (Cloud Run startup).
    """
    global _tracer, _initialized
    if _initialized:
        return

    _env_flag = os.environ.get("PHOENIX_TRACING", "").strip().lower()
    should_launch = launch_ui or _env_flag in ("1", "true", "yes")

    if should_launch:
        import io
        import sys
        import phoenix as px  # type: ignore[import]

        # Phoenix prints a globe-emoji line on startup which breaks cp1252 on Windows.
        # Redirect stdout to a UTF-8-safe wrapper for the duration of launch_app().
        _old_stdout = sys.stdout
        try:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
        except AttributeError:
            # stdout.buffer not available (e.g. already wrapped) — just proceed
            pass
        try:
            session = px.launch_app()
        finally:
            sys.stdout = _old_stdout

        # launch_app() starts a thread-based server on :6006 by default
        collector_endpoint = "http://localhost:6006/v1/traces"
        print("[observability] Phoenix UI launched at http://localhost:6006")
    else:
        # Headless: export to wherever PHOENIX_COLLECTOR_ENDPOINT points (or :6006
        # if the server is already running externally).
        collector_endpoint = os.environ.get(
            "PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces"
        )

    # Use phoenix.otel.register to get a properly configured TracerProvider.
    try:
        from phoenix.otel import register  # type: ignore[import]

        tp = register(
            project_name="agentic-awm-advisor",
            endpoint=collector_endpoint,
            verbose=False,
        )
    except Exception:
        # Fallback: plain OTLP exporter (no phoenix.otel dependency)
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import]
            OTLPSpanExporter,
        )

        tp = TracerProvider()
        tp.add_span_processor(
            SimpleSpanProcessor(OTLPSpanExporter(endpoint=collector_endpoint))
        )
        trace.set_tracer_provider(tp)

    _tracer = tp.get_tracer("agentic-awm-advisor")
    _initialized = True

    # Patch vertex_client.generate with the LLM span wrapper
    _patch_vertex_client()
    # Patch _base.run_agent_sync with CHAIN spans (agent_name → CHAIN wrapping the LLM span)
    _patch_run_agent_sync()
    print("[observability] tracing active → spans → Phoenix at", collector_endpoint)


# ---------------------------------------------------------------------------
# Manual LLM span wrapper
# ---------------------------------------------------------------------------

SPAN_KIND = SpanAttributes.OPENINFERENCE_SPAN_KIND
LLM_MODEL = SpanAttributes.LLM_MODEL_NAME
INPUT_VALUE = SpanAttributes.INPUT_VALUE
OUTPUT_VALUE = SpanAttributes.OUTPUT_VALUE
PROMPT_TOKENS = SpanAttributes.LLM_TOKEN_COUNT_PROMPT
COMPLETION_TOKENS = SpanAttributes.LLM_TOKEN_COUNT_COMPLETION


def _patch_run_agent_sync() -> None:
    """Monkey-patch app.agents._base.run_agent_sync to wrap each call in a CHAIN span.

    The CHAIN span name is ``stage/<agent_name>`` so Phoenix shows a clean
    hierarchy:  CHAIN(stage/planner) → LLM(gemini/...).
    """
    import app.agents._base as base_mod

    original_run = base_mod.run_agent_sync

    @functools.wraps(original_run)
    def _traced_run(agent_name: str, contents: Any, schema: Any, *, model: Any = None) -> Any:
        t = get_tracer()
        with t.start_as_current_span(f"stage/{agent_name}") as span:
            span.set_attribute(SPAN_KIND, OpenInferenceSpanKindValues.CHAIN.value)
            span.set_attribute("agent.name", agent_name)
            return original_run(agent_name, contents, schema, model=model)

    base_mod.run_agent_sync = _traced_run


def _patch_vertex_client() -> None:
    """Monkey-patch app.llm.vertex_client.generate with a span-emitting wrapper.

    The wrapper is idempotent — if already patched (e.g. init_tracing called
    twice) it will be guarded by _initialized above.
    """
    import app.llm.vertex_client as vc  # import here to avoid circular at module level

    original_generate = vc.generate

    @functools.wraps(original_generate)
    def _traced_generate(
        model: str,
        contents: Any,
        *,
        response_schema: Any = None,
        system_instruction: Any = None,
        tools: Any = None,
    ):
        t = get_tracer()
        # Derive a short span name from the calling agent (best-effort)
        span_name = f"gemini/{model.split('/')[-1]}"

        # Serialise contents for INPUT_VALUE
        try:
            input_str = contents if isinstance(contents, str) else json.dumps(contents, default=str)
        except Exception:
            input_str = str(contents)

        with t.start_as_current_span(span_name) as span:
            span.set_attribute(SPAN_KIND, OpenInferenceSpanKindValues.LLM.value)
            span.set_attribute(LLM_MODEL, model)
            span.set_attribute(INPUT_VALUE, input_str[:2000])  # truncate long prompts

            resp = original_generate(
                model,
                contents,
                response_schema=response_schema,
                system_instruction=system_instruction,
                tools=tools,
            )

            # Capture output + token counts
            try:
                out_text = resp.text or ""
                span.set_attribute(OUTPUT_VALUE, out_text[:2000])
            except Exception:
                pass

            try:
                usage = resp.usage_metadata
                if usage:
                    if hasattr(usage, "prompt_token_count") and usage.prompt_token_count:
                        span.set_attribute(PROMPT_TOKENS, usage.prompt_token_count)
                    if hasattr(usage, "candidates_token_count") and usage.candidates_token_count:
                        span.set_attribute(COMPLETION_TOKENS, usage.candidates_token_count)
            except Exception:
                pass

            return resp

    vc.generate = _traced_generate


# ---------------------------------------------------------------------------
# Context-manager helpers for stage spans
# ---------------------------------------------------------------------------


def stage_span(name: str, kind: str = "CHAIN"):
    """Return an OTel span context-manager for a pipeline stage.

    Parameters
    ----------
    name:
        Human-readable stage label (e.g. ``"stage_1_opportunity_scout"``).
    kind:
        OpenInference span kind string — ``"CHAIN"`` for orchestration,
        ``"AGENT"`` for the top-level pipeline.
    """
    t = get_tracer()
    span = t.start_span(name)
    kind_val = getattr(OpenInferenceSpanKindValues, kind, OpenInferenceSpanKindValues.CHAIN).value
    span.set_attribute(SPAN_KIND, kind_val)
    return trace.use_span(span, end_on_exit=True)
