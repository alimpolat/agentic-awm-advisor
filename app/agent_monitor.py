"""In-memory agent telemetry — powers the cockpit's Agent Ops dashboard.

Every stage agent funnels through ``run_agent_sync`` (app/agents/_base.py), so a
single instrumentation point records start / done / error, **real token usage**
(from Gemini ``usage_metadata``), per-run history, a fleet event feed, and the
waterfall of the last pipeline run. The chat agent instruments its own ``run``.

Process-local and thread-safe — right for a POC; in production these are the
same dimensions shipped as OpenTelemetry spans (app/observability.py) to
Phoenix/Grafana.

GET /api/agents returns the full snapshot the frontend polls.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

# ── Fleet metadata: name -> (emoji, display name, role, stage) ────────────────
FLEET: dict[str, dict[str, str]] = {
    "opportunity_scout": {
        "emoji": "🔭", "name": "Opportunity Scout", "stage": "Stage 1",
        "role": "Scans drift, IPS limits and live market intel for talking points",
    },
    "client_insights": {
        "emoji": "🗂️", "name": "Client Insights", "stage": "Stage 2",
        "role": "Extracts concerns & restrictions from meeting notes and the IPS",
    },
    "planner": {
        "emoji": "🧭", "name": "Planner", "stage": "Stage 3",
        "role": "Decomposes the meeting goal into sub-questions for the specialists",
    },
    "intel_gathering": {
        "emoji": "📡", "name": "Intel Gathering", "stage": "Stage 3 · parallel",
        "role": "Answers intel sub-questions from live signals (oil, rates, FX)",
    },
    "macro": {
        "emoji": "🌍", "name": "Macro Strategist", "stage": "Stage 3 · parallel",
        "role": "Macro backdrop from BIS / ECB / IMF corpus via hybrid retrieval",
    },
    "portfolio": {
        "emoji": "📊", "name": "Portfolio Analyst", "stage": "Stage 3 · parallel",
        "role": "Deterministic drift / FX / concentration math over the real book",
    },
    "news": {
        "emoji": "📰", "name": "News Desk", "stage": "Stage 3 · parallel",
        "role": "Google-grounded weekend news relevant to the family's sleeves",
    },
    "synthesizer": {
        "emoji": "⚗️", "name": "Synthesizer", "stage": "Stage 4",
        "role": "Fuses all findings into the brief: NBAs, risk flags, evidence",
    },
    "chat": {
        "emoji": "💬", "name": "Advisor Q&A", "stage": "On demand",
        "role": "Hybrid-retrieval chat over the brief, book and corpus (AFC + ReAct)",
    },
}

_HISTORY_LEN = 20
_EVENTS_LEN = 80

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {
    key: {
        "status": "idle",            # idle | running | done | error
        "activity": None,
        "started_at": None,
        "finished_at": None,
        "duration_s": None,
        "runs": 0,
        "errors": 0,
        "tokens_in": 0,              # cumulative real prompt tokens
        "tokens_out": 0,             # cumulative real completion tokens
        "last_tokens_in": None,
        "last_tokens_out": None,
        "avg_duration_s": None,
        "history": [],               # last N runs: {duration_s, tokens_in, tokens_out, ok, start_offset_s}
        "last_error": None,
    }
    for key in FLEET
}
_t0: dict[str, float] = {}
_events: deque[dict[str, Any]] = deque(maxlen=_EVENTS_LEN)

# pipeline-run tracking (for the waterfall)
_pipeline_t0: Optional[float] = None
_pipeline_active = False
_pipeline_explicit = False  # True when the orchestrator brackets the run itself
_pipeline_idle_since: Optional[float] = None  # set when fleet goes quiet mid-pipeline
_IDLE_GRACE_S = 5.0  # stage gaps shorter than this don't end an implicit pipeline
_current_run: dict[str, dict[str, Any]] = {}
_last_pipeline: Optional[dict[str, Any]] = None


def pipeline_begin() -> None:
    """Explicit bracket from the orchestrator: a full brief run is starting.

    Retrieval phases between agent LLM calls look 'idle' to the heuristic;
    explicit bracketing makes the waterfall and pipeline_running exact.
    """
    global _pipeline_active, _pipeline_explicit, _pipeline_t0, _pipeline_idle_since
    with _lock:
        _pipeline_active = True
        _pipeline_explicit = True
        _pipeline_t0 = time.monotonic()
        _pipeline_idle_since = None
        _current_run.clear()


def pipeline_end() -> None:
    """Explicit bracket from the orchestrator: the brief run finished."""
    global _pipeline_active, _pipeline_explicit, _pipeline_idle_since, _last_pipeline
    with _lock:
        if not _pipeline_active:
            return
        total = round(time.monotonic() - (_pipeline_t0 or time.monotonic()), 1)
        _pipeline_active = False
        _pipeline_explicit = False
        _pipeline_idle_since = None
        _last_pipeline = {
            "total_s": total,
            "finished_at": _now_iso(),
            "agents": [
                {"key": k, "emoji": FLEET[k]["emoji"], "name": FLEET[k]["name"],
                 "start_offset_s": v.get("start_offset_s", 0),
                 "duration_s": v.get("duration_s", 0), "ok": v.get("ok", True)}
                for k, v in _current_run.items() if "duration_s" in v
            ],
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(agent: str, event: str, detail: str) -> None:
    meta = FLEET.get(agent, {})
    _events.appendleft({
        "ts": _now_iso(),
        "agent": agent,
        "emoji": meta.get("emoji", "·"),
        "name": meta.get("name", agent),
        "event": event,                 # start | done | error
        "detail": detail[:160],
    })


def record_start(agent: str, activity: str = "") -> None:
    global _pipeline_t0, _pipeline_active, _pipeline_idle_since
    if agent not in _state:
        return
    with _lock:
        if not _pipeline_active:
            _pipeline_active = True
            _pipeline_t0 = time.monotonic()
            _current_run.clear()
        _pipeline_idle_since = None  # work resumed — any stage gap is over
        s = _state[agent]
        s["status"] = "running"
        s["activity"] = activity or "working…"
        s["started_at"] = _now_iso()
        s["finished_at"] = None
        s["last_error"] = None
        _t0[agent] = time.monotonic()
        _current_run[agent] = {
            "start_offset_s": round(time.monotonic() - (_pipeline_t0 or time.monotonic()), 1),
        }
        _emit(agent, "start", activity)


def _finish(agent: str, ok: bool, summary: str, tokens_in: int, tokens_out: int) -> None:
    """Shared completion path under the lock."""
    global _pipeline_active, _last_pipeline
    s = _state[agent]
    dur = round(time.monotonic() - _t0.get(agent, time.monotonic()), 1)
    s["status"] = "done" if ok else "error"
    if summary:
        s["activity" if ok else "last_error"] = summary
        if not ok:
            s["activity"] = None
    s["finished_at"] = _now_iso()
    s["duration_s"] = dur
    s["runs"] += 1
    if not ok:
        s["errors"] += 1
    if tokens_in:
        s["tokens_in"] += tokens_in
        s["last_tokens_in"] = tokens_in
    if tokens_out:
        s["tokens_out"] += tokens_out
        s["last_tokens_out"] = tokens_out

    entry = {
        "duration_s": dur, "tokens_in": tokens_in, "tokens_out": tokens_out,
        "ok": ok, "start_offset_s": _current_run.get(agent, {}).get("start_offset_s", 0),
    }
    s["history"] = (s["history"] + [entry])[-_HISTORY_LEN:]
    durs = [h["duration_s"] for h in s["history"]]
    s["avg_duration_s"] = round(sum(durs) / len(durs), 1)
    if agent in _current_run:
        _current_run[agent]["duration_s"] = dur
        _current_run[agent]["ok"] = ok

    _emit(agent, "done" if ok else "error",
          summary if ok else (summary or "failed"))

    # fleet went quiet — start the grace clock; snapshot() finalizes the
    # pipeline only if the quiet persists (stage gaps are shorter than grace)
    global _pipeline_idle_since
    if _pipeline_active and not any(x["status"] == "running" for x in _state.values()):
        _pipeline_idle_since = time.monotonic()


def _maybe_finalize_pipeline() -> None:
    """Called under the lock from snapshot(): end an IMPLICIT pipeline (e.g. a
    chat-only run) after a real quiet period. Explicit runs end via pipeline_end()."""
    global _pipeline_active, _pipeline_idle_since, _last_pipeline
    if _pipeline_explicit:
        return
    if not _pipeline_active or _pipeline_idle_since is None:
        return
    if any(x["status"] == "running" for x in _state.values()):
        return
    if time.monotonic() - _pipeline_idle_since < _IDLE_GRACE_S:
        return
    _pipeline_active = False
    total = round(_pipeline_idle_since - (_pipeline_t0 or _pipeline_idle_since), 1)
    _pipeline_idle_since = None
    _last_pipeline = {
        "total_s": total,
        "finished_at": _now_iso(),
        "agents": [
            {"key": k, "emoji": FLEET[k]["emoji"], "name": FLEET[k]["name"],
             "start_offset_s": v.get("start_offset_s", 0),
             "duration_s": v.get("duration_s", 0), "ok": v.get("ok", True)}
            for k, v in _current_run.items() if "duration_s" in v
        ],
    }


def record_done(agent: str, summary: str = "", tokens_in: int = 0, tokens_out: int = 0) -> None:
    if agent not in _state:
        return
    with _lock:
        _finish(agent, True, summary, tokens_in, tokens_out)


def record_error(agent: str, error: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
    if agent not in _state:
        return
    with _lock:
        _finish(agent, False, error[:200], tokens_in, tokens_out)


def snapshot() -> dict[str, Any]:
    """Fleet metadata + live state + totals + event feed + last-run waterfall."""
    with _lock:
        _maybe_finalize_pipeline()
        agents = [{"key": key, **FLEET[key], **_state[key]} for key in FLEET]
        events = list(_events)
        last_pipeline = _last_pipeline
        # "running" includes short stage gaps, so the UI doesn't flap idle
        # mid-pipeline and the brief isn't refetched early
        any_running = any(a["status"] == "running" for a in agents) or _pipeline_active
    totals = {
        "runs": sum(a["runs"] for a in agents),
        "errors": sum(a["errors"] for a in agents),
        "tokens_in": sum(a["tokens_in"] for a in agents),
        "tokens_out": sum(a["tokens_out"] for a in agents),
    }
    durs = [a["avg_duration_s"] for a in agents if a["avg_duration_s"]]
    totals["avg_latency_s"] = round(sum(durs) / len(durs), 1) if durs else None
    return {
        "agents": agents,
        "pipeline_running": any_running,
        "totals": totals,
        "events": events,
        "last_pipeline": last_pipeline,
    }


__all__ = ["record_start", "record_done", "record_error", "snapshot", "FLEET"]
