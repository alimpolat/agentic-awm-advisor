"""In-memory agent activity registry — powers the cockpit's Agent Ops panel.

Every stage agent funnels through ``run_agent_sync`` (app/agents/_base.py), so a
single instrumentation point there records start / done / error for the whole
fleet. The chat agent is instrumented in its own ``run``. The registry is
process-local and thread-safe — exactly right for a POC; in production this
would be OpenTelemetry spans shipped to Phoenix/Grafana (see app/observability.py,
which already produces the span hierarchy).

GET /api/agents returns the snapshot the frontend polls.
"""
from __future__ import annotations

import threading
import time
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

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {
    key: {
        "status": "idle",          # idle | running | done | error
        "activity": None,           # what it's doing right now / did last
        "started_at": None,
        "finished_at": None,
        "duration_s": None,
        "runs": 0,
        "last_error": None,
    }
    for key in FLEET
}
_t0: dict[str, float] = {}


def record_start(agent: str, activity: str = "") -> None:
    if agent not in _state:
        return
    with _lock:
        s = _state[agent]
        s["status"] = "running"
        s["activity"] = activity or "working…"
        s["started_at"] = datetime.now(timezone.utc).isoformat()
        s["finished_at"] = None
        s["last_error"] = None
        _t0[agent] = time.monotonic()


def record_done(agent: str, summary: str = "") -> None:
    if agent not in _state:
        return
    with _lock:
        s = _state[agent]
        s["status"] = "done"
        if summary:
            s["activity"] = summary
        s["finished_at"] = datetime.now(timezone.utc).isoformat()
        s["duration_s"] = round(time.monotonic() - _t0.get(agent, time.monotonic()), 1)
        s["runs"] += 1


def record_error(agent: str, error: str) -> None:
    if agent not in _state:
        return
    with _lock:
        s = _state[agent]
        s["status"] = "error"
        s["last_error"] = error[:200]
        s["finished_at"] = datetime.now(timezone.utc).isoformat()
        s["duration_s"] = round(time.monotonic() - _t0.get(agent, time.monotonic()), 1)
        s["runs"] += 1


def snapshot() -> dict[str, Any]:
    """Fleet metadata merged with live state, in pipeline order."""
    with _lock:
        agents = [
            {"key": key, **FLEET[key], **_state[key]}
            for key in FLEET
        ]
    any_running = any(a["status"] == "running" for a in agents)
    return {"agents": agents, "pipeline_running": any_running}


__all__ = ["record_start", "record_done", "record_error", "snapshot", "FLEET"]
