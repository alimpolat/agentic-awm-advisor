"""Chat agent — ReAct loop via Gemini Automatic Function Calling (AFC).

Task 4.4: Replaces the single retrieve+answer stub with a multi-tool ReAct loop
using google-genai AFC over four tools:
  1. retrieve_from_corpus  — hybrid dense+sparse retrieval over the document corpus
  2. retrieve_from_brief   — load and summarise the cached BriefSchema
  3. lookup_client_holdings — Bergström portfolio + IPS limits
  4. web_grounding          — grounded web search (Google Search tool, degraded on error)

The SDK executes the AFC loop automatically (up to 5 remote calls); we collect
EvidenceRef objects via a shared closure list for citation.

Manual ReAct fallback is also implemented and used if AFC raises an exception
(e.g. serialisation issues with closures on some SDK versions).

Async interface: await run(req) dispatches _run_sync via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from google.genai import types

from app.llm.prompt_loader import load_prompt
from app.llm.vertex_client import client as genai_client, generate
from app.retrieval.hybrid import retrieve
from app.schemas import BriefSchema, ChatRequest, ChatResponse, EvidenceRef
from app.settings import settings

logger = logging.getLogger(__name__)

_WEB_GROUNDING_TIMEOUT_S: float = 30.0
_MAX_TOOL_CALLS: int = 5

_WEB_GROUNDING_SYSTEM = (
    "You are a financial news researcher with access to Google Search grounding. "
    "Find recent, real information relevant to the query. "
    "Respond in plain text (NOT JSON). Be concise and factual. "
    "Only report what your grounded search actually returns — never fabricate."
)


# ---------------------------------------------------------------------------
# JSON answer unwrapper
# ---------------------------------------------------------------------------

def _unwrap_json_answer(text: str) -> str:
    """If the model returned a ChatResponse JSON blob instead of plain text,
    extract just the 'answer' field.  Otherwise return the text unchanged.

    This handles the case where the old JSON-output system prompt is still
    cached, or the model decides to format its response as structured JSON.
    """
    stripped = text.strip()
    if not stripped.startswith("{"):
        return text

    try:
        data = json.loads(stripped)
        if isinstance(data, dict) and "answer" in data:
            inner = data["answer"]
            if isinstance(inner, str) and inner.strip():
                logger.debug("chat: unwrapped JSON answer (%d chars)", len(inner))
                return inner
    except (json.JSONDecodeError, ValueError):
        pass

    return text


# ---------------------------------------------------------------------------
# Refusal detection (used to trigger the manual ReAct fallback)
# ---------------------------------------------------------------------------

_REFUSAL_PHRASES = (
    "i don't know", "i cannot", "cannot find", "don't have enough",
    "unable to", "internal error", "issue with the available tools",
    "error in accessing", "error with the available tools", "unable to find",
    "i apologize", "i'm sorry",
)


def _is_refusal(text: str) -> bool:
    t = (text or "").lower()
    return any(p in t for p in _REFUSAL_PHRASES)


# ---------------------------------------------------------------------------
# Synchronous core
# ---------------------------------------------------------------------------

def _run_sync(req: ChatRequest) -> ChatResponse:
    """Synchronous ReAct loop — called via asyncio.to_thread from `run`."""
    refs: list[EvidenceRef] = []

    # ── Tool definitions (closures that share the `refs` collector) ──────────

    def retrieve_from_corpus(query: str) -> str:
        """Search the macro + a Nordic private bank + Bergstrom document corpus for relevant passages."""
        try:
            chunks = retrieve(query, top_k=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("retrieve_from_corpus: retrieval error: %s", exc)
            return "(corpus retrieval failed)"
        if not chunks:
            return "(no relevant passages found in corpus)"
        parts: list[str] = []
        for c in chunks:
            refs.append(EvidenceRef(
                doc_id=c.doc_id,
                chunk_id=c.chunk_id,
                excerpt=c.text[:200],
            ))
            parts.append(f"[doc_id={c.doc_id!r} chunk_id={c.chunk_id!r}]\n{c.text[:500]}")
        return "\n\n".join(parts)

    def retrieve_from_brief(topic: str) -> str:  # noqa: ARG001
        """Look up the current Monday brief: its opportunities, next-best-actions, risk flags, and weekend changes."""
        try:
            from pathlib import Path
            cache_path = Path("data/brief_cache_bergstrom.json")
            if not cache_path.exists():
                return "(brief cache not found)"
            brief = BriefSchema.model_validate_json(cache_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("retrieve_from_brief: load error: %s", exc)
            return "(brief cache unavailable)"

        refs.append(EvidenceRef(doc_id="brief_cache_bergstrom"))

        lines: list[str] = [f"BRIEF for {brief.client_id} (generated {brief.generated_at})\n"]

        # Opportunities
        if brief.opportunities:
            lines.append("OPPORTUNITIES:")
            for opp in brief.opportunities:
                lines.append(
                    f"  [{opp.trigger_type.upper()}] {opp.asset_class}: "
                    f"{opp.suggested_topic} (confidence={opp.confidence})"
                )

        # Next best actions
        if brief.three_nbas:
            lines.append("\nNEXT BEST ACTIONS:")
            for nba in brief.three_nbas:
                lines.append(
                    f"  [{nba.suggested_priority.upper()}] {nba.title}: "
                    f"{nba.rationale} | impact={nba.projected_impact} | confidence={nba.confidence}"
                )

        # Risk flags
        if brief.risk_flags:
            lines.append("\nRISK FLAGS:")
            for flag in brief.risk_flags:
                if flag.severity != "none":
                    lines.append(f"  [{flag.severity.upper()}] {flag.kind}: {flag.note}")

        # Weekend changes (brief)
        if brief.weekend_changes:
            lines.append(f"\nWEEKEND CHANGES: {len(brief.weekend_changes)} item(s)")
            for change in brief.weekend_changes[:3]:
                raw = change.model_dump() if hasattr(change, "model_dump") else {}
                headline = raw.get("headline") or raw.get("claim") or str(raw)[:100]
                lines.append(f"  - {headline[:120]}")

        return "\n".join(lines)

    def lookup_client_holdings() -> str:
        """Return the Bergstrom client's holdings, allocations, and IPS limits."""
        try:
            from app.fixtures import load_portfolio
            portfolio = load_portfolio("bergstrom")
        except Exception as exc:  # noqa: BLE001
            logger.warning("lookup_client_holdings: load error: %s", exc)
            return "(portfolio unavailable)"

        refs.append(EvidenceRef(doc_id="bergstrom_portfolio_q1_2026"))

        lines: list[str] = [
            f"CLIENT: {portfolio.get('client_name', 'Bergström')} | AUM: {portfolio.get('aum_sek', 'N/A'):,} SEK",
            "",
        ]

        # Current allocation
        current_alloc = portfolio.get("current_allocation", {})
        target_alloc = portfolio.get("target_allocation", {})
        if current_alloc or target_alloc:
            lines.append("ALLOCATION (current vs target, % of AUM):")
            all_keys = set(current_alloc) | set(target_alloc)
            for k in sorted(all_keys):
                # The portfolio JSON stores allocations as FRACTIONS (0.15 == 15%).
                curr = current_alloc.get(k, 0) * 100
                tgt = target_alloc.get(k, 0) * 100
                drift = curr - tgt
                drift_str = f"{drift:+.1f}pp" if abs(drift) > 1e-9 else "on-target"
                lines.append(f"  {k}: {curr:.0f}% current / {tgt:.0f}% target  ({drift_str})")

        # IPS limits (read the actual fixture fields)
        ips_lines: list[str] = []
        if portfolio.get("single_position_limit_pct") is not None:
            ips_lines.append(
                f"  Single-position limit: {portfolio['single_position_limit_pct']:.0f}% of AUM "
                "(funds/ETFs exempt)"
            )
        if portfolio.get("fx_floor_pct") is not None:
            ips_lines.append(
                f"  FX floor: minimum {portfolio['fx_floor_pct']:.0f}% SEK base-currency exposure"
            )
        elif portfolio.get("fx_policy"):
            ips_lines.append(f"  FX policy: {portfolio['fx_policy']}")
        if ips_lines:
            lines.append("\nIPS CONSTRAINTS:")
            lines.extend(ips_lines)

        # Top holdings
        holdings = portfolio.get("holdings", [])
        if holdings:
            lines.append(f"\nHOLDINGS ({len(holdings)} positions):")
            for h in holdings[:10]:
                lines.append(
                    f"  {h.get('ticker', '?'):<8} {h.get('name', '?'):<35} "
                    f"MV={h.get('current_mv', 0):>12,.0f} SEK  "
                    f"({h.get('asset_class', '?')}) YTD={h.get('ytd_return_pct', 0):+.1f}%"
                )
            if len(holdings) > 10:
                lines.append(f"  ... and {len(holdings) - 10} more positions")

        return "\n".join(lines)

    def web_grounding(query: str) -> str:
        """Search the web for recent news/data when the corpus and brief are insufficient."""
        try:
            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(_web_grounding_sync, query, refs)
            try:
                return future.result(timeout=_WEB_GROUNDING_TIMEOUT_S)
            except FuturesTimeoutError:
                logger.warning("web_grounding: timed out after %.0fs", _WEB_GROUNDING_TIMEOUT_S)
                return "(web search timed out)"
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("web_grounding: error: %s", exc)
            return "(web search unavailable)"

    tool_map = {
        "retrieve_from_corpus": retrieve_from_corpus,
        "retrieve_from_brief": retrieve_from_brief,
        "lookup_client_holdings": lookup_client_holdings,
        "web_grounding": web_grounding,
    }

    # ── Try AFC (Automatic Function Calling) ────────────────────────────────
    answer = ""
    try:
        cfg = types.GenerateContentConfig(
            system_instruction=load_prompt("chat"),
            tools=list(tool_map.values()),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=_MAX_TOOL_CALLS,
            ),
        )
        resp = genai_client.models.generate_content(
            model=settings.gemini_model_flash,
            contents=req.question,
            config=cfg,
        )
        answer = _unwrap_json_answer(resp.text or "")
        logger.info("chat AFC: answer length=%d, refs collected=%d", len(answer), len(refs))

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "chat: AFC failed (%s: %s) — falling back to manual ReAct loop",
            type(exc).__name__,
            exc,
        )
        answer = _manual_react(question=req.question, tool_map=tool_map)

    # ── AFC sometimes "completes" without actually grounding (tool execution
    #    under a worker thread can silently no-op). If we got no evidence refs
    #    and the answer reads like a refusal, retry via the explicit manual
    #    ReAct loop, which invokes the tool functions directly. ───────────────
    if not refs and (not answer.strip() or _is_refusal(answer)):
        logger.info("chat: AFC produced no grounded refs (answer=%.40r) — retrying manual ReAct", answer)
        answer = _manual_react(question=req.question, tool_map=tool_map)

    # ── Build response ───────────────────────────────────────────────────────
    if not answer or answer.strip() == "":
        return ChatResponse(
            answer="I don't have enough grounded information to answer that.",
            cited_refs=[],
            confidence="low_needs_verification",
        )

    deduped = _dedup_refs(refs)

    # Confidence heuristic
    answer_lower = answer.lower()
    if not answer.strip() or any(
        phrase in answer_lower for phrase in
        ["i don't know", "i cannot", "cannot find", "don't have enough", "unable to find"]
    ):
        confidence: str = "low_needs_verification"
    elif deduped:
        confidence = "high"
    else:
        confidence = "medium"

    return ChatResponse(
        answer=answer,
        cited_refs=deduped,
        confidence=confidence,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Web grounding helper (runs in thread)
# ---------------------------------------------------------------------------

def _web_grounding_sync(query: str, refs: list[EvidenceRef]) -> str:
    """Execute a grounded Gemini Flash call and return plain text.

    Appends EvidenceRef entries (one per grounding URI) to *refs*.
    Raises on any error (caller wraps in try/except).
    """
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    response = generate(
        model=settings.gemini_model_flash,
        contents=query,
        system_instruction=_WEB_GROUNDING_SYSTEM,
        tools=[grounding_tool],
    )

    grounded_text = response.text or ""

    # Extract grounding URIs
    try:
        candidates = response.candidates or []
        if candidates:
            gm = candidates[0].grounding_metadata
            if gm is not None:
                for chunk in (gm.grounding_chunks or []):
                    web = getattr(chunk, "web", None)
                    if web is not None:
                        uri = getattr(web, "uri", None) or ""
                        title = getattr(web, "title", None) or uri
                        if uri.startswith("http"):
                            refs.append(EvidenceRef(
                                doc_id=title[:80] if title else uri[:80],
                                source_uri=uri,
                            ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_grounding: error extracting URIs: %s", exc)

    return grounded_text if grounded_text else "(web search returned no results)"


# ---------------------------------------------------------------------------
# Manual ReAct fallback (inspect function_call parts, loop up to 5 iterations)
# ---------------------------------------------------------------------------

def _manual_react(
    question: str,
    tool_map: dict[str, Any],
) -> str:
    """Manual ReAct loop for when AFC fails.

    Sends the question, inspects function_call parts, executes tools,
    appends function_response parts, repeats up to _MAX_TOOL_CALLS times.
    Returns the final model text.
    """
    system_instruction = load_prompt("chat")
    contents: list[Any] = [question]

    for _iteration in range(_MAX_TOOL_CALLS + 1):
        # Define function declarations for manual mode
        tool_declarations = [
            types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name="retrieve_from_corpus",
                    description="Search the macro + a Nordic private bank + Bergstrom document corpus for relevant passages.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"query": types.Schema(type=types.Type.STRING)},
                        required=["query"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="retrieve_from_brief",
                    description="Look up the current Monday brief: its opportunities, next-best-actions, risk flags, and weekend changes.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"topic": types.Schema(type=types.Type.STRING)},
                        required=["topic"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="lookup_client_holdings",
                    description="Return the Bergstrom client's holdings, allocations, and IPS limits.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={},
                    ),
                ),
                types.FunctionDeclaration(
                    name="web_grounding",
                    description="Search the web for recent news/data when the corpus and brief are insufficient.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={"query": types.Schema(type=types.Type.STRING)},
                        required=["query"],
                    ),
                ),
            ])
        ]

        cfg = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tool_declarations,
        )
        resp = genai_client.models.generate_content(
            model=settings.gemini_model_flash,
            contents=contents,
            config=cfg,
        )

        # Check for text response (done)
        if resp.text:
            return resp.text

        # Inspect parts for function calls
        parts = []
        try:
            parts = resp.candidates[0].content.parts or []
        except (IndexError, AttributeError):
            break

        fn_calls = [p for p in parts if hasattr(p, "function_call") and p.function_call]
        if not fn_calls:
            # No function calls and no text — stop
            break

        # Append the model turn
        contents.append(resp.candidates[0].content)

        # Execute each function call and append responses
        fn_response_parts = []
        for part in fn_calls:
            fc = part.function_call
            fn_name = fc.name
            fn_args = dict(fc.args) if fc.args else {}

            logger.info("manual_react: calling tool %r with args %s", fn_name, fn_args)
            tool_fn = tool_map.get(fn_name)
            if tool_fn is None:
                result_text = f"(unknown tool: {fn_name!r})"
            else:
                try:
                    result_text = tool_fn(**fn_args)
                except Exception as exc:  # noqa: BLE001
                    result_text = f"(tool error: {exc})"

            fn_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fn_name,
                        response={"result": result_text},
                    )
                )
            )

        contents.append(types.Content(parts=fn_response_parts, role="user"))

    # Final call: ask for text answer with tool results in context
    try:
        final_cfg = types.GenerateContentConfig(system_instruction=system_instruction)
        final_resp = genai_client.models.generate_content(
            model=settings.gemini_model_flash,
            contents=contents,
            config=final_cfg,
        )
        return final_resp.text or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("manual_react: final text call failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Ref deduplication
# ---------------------------------------------------------------------------

def _dedup_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """Deduplicate EvidenceRef by (doc_id, chunk_id, source_uri), preserving order."""
    seen: set[tuple[str, str | None, str | None]] = set()
    result: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.doc_id, ref.chunk_id, ref.source_uri)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


# ---------------------------------------------------------------------------
# Async entry point
# ---------------------------------------------------------------------------

async def run(req: ChatRequest) -> ChatResponse:
    """Async entry point — runs _run_sync in a threadpool to avoid blocking the event loop."""
    from app import agent_monitor

    q = (req.question or "")[:70]
    agent_monitor.record_start("chat", f'answering: "{q}…"')
    try:
        resp = await asyncio.to_thread(_run_sync, req)
        agent_monitor.record_done(
            "chat", f'answered ({len(resp.cited_refs)} citations, {resp.confidence})'
        )
        return resp
    except Exception as e:
        agent_monitor.record_error("chat", str(e))
        raise
