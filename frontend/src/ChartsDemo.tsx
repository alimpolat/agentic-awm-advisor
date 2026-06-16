/**
 * ChartsDemo — visual review page for all 6 chart components.
 * Accessible at /#charts (hash route — no router dependency).
 * Feed with realistic fixture data mirroring Bergström family office.
 */
import AllocationDonut from "./charts/AllocationDonut";
import DriftBars from "./charts/DriftBars";
import MacroRadar from "./charts/MacroRadar";
import NbaProjection from "./charts/NbaProjection";
import CitationSankey from "./charts/CitationSankey";
import Sparkline from "./charts/Sparkline";

// ── Fixture data ──────────────────────────────────────────────────────────────

const TARGET_ALLOC = {
  "Nordic equity": 0.35,
  "US tech": 0.15,
  "EU fixed income": 0.20,
  "Gulf real estate": 0.10,
  Alternatives: 0.20,
};

const CURRENT_ALLOC = {
  "Nordic equity": 0.35,
  "US tech": 0.20,
  "EU fixed income": 0.15,
  "Gulf real estate": 0.15,
  Alternatives: 0.15,
};

const DRIFT_DATA = [
  { asset_class: "US tech", drift_pp: 5 },
  { asset_class: "Gulf real estate", drift_pp: 5 },
  { asset_class: "EU fixed income", drift_pp: -5 },
  { asset_class: "Alternatives", drift_pp: -5 },
  { asset_class: "Nordic equity", drift_pp: 0 },
];

const RADAR_INDICATORS = [
  { name: "Brent crude", max: 10 },
  { name: "ECB rate", max: 10 },
  { name: "DXY index", max: 10 },
  { name: "OMXS30", max: 10 },
  { name: "Gulf REIT", max: 10 },
  { name: "IG spread", max: 10 },
];
const RADAR_VALUES = [6.5, 7.2, 5.8, 6.0, 8.1, 4.3];

// 12-month projection (SEK, ~480M base)
const BASE = 480_000_000;
const NBA_MONTHS = Array.from({ length: 12 }, (_, i) => i);
const WITHOUT_ACTION = NBA_MONTHS.map((i) => Math.round(BASE * (1 + 0.003 * i)));
const WITH_ACTION = NBA_MONTHS.map((i) =>
  Math.round(BASE * (1 + 0.003 * i + 0.0045 * i * (1 - Math.exp(-i / 5))))
);

const SANKEY_LINKS = [
  { source: "Trim US tech overweight", target: "bergstrom_portfolio_q1_2026", value: 2 },
  { source: "Trim US tech overweight", target: "bergstrom_ips", value: 1 },
  { source: "Correct FX breach", target: "bergstrom_ips", value: 2 },
  { source: "Correct FX breach", target: "norges_bank_fx_report_2026", value: 1 },
  { source: "Add green bonds", target: "ecb_economic_bulletin_2026", value: 2 },
  { source: "Add green bonds", target: "bergstrom_meeting_2026_04", value: 1 },
];

// 30-day sparklines
const SPARK_UP = Array.from({ length: 30 }, (_, i) =>
  +(100 + i * 0.4 + Math.sin(i * 0.7) * 1.2).toFixed(2)
);
const SPARK_DOWN = Array.from({ length: 30 }, (_, i) =>
  +(100 - i * 0.3 + Math.sin(i * 0.9) * 1.0).toFixed(2)
);

// ── Card wrapper ──────────────────────────────────────────────────────────────

function VizCard({ title, subtitle, children }: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: "#FFFFFF",
        border: "1px solid #D1CFC5",
        borderRadius: 10,
        padding: "20px 24px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div>
        <p
          style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "#D97757",
            margin: 0,
          }}
        >
          {title}
        </p>
        {subtitle && (
          <p style={{ fontFamily: "Newsreader, Georgia, serif", fontSize: 13, color: "#87867F", margin: "2px 0 0" }}>
            {subtitle}
          </p>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}

// ── Demo page ─────────────────────────────────────────────────────────────────

export default function ChartsDemo() {
  return (
    <div
      style={{
        background: "#FAF9F5",
        minHeight: "100vh",
        padding: "32px 24px 64px",
        fontFamily: "Newsreader, Georgia, serif",
      }}
    >
      {/* Header */}
      <div style={{ maxWidth: 1080, margin: "0 auto 32px" }}>
        <p
          style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10,
            textTransform: "uppercase",
            letterSpacing: "0.12em",
            color: "#D97757",
            margin: "0 0 6px",
          }}
        >
          AWM AI · Chart Library
        </p>
        <h1 style={{ fontSize: 28, fontWeight: 600, color: "#141413", margin: "0 0 4px" }}>
          ECharts House Theme — Visual Review
        </h1>
        <p style={{ color: "#87867F", fontSize: 14, margin: 0 }}>
          All 6 components fed with Bergström fixture data. Route: <code style={{ fontFamily: "monospace", background: "#F0EEE6", padding: "1px 5px", borderRadius: 3 }}>#charts</code>
        </p>
      </div>

      {/* 2-column grid */}
      <div
        style={{
          maxWidth: 1080,
          margin: "0 auto",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(460px, 1fr))",
          gap: 20,
        }}
      >
        <VizCard
          title="1 · Allocation Donut"
          subtitle="Inner ring = target · Outer ring = current (Bergström family office)"
        >
          <AllocationDonut target={TARGET_ALLOC} current={CURRENT_ALLOC} />
        </VizCard>

        <VizCard
          title="2 · Drift Bars"
          subtitle="Allocation drift vs IPS target — rust > 4 pp, amber 2–4 pp, olive ≤ 2 pp"
        >
          <DriftBars drift={DRIFT_DATA} />
        </VizCard>

        <VizCard
          title="3 · Macro Radar"
          subtitle="Composite macro signals — normalised to indicator max"
        >
          <MacroRadar indicators={RADAR_INDICATORS} values={RADAR_VALUES} />
        </VizCard>

        <VizCard
          title="4 · NBA Projection"
          subtitle="12-month portfolio value: olive = with NBA actions · dashed = without"
        >
          <NbaProjection withAction={WITH_ACTION} withoutAction={WITHOUT_ACTION} />
        </VizCard>

        <VizCard
          title="5 · Citation Sankey"
          subtitle="NBA claims → backing source documents (trust surface)"
        >
          <CitationSankey links={SANKEY_LINKS} height={320} />
        </VizCard>

        <VizCard
          title="6 · Sparklines"
          subtitle="30-day inline price trends for holdings table rows"
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "8px 0" }}>
            {[
              { label: "OMXS30 · Nordic equity ETF", data: SPARK_UP, positive: true },
              { label: "USDSEK FX hedge · negative", data: SPARK_DOWN, positive: false },
              { label: "Norsk Hydro · mixed", data: SPARK_UP.map((v, i) => i % 5 === 0 ? v - 2 : v), positive: true },
            ].map((row) => (
              <div
                key={row.label}
                style={{ display: "flex", alignItems: "center", gap: 14 }}
              >
                <Sparkline data={row.data} positive={row.positive} width={90} height={28} />
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 11,
                    color: "#87867F",
                  }}
                >
                  {row.label}
                </span>
              </div>
            ))}
          </div>
        </VizCard>
      </div>
    </div>
  );
}
