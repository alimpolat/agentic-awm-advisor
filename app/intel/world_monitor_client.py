"""World_Monitor intel client with snapshot fallback.

Discovery (2026-05-26): the public World_Monitor finance endpoints are API-key gated
(401) or not deployed on the web tier (404) — only `/api/version` is openly reachable.
So the POC runs **snapshot-first**: structured signals come from the frozen snapshot,
each tagged `live_or_snapshot="snapshot"`. `LIVE_ROUTES` is intentionally empty; in
production, mapping a signal to a reachable World_Monitor route (with the platform's
API key in `WORLD_MONITOR_API_KEY`) makes that signal live with zero other changes.
"""
from datetime import datetime

import httpx

from app.intel import live_market
from app.intel.snapshot_loader import SNAPSHOT, SNAPSHOT_AS_OF
from app.schemas import IntelFinding, IntelFindings
from app.settings import settings

# signal_key -> World_Monitor path. Empty for the POC (no openly-reachable data routes).
LIVE_ROUTES: dict[str, str] = {}

_AS_OF = datetime.fromisoformat(SNAPSHOT_AS_OF.replace("Z", "+00:00"))


def _from_snapshot(key: str, blk: dict) -> IntelFinding:
    return IntelFinding(
        source=blk["source"],
        metric=blk["metric"],
        value=blk["value"],
        as_of=_AS_OF,
        relevance=blk["relevance"],
        live_or_snapshot="snapshot",
    )


def _from_live_market(key: str, blk: dict) -> IntelFinding | None:
    """Real free-feed live value for a signal (Yahoo Finance). None if unsupported/failed."""
    res = live_market.live_value(key)
    if res is None:
        return None
    value, source_label, change_note = res
    return IntelFinding(
        source=source_label,
        metric=blk["metric"],
        value=value,
        as_of=datetime.now().astimezone(),
        relevance=blk["relevance"] + change_note,
        live_or_snapshot="live",
    )


def _try_live(key: str, path: str) -> IntelFinding | None:
    """Attempt a live fetch for one signal. Returns None on any failure (→ caller falls back)."""
    try:
        headers = {"User-Agent": "agentic-awm-advisor", "Origin": settings.world_monitor_base}
        r = httpx.get(
            f"{settings.world_monitor_base}{path}",
            timeout=settings.world_monitor_timeout_s,
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        blk = SNAPSHOT[key]
        return IntelFinding(
            source=blk["source"].replace("snapshot", "live"),
            metric=blk["metric"],
            value=data.get("value", blk["value"]),
            as_of=datetime.now().astimezone(),
            relevance=blk["relevance"],
            live_or_snapshot="live",
        )
    except Exception:  # noqa: BLE001
        return None


def fetch_intel() -> IntelFindings:
    """Return all signals as IntelFindings. Live where reachable, snapshot otherwise."""
    mode = settings.intel_mode
    items: list[IntelFinding] = []
    for key, blk in SNAPSHOT.items():
        finding: IntelFinding | None = None
        if mode in ("auto", "live"):
            # 1) real free market feeds (Yahoo Finance); 2) any World_Monitor route
            finding = _from_live_market(key, blk)
            if finding is None and key in LIVE_ROUTES:
                finding = _try_live(key, LIVE_ROUTES[key])
        if finding is None:
            finding = _from_snapshot(key, blk)
        items.append(finding)
    return IntelFindings(items=items)


def heartbeat() -> bool:
    """Live connectivity check against the one openly-reachable endpoint (/api/version)."""
    try:
        r = httpx.get(
            f"{settings.world_monitor_base}/api/version",
            timeout=settings.world_monitor_timeout_s,
            headers={"User-Agent": "agentic-awm-advisor"},
        )
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False
