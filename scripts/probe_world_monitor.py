"""Day-1 discovery: which World_Monitor (finance variant) endpoints are reachable
from a server-side client without API keys?

World_Monitor is a Vercel serverless intel aggregator. Its finance variant exposes
market endpoints — some keyless (stock-index, yahoo-finance, polymarket, risk-scores),
some key-gated (fred-data, macro-signals, eia). This probe records reachability +
response shape so the intel client (Task 1.4) knows what to fetch live vs. snapshot.

Run from repo root:  uv run python scripts/probe_world_monitor.py
Writes:              data/world_monitor_endpoints_discovered.json
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.settings import settings  # noqa: E402

BASE = settings.world_monitor_base.rstrip("/")
TIMEOUT = settings.world_monitor_timeout_s

# (label, path, needs_key) — curated from World_Monitor API_REFERENCE.md
PROBES = [
    ("version", "/api/version", False),
    ("stock_index", "/api/stock-index?symbols=^OMX,^GSPC,^GDAXI", False),
    ("yahoo_finance", "/api/yahoo-finance?symbol=^OMX", False),
    ("polymarket", "/api/polymarket?limit=10&active=true", False),
    ("risk_scores", "/api/risk-scores", False),
    ("coingecko", "/api/coingecko", False),
    ("macro_signals", "/api/macro-signals", True),   # partial without keys
    ("fred_data", "/api/fred-data?series_id=DGS10", True),  # needs FRED_API_KEY
    ("story_se", "/api/story?country=SE", False),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (agentic-awm-advisor probe)",
    "Origin": BASE,
    "Accept": "application/json, */*",
}


def _shape(body: str):
    try:
        data = json.loads(body)
    except Exception:
        return {"json": False, "preview": body[:160]}
    if isinstance(data, list):
        return {"json": True, "type": "array", "len": len(data),
                "item_keys": sorted(data[0].keys())[:12] if data and isinstance(data[0], dict) else None}
    if isinstance(data, dict):
        return {"json": True, "type": "object", "top_keys": sorted(data.keys())[:12]}
    return {"json": True, "type": type(data).__name__}


def main() -> int:
    print(f"Probing {BASE} (timeout {TIMEOUT}s each)\n")
    results = []
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS) as c:
        for label, path, needs_key in PROBES:
            url = f"{BASE}{path}"
            rec = {"label": label, "path": path, "needs_key": needs_key}
            t0 = time.perf_counter()
            try:
                r = c.get(url)
                rec["status"] = r.status_code
                rec["ms"] = round((time.perf_counter() - t0) * 1000)
                rec["shape"] = _shape(r.text)
                # "live usable" = 200, JSON, and actually carries data (not an error/unavailable stub)
                shape = rec["shape"]
                usable = (
                    r.status_code == 200
                    and shape.get("json")
                    and (shape.get("len", 1) != 0)
                    and "error" not in shape.get("top_keys", [])
                )
                rec["live_usable"] = bool(usable)
            except Exception as e:  # noqa: BLE001
                rec["status"] = None
                rec["ms"] = round((time.perf_counter() - t0) * 1000)
                rec["error"] = f"{type(e).__name__}: {e}"
                rec["live_usable"] = False
            flag = "OK " if rec["live_usable"] else "-- "
            print(f"{flag}{label:14} {str(rec.get('status')):>4}  {rec['ms']:>5}ms  {rec.get('shape') or rec.get('error')}")
            results.append(rec)

    out = Path(__file__).resolve().parents[1] / "data" / "world_monitor_endpoints_discovered.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"base": BASE, "probed_at": time.time(), "results": results}, indent=2))
    usable = [r["label"] for r in results if r["live_usable"]]
    print(f"\nLive-usable (keyless): {len(usable)}/{len(PROBES)} -> {usable}")
    print(f"catalog: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
