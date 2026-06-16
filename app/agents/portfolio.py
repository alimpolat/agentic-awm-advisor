"""Stage 3d — Portfolio Analytics specialist.

Receives sub-questions from the Planner and returns a PortfolioFinding.

Design decisions
----------------
* **Numbers computed in Python, not by the LLM.**  Computing drift, IPS
  compliance, and YTD return deterministically in Python avoids the known
  conflict between Gemini's code_execution tool and a response_schema
  structured-output request.  The model is only asked to produce the
  interpretive `opportunities` list, grounded in retrieved a Nordic private bank/ESG docs.
* The async interface uses asyncio.to_thread so the orchestrator can gather
  all Stage-3 specialists in parallel without blocking the event loop.
* Fund/ETF/Trust positions are exempted from the single-position check via a
  simple substring heuristic on the holding name (case-sensitive: "ETF",
  "Fund", "Trust").
* Retrieval runs for a mix of planner sub-questions and fixed opportunity
  queries to ensure at least some grounding chunks are present even if the
  planner questions are narrow.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.agents._base import run_agent_sync
from app.fixtures import load_portfolio
from app.retrieval.chunker import Chunk
from app.retrieval.hybrid import retrieve
from app.schemas import PortfolioFinding

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_TOP_K_PER_QUESTION = 5
_MAX_TOTAL_CHUNKS = 8
_CHUNK_TEXT_MAX_CHARS = 500
# No artificial cap on parallel retrieve calls — the ThreadPoolExecutor runs all
# queries concurrently so wall-clock cost is O(single retrieval latency).  Brief
# generation runs in the background (cache-first serving), so latency is not on
# the user's critical path — fidelity and recall are the priority.

# Fund/ETF/Trust name fragments that exempt a holding from the single-name rule
_FUND_KEYWORDS = ("ETF", "Fund", "Trust")

_OPPORTUNITY_SEED_QUERIES = [
    "a Nordic private bank green bond fund offerings EU fixed income",
    "ESG fixed income sustainable bonds Nordic investor",
]

_DEFAULT_SUB_QUESTIONS: list[str] = [
    "What is the portfolio drift relative to IPS targets?",
    "Are there any IPS compliance breaches in the Bergström portfolio?",
    "What are the YTD performance numbers for the Bergström portfolio?",
]


# ---------------------------------------------------------------------------
# Public async interface
# ---------------------------------------------------------------------------


async def run(sub_questions: list[str]) -> PortfolioFinding:
    """Async entry point — wraps the blocking pipeline in a thread pool."""
    return await asyncio.to_thread(_run_sync, sub_questions)


# ---------------------------------------------------------------------------
# Synchronous implementation
# ---------------------------------------------------------------------------


def _run_sync(sub_questions: list[str]) -> PortfolioFinding:
    questions = sub_questions if sub_questions else _DEFAULT_SUB_QUESTIONS[:]

    # 1. Load portfolio fixture
    pf: dict[str, Any] = load_portfolio("bergstrom")
    aum: float = pf["aum_sek"]
    target: dict[str, float] = pf["target_allocation"]
    current: dict[str, float] = pf["current_allocation"]
    holdings: list[dict] = pf["holdings"]
    single_pos_limit: float = pf.get("single_position_limit_pct", 5.0)
    fx_floor: float = pf.get("fx_floor_pct", 60.0)

    # 2a. Compute drift_signals
    drift_signals = _compute_drift(target, current)

    # 2b. Compute IPS compliance
    ips_compliance = _compute_ips_compliance(holdings, aum, single_pos_limit, fx_floor)

    # 2c. Compute YTD summary
    ytd_summary = _compute_ytd_summary(holdings)

    # 2d. Build computation trace
    computation_trace = _build_trace(
        target, current, aum, holdings, single_pos_limit, fx_floor, ytd_summary
    )

    # 3. Retrieve grounding chunks for opportunities
    all_chunks = _retrieve_grounding(questions)

    # 4. LLM call — model produces only `opportunities`
    contents = _build_contents(
        questions, drift_signals, ips_compliance, ytd_summary, all_chunks
    )

    # We ask the model for a PortfolioFinding but use only `opportunities`
    try:
        llm_result: PortfolioFinding = run_agent_sync("portfolio", contents, PortfolioFinding)
        opportunities = llm_result.opportunities if llm_result.opportunities else []
    except Exception:
        opportunities = []

    # Fallback: if model returns no opportunities, generate a minimal computed one
    if not opportunities:
        opportunities = _fallback_opportunities(drift_signals, ips_compliance)

    # 5. Assemble final result with Python-computed numbers + model's opportunities
    return PortfolioFinding(
        drift_signals=drift_signals,
        ips_compliance=ips_compliance,
        ytd_summary=ytd_summary,
        opportunities=opportunities,
        computation_trace=computation_trace,
    )


# ---------------------------------------------------------------------------
# Python computation helpers
# ---------------------------------------------------------------------------


def _compute_drift(
    target: dict[str, float],
    current: dict[str, float],
) -> list[dict]:
    """Compute drift (pp) for every asset class in the union of target + current."""
    results = []
    for ac in sorted(set(target) | set(current)):
        cur_pct = round(current.get(ac, 0.0) * 100, 4)
        tgt_pct = round(target.get(ac, 0.0) * 100, 4)
        drift_pp = round(cur_pct - tgt_pct, 2)
        results.append(
            {
                "asset_class": ac,
                "current_pct": cur_pct,
                "target_pct": tgt_pct,
                "drift_pp": drift_pp,
            }
        )
    return results


def _is_fund(name: str) -> bool:
    """Return True if the holding name suggests it is a pooled vehicle (ETF/Fund/Trust)."""
    return any(kw in name for kw in _FUND_KEYWORDS)


def _compute_ips_compliance(
    holdings: list[dict],
    aum: float,
    single_pos_limit: float,
    fx_floor: float,
) -> list[dict]:
    """Compute IPS compliance checks; return a list of dicts."""
    results: list[dict] = []

    # Single-position rule
    breaches: list[dict] = []
    for h in holdings:
        if _is_fund(h["name"]):
            continue  # exempt
        weight_pct = round(h["current_mv"] / aum * 100, 2)
        if weight_pct > single_pos_limit:
            breaches.append(
                {
                    "rule": "single_position_limit",
                    "holding": h["name"],
                    "ticker": h["ticker"],
                    "weight_pct": weight_pct,
                    "limit_pct": single_pos_limit,
                    "status": "breach",
                }
            )

    if breaches:
        results.extend(breaches)
    else:
        results.append(
            {
                "rule": "single_position_limit",
                "status": "pass",
                "detail": "No single-name holding exceeds the position limit.",
            }
        )

    # FX floor rule
    sek_mv = sum(h["current_mv"] for h in holdings if h["fx_exposure"] == "SEK")
    sek_pct = round(sek_mv / aum * 100, 2)
    results.append(
        {
            "rule": "fx_floor_sek",
            "sek_pct": sek_pct,
            "floor_pct": fx_floor,
            "status": "breach" if sek_pct < fx_floor else "pass",
        }
    )

    return results


def _compute_ytd_summary(holdings: list[dict]) -> dict:
    """Compute weighted YTD return, total MV, and total dividends."""
    total_mv = sum(h["current_mv"] for h in holdings)
    weighted_ytd = (
        round(sum(h["current_mv"] * h["ytd_return_pct"] for h in holdings) / total_mv, 2)
        if total_mv > 0
        else 0.0
    )
    total_dividend = sum(h["dividend_ytd"] for h in holdings)
    return {
        "weighted_ytd_pct": weighted_ytd,
        "total_mv_sek": total_mv,
        "total_dividend_ytd_sek": total_dividend,
    }


def _build_trace(
    target: dict,
    current: dict,
    aum: float,
    holdings: list[dict],
    single_pos_limit: float,
    fx_floor: float,
    ytd_summary: dict,
) -> str:
    """Produce a concise audit-trail string for the computation_trace field."""
    sek_mv = sum(h["current_mv"] for h in holdings if h["fx_exposure"] == "SEK")
    sek_pct = round(sek_mv / aum * 100, 2)
    fx_status = "BREACH" if sek_pct < fx_floor else "PASS"

    # Single-position breaches (non-fund)
    sp_breaches = [
        f"{h['name']} ({round(h['current_mv']/aum*100, 2):.2f}%)"
        for h in holdings
        if not _is_fund(h["name"]) and h["current_mv"] / aum * 100 > single_pos_limit
    ]

    lines = [
        "COMPUTATION TRACE",
        "─────────────────",
        "Drift = current_alloc − target_alloc (pp); iterates union of all asset classes.",
        "",
        "Drift results:",
    ]
    for ac in sorted(set(target) | set(current)):
        cur = current.get(ac, 0.0) * 100
        tgt = target.get(ac, 0.0) * 100
        lines.append(f"  {ac}: {cur:.1f}% − {tgt:.1f}% = {round(cur-tgt, 2):+.2f}pp")

    lines += [
        "",
        f"Weighted YTD = Σ(mv × ytd_pct) / Σmv = {ytd_summary['weighted_ytd_pct']}%",
        f"Total MV = SEK {ytd_summary['total_mv_sek']:,}",
        f"Total dividends YTD = SEK {ytd_summary['total_dividend_ytd_sek']:,}",
        "",
        f"SEK base share = Σ(mv where fx_exposure='SEK') / AUM",
        f"  = SEK {sek_mv:,} / SEK {aum:,} = {sek_pct:.2f}%  "
        f"(floor={fx_floor:.0f}% → {fx_status})",
        "",
        f"Single-name positions > {single_pos_limit:.0f}% AUM (funds/ETFs/Trusts exempt):",
    ]
    if sp_breaches:
        for b in sp_breaches:
            lines.append(f"  BREACH: {b}")
    else:
        lines.append("  None.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def _retrieve_grounding(questions: list[str]) -> list[Chunk]:
    """Retrieve chunks from the corpus to ground the LLM's opportunities.

    Uses a ThreadPoolExecutor to run all per-query retrieve() calls concurrently.
    This reduces wall-clock time from O(N × retrieval_latency) to O(retrieval_latency).
    Retrieves for all planner sub-questions + opportunity-seed queries with the full
    reranker pipeline (design-spec default).
    """
    # Combine planner questions with fixed opportunity-seed queries (no cap).
    all_queries = list(questions) + _OPPORTUNITY_SEED_QUERIES

    # Run all retrieve calls in parallel with the full reranker pipeline.
    # The listwise Flash reranker is the design-spec default; it improves
    # relevance quality of grounding chunks for the opportunities prompt.
    per_query_results: dict[int, list[Chunk]] = {}
    with ThreadPoolExecutor(max_workers=len(all_queries)) as pool:
        futures = {
            pool.submit(retrieve, q, _TOP_K_PER_QUESTION): i
            for i, q in enumerate(all_queries)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                per_query_results[idx] = future.result()
            except Exception:
                per_query_results[idx] = []

    # Merge in original query order, dedupe, cap
    seen_chunk_ids: set[str] = set()
    merged: list[Chunk] = []
    for i in sorted(per_query_results):
        for chunk in per_query_results[i]:
            if chunk.chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(chunk.chunk_id)
                merged.append(chunk)
            if len(merged) >= _MAX_TOTAL_CHUNKS:
                return merged

    return merged


# ---------------------------------------------------------------------------
# LLM input construction
# ---------------------------------------------------------------------------


def _build_contents(
    questions: list[str],
    drift_signals: list[dict],
    ips_compliance: list[dict],
    ytd_summary: dict,
    chunks: list[Chunk],
) -> str:
    """Build the user-turn string for the portfolio LLM call.

    The model sees the pre-computed analytics (Python-derived) and retrieved
    corpus chunks, and is asked only to produce `opportunities`.
    """
    # 1. Planner sub-questions
    q_lines = ["=== PLANNER SUB-QUESTIONS (portfolio specialist) ==="]
    for i, q in enumerate(questions, start=1):
        q_lines.append(f"  [{i}] {q}")

    # 2. Pre-computed analytics
    drift_lines = ["=== COMPUTED DRIFT SIGNALS (Python-derived, authoritative) ==="]
    for d in drift_signals:
        direction = "OVERWEIGHT" if d["drift_pp"] > 0 else ("UNDERWEIGHT" if d["drift_pp"] < 0 else "on-target")
        drift_lines.append(
            f"  {d['asset_class']:<22}  current={d['current_pct']:.1f}%  "
            f"target={d['target_pct']:.1f}%  drift={d['drift_pp']:+.2f}pp  [{direction}]"
        )

    ips_lines = ["=== IPS COMPLIANCE (Python-derived, authoritative) ==="]
    for entry in ips_compliance:
        if entry["rule"] == "fx_floor_sek":
            ips_lines.append(
                f"  FX floor: SEK base share = {entry['sek_pct']:.2f}%  "
                f"(floor={entry['floor_pct']:.0f}%) → {entry['status'].upper()}"
            )
        elif entry.get("status") == "breach":
            ips_lines.append(
                f"  Single-position breach: {entry.get('holding', '?')} "
                f"({entry.get('weight_pct', '?'):.2f}% > {entry.get('limit_pct', 5.0):.0f}%)"
            )
        else:
            ips_lines.append(f"  {entry['rule']}: {entry.get('detail', entry.get('status', ''))}")

    ytd_lines = [
        "=== YTD SUMMARY (Python-derived, authoritative) ===",
        f"  Weighted YTD return: {ytd_summary['weighted_ytd_pct']:.2f}%",
        f"  Total MV (SEK):      {ytd_summary['total_mv_sek']:,}",
        f"  Total dividends YTD: {ytd_summary['total_dividend_ytd_sek']:,}",
    ]

    # 3. Retrieved corpus chunks
    chunk_lines = [
        f"=== RETRIEVED CORPUS CHUNKS FOR GROUNDING ({len(chunks)} chunks) ===",
        "Use the evidence in these chunks to ground your opportunities.",
    ]
    for c in chunks:
        truncated = c.text[:_CHUNK_TEXT_MAX_CHARS]
        if len(c.text) > _CHUNK_TEXT_MAX_CHARS:
            truncated += " [...]"
        chunk_lines.append(
            f"\n  [CHUNK] doc_id={c.doc_id}  chunk_id={c.chunk_id}\n  {truncated}"
        )

    # 4. Task instruction
    task_lines = [
        "=== TASK ===",
        "The drift_signals, ips_compliance, and ytd_summary above are ALREADY COMPUTED "
        "in Python and are authoritative. DO NOT recompute them.",
        "",
        "Your job is to produce ONLY the `opportunities` field: a list of 2–4 concrete, "
        "actionable strings that an advisor can use in a client brief. Each opportunity "
        "should:",
        "  1. Reference a specific drift or IPS finding (use the computed numbers above).",
        "  2. Suggest a concrete rebalancing action (e.g. trim overweight → fund underweight).",
        "  3. Where possible, name a specific a Nordic private bank product or doc from the retrieved chunks.",
        "",
        "For the other fields (drift_signals, ips_compliance, ytd_summary, computation_trace) "
        "you MUST return empty lists / null — those are filled from the Python computation.",
    ]

    sections = [
        "\n".join(q_lines),
        "\n".join(drift_lines),
        "\n".join(ips_lines),
        "\n".join(ytd_lines),
        "\n".join(chunk_lines),
        "\n".join(task_lines),
    ]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Fallback opportunities (pure Python, no LLM)
# ---------------------------------------------------------------------------


def _fallback_opportunities(
    drift_signals: list[dict],
    ips_compliance: list[dict],
) -> list[str]:
    """Generate minimal opportunities from the computed signals if the LLM fails."""
    opps: list[str] = []

    for d in drift_signals:
        if d["drift_pp"] > 1.0:
            opps.append(
                f"Trim {d['asset_class']} overweight "
                f"({d['current_pct']:.1f}% vs {d['target_pct']:.1f}% target, "
                f"{d['drift_pp']:+.1f}pp drift) to fund underweight sleeves."
            )
        elif d["drift_pp"] < -1.0:
            opps.append(
                f"Add to {d['asset_class']} underweight "
                f"({d['current_pct']:.1f}% vs {d['target_pct']:.1f}% target, "
                f"{d['drift_pp']:+.1f}pp drift)."
            )

    for entry in ips_compliance:
        if entry.get("rule") == "fx_floor_sek" and entry.get("status") == "breach":
            opps.append(
                f"SEK base share ({entry['sek_pct']:.1f}%) is below the {entry['floor_pct']:.0f}% "
                "FX floor — consider adding SEK-denominated instruments."
            )

    return opps if opps else ["No actionable opportunities identified from current data."]
