"""5-stage orchestrator -generates the Monday advisor brief for a client.

Stage topology
--------------
Stage 1 + 2 (parallel)  →  Stage 3a (planner)  →  Stages 3b-e (parallel)  →  Stage 4

Public surface
--------------
    generate_brief(client_id, meeting_datetime) -> BriefSchema
    save_brief_cache(brief, path=BRIEF_CACHE_PATH) -> None

CLI entry-point
---------------
    uv run python -m app.orchestrator
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Agent imports -module names collide with common local var names, so alias
# ---------------------------------------------------------------------------
from app.agents import (
    opportunity_scout,
    client_insights,
    planner,
    intel_gathering,
    synthesizer,
)
from app.agents import macro as macro_agent
from app.agents import portfolio as portfolio_agent
from app.agents import news as news_agent

from app.schemas import BriefSchema, ClientSnapshot

# ---------------------------------------------------------------------------
# Cache paths
# ---------------------------------------------------------------------------

BRIEF_CACHE_PATH: Path = Path(__file__).parent.parent / "data" / "brief_cache_bergstrom.json"
CLIENT_SNAPSHOT_CACHE_PATH: Path = Path(__file__).parent.parent / "data" / "client_snapshot_bergstrom.json"


def _snapshot_cache_path_for(client_id: str) -> Path:
    """Return the snapshot cache file path for a given client_id.

    For 'bergstrom' this matches CLIENT_SNAPSHOT_CACHE_PATH exactly.
    For other clients it follows the same naming convention.
    """
    if client_id == "bergstrom":
        return CLIENT_SNAPSHOT_CACHE_PATH
    return CLIENT_SNAPSHOT_CACHE_PATH.parent / f"client_snapshot_{client_id}.json"


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


async def generate_brief(
    client_id: str,
    meeting_datetime: datetime,
) -> BriefSchema:
    """Run the full 5-stage pipeline and return a validated BriefSchema.

    Stages 1 and 2 are independent and run in parallel via asyncio.gather.
    Stage 3a (planner) depends on both; the four Stage-3 specialists (3b-e)
    depend on the planner output and run in parallel; Stage 4 (synthesizer)
    depends on all prior stages.
    """
    from app import agent_monitor

    agent_monitor.pipeline_begin()
    try:
        return await _generate_brief_inner(client_id, meeting_datetime)
    finally:
        agent_monitor.pipeline_end()


async def _generate_brief_inner(
    client_id: str,
    meeting_datetime: datetime,
) -> BriefSchema:
    # -----------------------------------------------------------------------
    # Stages 1 + 2 in parallel
    # -----------------------------------------------------------------------
    opp, snap = await asyncio.gather(
        opportunity_scout.run(client_id),
        client_insights.run(client_id),
    )

    # Persist snapshot as a side-effect so the /api/client endpoint can serve it
    save_snapshot_cache(snap, _snapshot_cache_path_for(client_id))

    # -----------------------------------------------------------------------
    # Stage 3a -planner (sequential, depends on Stage 1 + 2)
    # -----------------------------------------------------------------------
    plan = await planner.run(opp, snap, meeting_datetime)

    # -----------------------------------------------------------------------
    # Stages 3b-e in parallel (depend on planner)
    # The planner invariant guarantees all four keys are present; use .get
    # with [] default as a belt-and-suspenders guard.
    # -----------------------------------------------------------------------
    intel, macro_f, port_f, news_f = await asyncio.gather(
        intel_gathering.run(plan.sub_questions.get("intel", [])),
        macro_agent.run(plan.sub_questions.get("macro", [])),
        portfolio_agent.run(plan.sub_questions.get("portfolio", [])),
        news_agent.run(plan.sub_questions.get("news", [])),
    )

    # -----------------------------------------------------------------------
    # Stage 4 -synthesizer
    # -----------------------------------------------------------------------
    brief = await synthesizer.run(plan, opp, snap, intel, macro_f, port_f, news_f)
    return brief


# ---------------------------------------------------------------------------
# Cache helper
# ---------------------------------------------------------------------------


def save_brief_cache(brief: BriefSchema, path: Path = BRIEF_CACHE_PATH) -> None:
    """Write the BriefSchema to disk as formatted JSON (UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")


def save_snapshot_cache(
    snapshot: ClientSnapshot, path: Path = CLIENT_SNAPSHOT_CACHE_PATH
) -> None:
    """Write the ClientSnapshot to disk as formatted JSON (UTF-8)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entry-point -`uv run python -m app.orchestrator`
# ---------------------------------------------------------------------------


def _print_summary(brief: BriefSchema, elapsed: float) -> None:
    """Print a human-readable brief summary to stdout."""
    print()
    print("=" * 70)
    print("  AWM -- MONDAY BRIEF SUMMARY")
    print("=" * 70)
    print(f"  client_id     : {brief.client_id}")
    print(f"  generated_at  : {brief.generated_at.isoformat()}")
    print(f"  intel_mode    : {brief.intel_mode}")
    print(f"  opportunities : {len(brief.opportunities)} signal(s)")
    print(f"  weekend_changes: {len(brief.weekend_changes)} item(s)")
    print(f"  risk_flags    : {len(brief.risk_flags)} flag(s)")
    for flag in brief.risk_flags:
        print(f"    [{flag.severity.upper()}] {flag.kind} -- {flag.note}")
    print()
    print(f"  THREE NBAs ({len(brief.three_nbas)}):")
    for nba in brief.three_nbas:
        print(f"    [{nba.suggested_priority.upper()}] {nba.title}")
        print(f"      rationale      : {nba.rationale[:120]}{'...' if len(nba.rationale) > 120 else ''}")
        print(f"      projected_impact: {nba.projected_impact[:100]}{'...' if len(nba.projected_impact) > 100 else ''}")
        print(f"      confidence     : {nba.confidence}")
        print(f"      evidence_refs  : {len(nba.evidence_refs)} ref(s) -- "
              f"{[r.doc_id for r in nba.evidence_refs]}")
    print()
    print(f"  elapsed       : {elapsed:.2f}s")
    print(f"  brief generation: {elapsed:.1f}s (background/pre-generated; served from cache — not on the request path)")
    print("=" * 70)
    print()


if __name__ == "__main__":
    import time

    meeting_dt = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)

    print(f"Running 5-stage brief pipeline for 'bergstrom' -- meeting {meeting_dt.isoformat()} ...")
    t0 = time.perf_counter()
    brief = asyncio.run(generate_brief("bergstrom", meeting_dt))
    elapsed = time.perf_counter() - t0

    _print_summary(brief, elapsed)

    save_brief_cache(brief)
    print(f"Brief cache written -> {BRIEF_CACHE_PATH}")
