"""FastAPI entrypoint. Serves the built React frontend (when present) and the API.

Route ordering: ALL explicit API routes MUST be declared before app.mount("/", ...)
because the StaticFiles catch-all would otherwise shadow them.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.schemas import BriefSchema, ChatRequest, ChatResponse, ClientSnapshot, HitlRequest
from app.orchestrator import (
    generate_brief,
    save_brief_cache,
    BRIEF_CACHE_PATH,
    _snapshot_cache_path_for,
)
from app.agents import chat
from app.fixtures import save_meeting_note

logger = logging.getLogger(__name__)

app = FastAPI(title="Agentic AWM Advisor")

# ---------------------------------------------------------------------------
# In-memory HITL log (per design §13 "logged in-memory for POC")
# ---------------------------------------------------------------------------
HITL_LOG: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cache_path_for(client_id: str) -> Path:
    """Return the cache file path for a given client_id.

    For 'bergstrom' this matches BRIEF_CACHE_PATH exactly.
    For other clients it follows the same naming convention.
    """
    if client_id == "bergstrom":
        return BRIEF_CACHE_PATH
    return BRIEF_CACHE_PATH.parent / f"brief_cache_{client_id}.json"


async def _mark_to_market(client_id: str) -> None:
    """Re-mark the portfolio to live market prices before a pipeline run.

    Runs scripts/mark_to_market.py as a subprocess (it talks to Yahoo/FX feeds
    and rewrites data/{client_id}_portfolio.json).  Fail-open by design: if the
    feeds are unreachable or the script errors, the pipeline proceeds on the
    last-written valuations — stale-but-real beats no brief.
    """
    if client_id != "bergstrom":
        return  # only the bergstrom book has live-tickered holdings
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "mark_to_market.py"
    try:
        import sys

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script),
            cwd=str(repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
        if proc.returncode == 0:
            logger.info("mark-to-market refreshed before pipeline run")
        else:
            logger.warning(
                "mark-to-market exited %s — using last valuations.\n%s",
                proc.returncode, out.decode(errors="replace")[-500:],
            )
    except Exception:
        logger.exception("mark-to-market failed — using last valuations")


async def _regen_async(client_id: str) -> None:
    """Fire-and-forget coroutine: regenerate the brief and write it to disk.

    Launched via asyncio.create_task so it survives even when the calling
    handler raises an HTTPException (Starlette BackgroundTasks are discarded
    on exception; asyncio tasks are not).  Failures are logged and swallowed
    so they never crash the server.
    """
    try:
        # Fresh valuations first so every agent reasons over today's book.
        await _mark_to_market(client_id)
        brief = await generate_brief(client_id, datetime.now(timezone.utc))
        save_brief_cache(brief, _cache_path_for(client_id))
        logger.info("Background regen complete for %s", client_id)
    except Exception:
        logger.exception("background brief regeneration failed for %s", client_id)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------------------------------------------------------------------------
# Brief (cache-first)
# ---------------------------------------------------------------------------


@app.get("/api/brief/{client_id}", response_model=BriefSchema)
async def get_brief(client_id: str, refresh: bool = False):
    """Return the pre-generated brief from cache (instant, zero network).

    Plain GET: serves the committed cache immediately — no LLM call, no
    network activity.  If the cache is missing, returns 503.

    ?refresh=true: fires a best-effort background regeneration on the event
    loop via asyncio.create_task (survives even when this handler later
    raises).  The task runs the full ~2-minute pipeline off the request path.
    - If a cache already exists, it is served immediately (200) while regen
      runs in the background.
    - If no cache exists yet, returns 202 telling the caller to retry shortly
      once the background task has completed.
    """
    cache_path = _cache_path_for(client_id)

    # Fire background regen on the event loop BEFORE any potential raise.
    # asyncio.create_task survives a subsequent HTTPException; Starlette
    # BackgroundTasks (the previous implementation) do not.
    if refresh:
        asyncio.create_task(_regen_async(client_id))

    if cache_path.exists():
        return BriefSchema.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )

    if refresh:
        # Regen was just kicked off; tell the caller to retry shortly.
        raise HTTPException(
            status_code=202,
            detail=(
                f"Brief for '{client_id}' is being generated; retry shortly."
            ),
        )

    # No cache and no refresh requested
    raise HTTPException(
        status_code=503,
        detail=(
            f"Brief for '{client_id}' not generated yet. "
            "Run `python -m app.orchestrator` to build the cache "
            "or call with ?refresh=true and retry shortly."
        ),
    )


# ---------------------------------------------------------------------------
# Client snapshot (cache-first)
# ---------------------------------------------------------------------------


@app.get("/api/client/{client_id}", response_model=ClientSnapshot)
async def get_client(client_id: str):
    """Return the pre-generated ClientSnapshot from cache (instant, zero network).

    Serves client name, AUM, holdings, and target allocations for the
    frontend cockpit (ClientHeader, AllocationDonut, holdings table).
    Cache is written by the orchestrator as a side-effect of Stage 2.
    """
    path = _snapshot_cache_path_for(client_id)
    if path.exists():
        return ClientSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    raise HTTPException(
        status_code=503,
        detail=(
            f"Client snapshot for '{client_id}' not generated yet. "
            "Run `python -m app.orchestrator` to build the cache."
        ),
    )


# ---------------------------------------------------------------------------
# Per-holding price trends (real, live) — feeds the holdings-table sparklines
# ---------------------------------------------------------------------------

# Some holdings carry a portfolio code that is not the tradable Yahoo symbol.
_TICKER_OVERRIDES: dict[str, str] = {
    "IEAC": "IEAC.AS",  # iShares EUR Corp Bond UCITS — Amsterdam listing
}
# Codes with no equity price series (bond yields, illiquid private funds, or
# venues Yahoo doesn't cover): served as source="unavailable" → FE draws an
# indicative line, honestly labelled.
_NO_MARKET_PRICE = {"DE10Y-BUND", "FR10Y-OAT", "REIT.DI", "NORD-PE-VII", "GLOB-INFRA"}

_TRENDS_CACHE: dict[str, tuple[float, dict]] = {}  # client_id -> (monotonic_ts, payload)
_TRENDS_TTL_S = 900  # 15 min


@app.get("/api/trends/{client_id}")
async def get_trends(client_id: str):
    """Real 30-day daily-close trend per holding (free Yahoo feed), cached 15 min.

    Returns {ticker: {"closes": [...], "source": "live"|"unavailable"}}. Liquid
    positions get real price history; bonds and illiquid funds report
    "unavailable" so the frontend can mark them honestly.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app.intel.live_market import price_history

    cached = _TRENDS_CACHE.get(client_id)
    if cached and (time.monotonic() - cached[0]) < _TRENDS_TTL_S:
        return cached[1]

    portfolio_path = BRIEF_CACHE_PATH.parent / f"{client_id}_portfolio.json"
    if not portfolio_path.exists():
        raise HTTPException(status_code=404, detail=f"No portfolio for '{client_id}'.")
    import json

    holdings = json.loads(portfolio_path.read_text(encoding="utf-8")).get("holdings", [])
    tickers = [h["ticker"] for h in holdings if h.get("ticker")]

    def fetch(ticker: str) -> tuple[str, dict]:
        if ticker in _NO_MARKET_PRICE:
            return ticker, {"closes": [], "source": "unavailable"}
        series = price_history(_TICKER_OVERRIDES.get(ticker, ticker))
        if series:
            return ticker, {"closes": series, "source": "live"}
        return ticker, {"closes": [], "source": "unavailable"}

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = await asyncio.gather(
            *[loop.run_in_executor(pool, fetch, t) for t in tickers]
        )
    payload = {t: data for t, data in results}
    _TRENDS_CACHE[client_id] = (time.monotonic(), payload)
    live_n = sum(1 for d in payload.values() if d["source"] == "live")
    logger.info("trends/%s: %d live, %d unavailable", client_id, live_n, len(payload) - live_n)
    return payload


# ---------------------------------------------------------------------------
# Agent Ops — live fleet status for the cockpit's monitor panel
# ---------------------------------------------------------------------------


@app.get("/api/agents")
async def get_agents():
    """Live status of every agent in the fleet (idle/running/done/error +
    current activity + last duration). Polled by the AgentMonitor panel;
    instrumented at the single run_agent_sync seam, so all stage agents and
    the chat agent report automatically."""
    from app import agent_monitor

    return agent_monitor.snapshot()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@app.post("/api/chat", response_model=ChatResponse)
async def post_chat(req: ChatRequest):
    """Answer a question about the client's brief / portfolio using hybrid retrieval."""
    return await chat.run(req)


# ---------------------------------------------------------------------------
# HITL
# ---------------------------------------------------------------------------


@app.post("/api/hitl/{action}")
async def post_hitl(
    action: Literal["approve", "edit", "regenerate", "reject"],
    req: HitlRequest,
):
    """Log a human-in-the-loop action against an NBA recommendation."""
    entry = {
        "action": action,
        "client_id": req.client_id,
        "nba_title": req.nba_title,
        "nba_index": req.nba_index,
        "reason": req.reason,
        "edited_text": req.edited_text,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    HITL_LOG.append(entry)
    return {"ok": True, "action": action, "logged": entry, "log_size": len(HITL_LOG)}


# ---------------------------------------------------------------------------
# After-meeting capture — closes the loop (Stage 5)
# ---------------------------------------------------------------------------


class FollowUpRequest(BaseModel):
    notes: str


@app.post("/api/followup/{client_id}")
async def post_followup(client_id: str, req: FollowUpRequest):
    """Persist advisor meeting notes, then kick off a background brief regen.

    The saved note becomes client context the next time the brief is generated
    (consumed by the Client-Insights agent via fixtures.load_meeting_notes),
    closing the advisor follow-up loop.
    """
    note = (req.notes or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="notes must not be empty")
    path = await asyncio.to_thread(save_meeting_note, client_id, note)
    asyncio.create_task(_regen_async(client_id))
    return {"ok": True, "saved": path.name, "regenerating": True}


# ---------------------------------------------------------------------------
# Static frontend — mounted LAST so it never shadows the API routes above
# ---------------------------------------------------------------------------

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
else:

    @app.get("/")
    def root():
        return HTMLResponse("<h1>Agentic AWM Advisor — frontend not built yet</h1>")
