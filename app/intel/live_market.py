"""Live market data via free, no-key endpoints (Yahoo Finance chart API).

Maps the World_Monitor snapshot signal keys to real, openly-reachable instruments
so ``INTEL_MODE`` in ("auto", "live") serves genuine current values instead of the
frozen snapshot. Each live finding carries the real intraday level plus a day-over-
day move so the Opportunity-Scout reasons over actual market conditions.

What is live vs snapshot, and why:
  - brent_oil / wti_oil / usd_index_dxy / omxs30  -> LIVE (Yahoo Finance chart API)
  - ecb_deposit_rate / sama_repo_rate             -> snapshot (policy rates change at
       scheduled meetings; no free real-time tick — kept as a dated reference)
  - ig_credit_spread_bps / gulf_reit_mom          -> snapshot (no free real-time feed)

The fetcher is best-effort and fail-soft: any network/parse failure returns None,
and the caller falls back to the snapshot for that single signal.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import httpx

logger = logging.getLogger("app.intel.live_market")

# snapshot signal key -> (Yahoo symbol, human source label)
_YAHOO: dict[str, Tuple[str, str]] = {
    "brent_oil": ("BZ=F", "ICE Brent (Yahoo Finance, live)"),
    "wti_oil": ("CL=F", "NYMEX WTI (Yahoo Finance, live)"),
    "usd_index_dxy": ("DX-Y.NYB", "ICE DXY (Yahoo Finance, live)"),
    "omxs30": ("%5EOMX", "Nasdaq OMX Stockholm 30 (Yahoo Finance, live)"),
}

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _yahoo_quote(symbol: str, timeout: float = 4.0) -> Tuple[float, Optional[float]]:
    """Return (last_price, previous_close) for a Yahoo symbol. Raises on failure."""
    r = httpx.get(
        _CHART_URL.format(symbol=symbol),
        params={"interval": "1d", "range": "5d"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=timeout,
    )
    r.raise_for_status()
    meta = r.json()["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None:
        raise ValueError("no regularMarketPrice in Yahoo response")
    return float(price), (float(prev) if prev is not None else None)


def _ecb_deposit_rate() -> Optional[Tuple[float, str, str]]:
    """Official ECB deposit facility rate from the ECB Data Portal (free, no key)."""
    try:
        r = httpx.get(
            "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV",
            params={"lastNObservations": "1", "format": "jsondata"},
            headers={"Accept": "application/json"},
            timeout=6,
        )
        r.raise_for_status()
        d = r.json()
        obs = list(d["dataSets"][0]["series"].values())[0]["observations"]
        value = float(list(obs.values())[0][0])
        as_of = d["structure"]["dimensions"]["observation"][0]["values"][-1]["id"]
        return value, "ECB Data Portal (official, live)", f" [official, as of {as_of}]"
    except Exception as e:  # noqa: BLE001
        logger.warning("ECB rate fetch failed: %s", e)
        return None


def _gulf_reit_mom() -> Optional[Tuple[float, str, str]]:
    """Real month-over-month % for the Gulf real-estate sleeve, proxied by
    Emaar Properties (EMAAR.AE, Dubai) — the most liquid listed Gulf RE name."""
    try:
        r = httpx.get(
            _CHART_URL.format(symbol="EMAAR.AE"),
            params={"interval": "1d", "range": "1mo"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
        )
        r.raise_for_status()
        closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        mom = (closes[-1] / closes[0] - 1.0) * 100.0
        return round(mom, 1), "EMAAR.AE proxy (Yahoo Finance, live)", f" [Emaar Properties {closes[-1]:g} AED]"
    except Exception as e:  # noqa: BLE001
        logger.warning("Gulf REIT MoM fetch failed: %s", e)
        return None


# signals with a non-Yahoo or computed live source
_SPECIAL = {
    "ecb_deposit_rate": _ecb_deposit_rate,
    "gulf_reit_mom": _gulf_reit_mom,
}


def live_value(key: str) -> Optional[Tuple[float, str, str]]:
    """Live (value, source_label, change_note) for a signal key, or None.

    ``change_note`` is a short day-over-day move string (e.g. " (-5.7% d/d)") or "".
    Returns None when the key has no live source or the fetch fails.
    """
    if key in _SPECIAL:
        res = _SPECIAL[key]()
        if res is not None:
            logger.info("live %s=%s%s", key, res[0], res[2])
        return res
    if key not in _YAHOO:
        return None
    symbol, label = _YAHOO[key]
    try:
        price, prev = _yahoo_quote(symbol)
    except Exception as e:  # noqa: BLE001
        logger.warning("live fetch failed for %s (%s): %s", key, symbol, e)
        return None

    note = ""
    if prev:
        chg = (price - prev) / prev * 100.0
        note = f" [{price:g} now, {chg:+.1f}% d/d]"
    value = round(price, 2)
    logger.info("live %s=%s%s", key, value, note)
    return value, label, note


def price_history(symbol: str, range_: str = "1mo", timeout: float = 5.0) -> Optional[list]:
    """Daily close series for a symbol (free Yahoo chart API). None on failure.

    Drops null closes (holidays/halts). Used to draw real per-holding trend
    sparklines instead of synthetic shapes.
    """
    try:
        r = httpx.get(
            _CHART_URL.format(symbol=symbol),
            params={"interval": "1d", "range": range_},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        res = r.json()["chart"]["result"][0]
        closes = res["indicators"]["quote"][0]["close"]
        series = [round(float(c), 4) for c in closes if c is not None]
        return series or None
    except Exception as e:  # noqa: BLE001
        logger.warning("price_history failed for %s: %s", symbol, e)
        return None


def fx_rate(base: str, quote: str, timeout: float = 4.0) -> Optional[float]:
    """Live FX cross via frankfurter.app (free, ECB-sourced, no key). None on failure."""
    try:
        r = httpx.get(
            "https://api.frankfurter.app/latest",
            params={"base": base, "symbols": quote},
            headers={"User-Agent": "agentic-awm-advisor"},
            timeout=timeout,
        )
        r.raise_for_status()
        return float(r.json()["rates"][quote])
    except Exception as e:  # noqa: BLE001
        logger.warning("FX fetch failed for %s%s: %s", base, quote, e)
        return None
