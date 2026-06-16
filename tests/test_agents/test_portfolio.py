"""Live tests for the Stage-3d Portfolio Analytics specialist.

Makes real Vertex AI / Gemini Flash calls (embed + rerank + synthesis).
Marked 'live'; deselected from the offline suite with -m 'not live'.
pytest asyncio_mode = "auto" (pyproject.toml) means plain `async def` tests work.

Key design contract
-------------------
* drift_signals, ips_compliance, ytd_summary are computed in Python (deterministic).
* opportunities come from the LLM (grounded in retrieved chunks).
* The tests assert the Python-computed numbers and the overall shape of the result.
"""
import pytest

from app.agents import portfolio
from app.schemas import PortfolioFinding

pytestmark = pytest.mark.live

_SUB_QUESTIONS = [
    "What is the Bergström portfolio's current drift from IPS target allocations?",
    "Are there any IPS compliance breaches (single-position limit, FX floor)?",
    "What are the YTD performance and income figures for the portfolio?",
    "Are there a Nordic private bank green-bond or ESG fixed-income products suited to rebuild the EU FI sleeve?",
]

# Expected asset classes from the portfolio fixture
_EXPECTED_ASSET_CLASSES = {
    "Nordic equity",
    "US tech",
    "EU fixed income",
    "Gulf real estate",
    "Alternatives",
}


@pytest.fixture(scope="module")
async def portfolio_finding() -> PortfolioFinding:
    """Call the agent once; reuse across all tests in this module."""
    result = await portfolio.run(_SUB_QUESTIONS)

    # Print computed values for human eyeball check + CI logs
    print("\n--- Portfolio Analytics findings ---")

    print("\n  drift_signals:")
    for d in result.drift_signals:
        print(
            f"    {d['asset_class']:<22}  current={d['current_pct']:.1f}%  "
            f"target={d['target_pct']:.1f}%  drift={d['drift_pp']:+.2f}pp"
        )

    fx_entry = next(
        (e for e in result.ips_compliance if e.get("rule") == "fx_floor_sek"), None
    )
    if fx_entry:
        print(
            f"\n  fx_floor_sek: sek_pct={fx_entry['sek_pct']}%  "
            f"floor={fx_entry['floor_pct']}%  status={fx_entry['status']!r}"
        )

    print(f"\n  ytd_summary: {result.ytd_summary}")

    print("\n  opportunities:")
    for opp in result.opportunities:
        print(f"    - {opp}")

    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_drift_signals_covers_all_asset_classes(portfolio_finding):
    """drift_signals must contain one entry per expected asset class."""
    found_classes = {d["asset_class"] for d in portfolio_finding.drift_signals}
    missing = _EXPECTED_ASSET_CLASSES - found_classes
    assert not missing, (
        f"Missing asset classes in drift_signals: {missing}. "
        f"Got: {found_classes}"
    )


async def test_us_tech_drift_is_five_pp(portfolio_finding):
    """US tech overweight must be +5.00pp (deterministic Python computation)."""
    us_tech = next(
        (d for d in portfolio_finding.drift_signals if d["asset_class"] == "US tech"),
        None,
    )
    assert us_tech is not None, "US tech entry missing from drift_signals"
    assert abs(us_tech["drift_pp"] - 5.0) < 0.01, (
        f"Expected US tech drift ≈ +5.00pp, got {us_tech['drift_pp']}"
    )


async def test_gulf_real_estate_drift_is_five_pp(portfolio_finding):
    """Gulf real estate overweight must be +5.00pp (deterministic Python computation)."""
    gulf = next(
        (d for d in portfolio_finding.drift_signals if d["asset_class"] == "Gulf real estate"),
        None,
    )
    assert gulf is not None, "Gulf real estate entry missing from drift_signals"
    assert abs(gulf["drift_pp"] - 5.0) < 0.01, (
        f"Expected Gulf real estate drift ≈ +5.00pp, got {gulf['drift_pp']}"
    )


async def test_fx_floor_breach(portfolio_finding):
    """FX floor rule must be present in ips_compliance and must be a breach.

    SEK base share is ~35% — well below the 60% floor.
    """
    fx_entry = next(
        (e for e in portfolio_finding.ips_compliance if e.get("rule") == "fx_floor_sek"),
        None,
    )
    assert fx_entry is not None, (
        "No 'fx_floor_sek' entry found in ips_compliance. "
        f"ips_compliance = {portfolio_finding.ips_compliance}"
    )
    assert fx_entry["status"] == "breach", (
        f"Expected fx_floor_sek status='breach', got {fx_entry['status']!r}. "
        f"sek_pct={fx_entry.get('sek_pct')}"
    )


async def test_fx_sek_pct_is_approximately_35(portfolio_finding):
    """SEK base share must be close to 35% (168M / 480M)."""
    fx_entry = next(
        (e for e in portfolio_finding.ips_compliance if e.get("rule") == "fx_floor_sek"),
        None,
    )
    assert fx_entry is not None
    sek_pct = fx_entry["sek_pct"]
    assert abs(sek_pct - 35.0) < 0.5, (
        f"Expected SEK pct ≈ 35.0%, got {sek_pct}"
    )


async def test_ytd_summary_weighted_return_is_positive(portfolio_finding):
    """Weighted YTD return must be a positive float (portfolio is up YTD)."""
    ytd_pct = portfolio_finding.ytd_summary.get("weighted_ytd_pct")
    assert isinstance(ytd_pct, (int, float)), (
        f"weighted_ytd_pct is not a number: {ytd_pct!r}"
    )
    assert ytd_pct > 0, (
        f"Expected positive weighted_ytd_pct, got {ytd_pct}"
    )


async def test_ytd_summary_has_required_keys(portfolio_finding):
    """ytd_summary must contain the three required keys."""
    required = {"weighted_ytd_pct", "total_mv_sek", "total_dividend_ytd_sek"}
    missing = required - set(portfolio_finding.ytd_summary.keys())
    assert not missing, (
        f"ytd_summary missing keys: {missing}. Got: {set(portfolio_finding.ytd_summary.keys())}"
    )


async def test_computation_trace_is_non_empty(portfolio_finding):
    """computation_trace must be a non-empty string (the audit trail)."""
    trace = portfolio_finding.computation_trace
    assert isinstance(trace, str) and len(trace.strip()) > 0, (
        f"Expected non-empty computation_trace, got: {trace!r}"
    )


async def test_opportunities_is_non_empty_list_of_strings(portfolio_finding):
    """opportunities must be a non-empty list of non-empty strings."""
    opps = portfolio_finding.opportunities
    assert isinstance(opps, list) and len(opps) > 0, (
        f"Expected non-empty opportunities list, got: {opps!r}"
    )
    for opp in opps:
        assert isinstance(opp, str) and len(opp.strip()) > 0, (
            f"Opportunity entry is not a non-empty string: {opp!r}"
        )


async def test_single_position_breaches_present(portfolio_finding):
    """At least one single-position breach must be present.

    The fixture has 7 non-fund positions above the 5% limit.
    """
    sp_breaches = [
        e for e in portfolio_finding.ips_compliance
        if e.get("rule") == "single_position_limit" and e.get("status") == "breach"
    ]
    assert len(sp_breaches) >= 1, (
        "Expected at least one single_position_limit breach. "
        f"ips_compliance = {portfolio_finding.ips_compliance}"
    )
