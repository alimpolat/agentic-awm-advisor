/**
 * AgentMonitor — "Agent Ops" dashboard: real-time fleet telemetry.
 *
 * Fleet KPI strip (runs · real token usage · avg latency · errors · last
 * pipeline wall-clock) → agent cards with live status, real per-run tokens,
 * avg duration and a duration-history sparkline → pipeline waterfall of the
 * last run (start offsets + durations, so the parallel fan-out is visible) →
 * live event feed. Polls GET /api/agents (2s running / 6s idle). All metrics
 * are real: token counts come from Gemini usage_metadata, instrumented at the
 * single run_agent_sync seam.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";

interface RunEntry {
  duration_s: number;
  tokens_in: number;
  tokens_out: number;
  ok: boolean;
  start_offset_s: number;
}

interface AgentStatus {
  key: string;
  emoji: string;
  name: string;
  stage: string;
  role: string;
  status: "idle" | "running" | "done" | "error";
  activity: string | null;
  duration_s: number | null;
  avg_duration_s: number | null;
  runs: number;
  errors: number;
  tokens_in: number;
  tokens_out: number;
  last_tokens_in: number | null;
  last_tokens_out: number | null;
  history: RunEntry[];
  last_error: string | null;
}

interface FleetEvent {
  ts: string;
  emoji: string;
  name: string;
  event: "start" | "done" | "error";
  detail: string;
}

interface PipelineRun {
  total_s: number;
  finished_at: string;
  agents: {
    key: string;
    emoji: string;
    name: string;
    start_offset_s: number;
    duration_s: number;
    ok: boolean;
  }[];
}

interface FleetSnapshot {
  agents: AgentStatus[];
  pipeline_running: boolean;
  totals: {
    runs: number;
    errors: number;
    tokens_in: number;
    tokens_out: number;
    avg_latency_s: number | null;
  };
  events: FleetEvent[];
  last_pipeline: PipelineRun | null;
}

const fmtK = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);

// ── KPI tile ──────────────────────────────────────────────────────────────────

function Kpi({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="bg-paper border border-gray-300 rounded-[10px] px-4 py-2.5 flex-1 min-w-[110px]">
      <p className="font-mono text-[9px] uppercase tracking-wider text-gray-500">{label}</p>
      <p className="font-mono text-[17px] font-semibold mt-0.5" style={accent ? { color: accent } : undefined}>
        {value}
      </p>
    </div>
  );
}

// ── Duration-history sparkline (inline SVG bars) ─────────────────────────────

function DurationSpark({ history }: { history: RunEntry[] }) {
  if (history.length < 2) return null;
  const h = history.slice(-12);
  const max = Math.max(...h.map((r) => r.duration_s), 0.1);
  const w = 4, gap = 2;
  return (
    <svg width={h.length * (w + gap)} height={18} className="inline-block align-middle">
      {h.map((r, i) => {
        const bh = Math.max(2, (r.duration_s / max) * 16);
        return (
          <rect key={i} x={i * (w + gap)} y={18 - bh} width={w} height={bh} rx={1}
            fill={r.ok ? "#788C5D" : "#B04A3F"} opacity={0.45 + 0.55 * (i / h.length)} />
        );
      })}
    </svg>
  );
}

// ── Status pill ───────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<AgentStatus["status"], string> = {
  idle: "bg-gray-100 text-gray-500 border-gray-300",
  running: "bg-clay/10 text-clay border-clay/40",
  done: "bg-olive/10 text-olive border-olive/30",
  error: "bg-rust/10 text-rust border-rust/40",
};

function StatusPill({ status }: { status: AgentStatus["status"] }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border font-mono text-[9px] uppercase tracking-wider ${STATUS_STYLES[status]}`}>
      {status === "running" && (
        <span className="relative flex h-1.5 w-1.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-clay opacity-75" />
          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-clay" />
        </span>
      )}
      {status}
    </span>
  );
}

// ── Agent card ────────────────────────────────────────────────────────────────

function AgentCard({ a }: { a: AgentStatus }) {
  const running = a.status === "running";
  return (
    <div className={`bg-paper border rounded-[12px] p-3.5 transition-all duration-300 ${
      running ? "border-clay/60 shadow-[0_0_0_3px_rgba(217,119,87,0.10)]" : "border-gray-300"
    }`}>
      <div className="flex items-start gap-2.5">
        <span className={`text-[22px] leading-none ${running ? "animate-bounce" : ""}`}
          style={running ? { animationDuration: "1.2s" } : undefined}>{a.emoji}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="font-serif font-semibold text-[13.5px] text-slate truncate">{a.name}</p>
            <StatusPill status={a.status} />
          </div>
          <p className="font-mono text-[8.5px] uppercase tracking-wider text-gray-500 mt-0.5">{a.stage}</p>
        </div>
      </div>

      <p className={`font-mono text-[9.5px] mt-2 truncate ${
        a.status === "error" ? "text-rust" : running ? "text-clay" : "text-gray-500"
      }`} title={a.last_error ?? a.activity ?? undefined}>
        {a.status === "error" ? `✗ ${a.last_error ?? "failed"}` : a.activity ?? "waiting for work"}
      </p>

      {/* metrics row */}
      <div className="grid grid-cols-3 gap-1 mt-2 pt-2 border-t border-gray-150 font-mono text-[9px] text-gray-500">
        <div>
          <p className="text-[8px] uppercase tracking-wide">last / avg</p>
          <p className="text-slate text-[10px] font-semibold">
            {a.duration_s != null ? `${a.duration_s}s` : "—"}
            <span className="text-gray-500 font-normal"> / {a.avg_duration_s != null ? `${a.avg_duration_s}s` : "—"}</span>
          </p>
        </div>
        <div>
          <p className="text-[8px] uppercase tracking-wide">tokens in→out</p>
          <p className="text-slate text-[10px] font-semibold">
            {a.last_tokens_in != null ? `${fmtK(a.last_tokens_in)}→${fmtK(a.last_tokens_out ?? 0)}` : "—"}
          </p>
        </div>
        <div>
          <p className="text-[8px] uppercase tracking-wide">runs · Σ tok</p>
          <p className="text-slate text-[10px] font-semibold">
            ×{a.runs}{a.errors > 0 && <span className="text-rust"> ✗{a.errors}</span>}
            <span className="text-gray-500 font-normal"> · {fmtK(a.tokens_in + a.tokens_out)}</span>
          </p>
        </div>
      </div>

      {/* duration history */}
      {a.history.length >= 2 && (
        <div className="mt-1.5 flex items-center gap-2">
          <DurationSpark history={a.history} />
          <span className="font-mono text-[8px] text-gray-500">run durations</span>
        </div>
      )}
    </div>
  );
}

// ── Pipeline waterfall (ECharts) ─────────────────────────────────────────────

function Waterfall({ run }: { run: PipelineRun }) {
  const agents = [...run.agents].sort((x, y) => x.start_offset_s - y.start_offset_s);
  const option = {
    textStyle: { fontFamily: "'JetBrains Mono', monospace" },
    grid: { left: 150, right: 60, top: 8, bottom: 24 },
    xAxis: {
      type: "value", max: Math.ceil(run.total_s),
      axisLabel: { color: "#87867F", fontSize: 9, formatter: "{value}s" },
      splitLine: { lineStyle: { color: "#E8E5DC", type: "dashed" } },
    },
    yAxis: {
      type: "category", inverse: true,
      data: agents.map((a) => `${a.emoji} ${a.name}`),
      axisLabel: { color: "#3D3D3A", fontSize: 10 },
      axisLine: { lineStyle: { color: "#D1CFC5" } }, axisTick: { show: false },
    },
    series: [
      { type: "bar", stack: "t", silent: true, itemStyle: { color: "transparent" },
        barWidth: 12, data: agents.map((a) => a.start_offset_s) },
      { type: "bar", stack: "t", barWidth: 12,
        itemStyle: { borderRadius: 3 },
        data: agents.map((a) => ({
          value: a.duration_s,
          itemStyle: { color: a.ok ? "#788C5D" : "#B04A3F" },
        })),
        label: { show: true, position: "right", fontSize: 9, color: "#87867F",
          fontFamily: "'JetBrains Mono', monospace", formatter: (p: { value: number }) => `${p.value}s` },
        animationDuration: 700,
      },
    ],
    tooltip: {
      backgroundColor: "rgba(255,255,255,.96)", borderColor: "#D1CFC5",
      textStyle: { color: "#141413", fontFamily: "'JetBrains Mono', monospace", fontSize: 11 },
      formatter: (p: { dataIndex: number; seriesIndex: number }) => {
        const a = agents[p.dataIndex];
        return `${a.emoji} ${a.name}<br/>start +${a.start_offset_s}s · ran ${a.duration_s}s`;
      },
    },
  };
  return <ReactECharts option={option} style={{ height: 30 + agents.length * 26 }} opts={{ renderer: "svg" }} />;
}

// ── Event feed ────────────────────────────────────────────────────────────────

const EVENT_COLOR: Record<FleetEvent["event"], string> = {
  start: "text-clay", done: "text-olive", error: "text-rust",
};

function EventFeed({ events }: { events: FleetEvent[] }) {
  return (
    <div className="bg-paper border border-gray-300 rounded-[12px] p-3 h-full max-h-[420px] overflow-y-auto">
      <p className="font-mono text-[9px] uppercase tracking-wider text-gray-500 mb-2 sticky top-0 bg-paper">
        Live event feed
      </p>
      {events.length === 0 && (
        <p className="font-mono text-[10px] text-gray-500">no events yet — run something</p>
      )}
      <div className="space-y-1.5">
        {events.map((e, i) => (
          <p key={i} className="font-mono text-[9.5px] leading-snug text-gray-700">
            <span className="text-gray-500">
              {new Date(e.ts).toLocaleTimeString("en-SE", { hour12: false })}
            </span>{" "}
            {e.emoji} <span className={EVENT_COLOR[e.event]}>{e.event}</span>{" "}
            <span className="text-gray-500">{e.detail}</span>
          </p>
        ))}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function AgentMonitor({
  clientId,
  onPipelineComplete,
}: {
  clientId: string;
  /** called when the fleet transitions running -> idle, so the page can
   *  re-fetch the freshly generated brief (new headlines, NBAs, chips) */
  onPipelineComplete?: () => void;
}) {
  const [fleet, setFleet] = useState<FleetSnapshot | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const timer = useRef<number | null>(null);
  const wasRunning = useRef(false);

  const poll = useCallback(async () => {
    try {
      const res = await fetch("/api/agents");
      if (res.ok) {
        const snap: FleetSnapshot = await res.json();
        setFleet(snap);
        if (!snap.pipeline_running) {
          setRegenerating(false);
          if (wasRunning.current) onPipelineComplete?.();
        }
        wasRunning.current = snap.pipeline_running;
        return snap.pipeline_running;
      }
    } catch {
      /* backend briefly away — keep last snapshot */
    }
    return false;
  }, [onPipelineComplete]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      const busy = await poll();
      timer.current = window.setTimeout(tick, busy || regenerating ? 2000 : 6000);
    };
    tick();
    return () => {
      alive = false;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [poll, regenerating]);

  const regenerate = async () => {
    setRegenerating(true);
    try {
      await fetch(`/api/brief/${clientId}?refresh=true`);
    } catch {
      /* polling shows real state */
    }
  };

  const busy = fleet?.pipeline_running || regenerating;
  const t = fleet?.totals;

  return (
    <div className="mt-8">
      {/* header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-clay">Agent ops</p>
          <p className="font-serif text-sm text-gray-700">
            Real-time fleet telemetry — tokens from Gemini usage metadata, one instrumentation seam
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider ${busy ? "text-clay" : "text-gray-500"}`}>
            {busy && (
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-clay opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-clay" />
              </span>
            )}
            {busy ? "pipeline running" : "fleet idle"}
          </span>
          <button onClick={regenerate} disabled={busy}
            className="font-mono text-[10px] uppercase tracking-wider px-3 py-1.5 rounded-full border border-clay/40 text-clay hover:bg-clay/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer">
            {busy ? "running…" : "Regenerate brief"}
          </button>
        </div>
      </div>

      {/* KPI strip */}
      {t && (
        <div className="flex flex-wrap gap-2 mb-3">
          <Kpi label="Agent runs" value={`${t.runs}`} />
          <Kpi label="Tokens in" value={fmtK(t.tokens_in)} accent="#788C5D" />
          <Kpi label="Tokens out" value={fmtK(t.tokens_out)} accent="#788C5D" />
          <Kpi label="Avg latency" value={t.avg_latency_s != null ? `${t.avg_latency_s}s` : "—"} />
          <Kpi label="Errors" value={`${t.errors}`} accent={t.errors > 0 ? "#B04A3F" : undefined} />
          <Kpi label="Last pipeline" value={fleet?.last_pipeline ? `${fleet.last_pipeline.total_s}s` : "—"} accent="#D97757" />
        </div>
      )}

      {/* cards + event feed */}
      <div className="grid lg:grid-cols-[1fr_280px] gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">
          {(fleet?.agents ?? []).map((a) => <AgentCard key={a.key} a={a} />)}
        </div>
        <EventFeed events={fleet?.events ?? []} />
      </div>

      {/* waterfall of the last pipeline run */}
      {fleet?.last_pipeline && fleet.last_pipeline.agents.length > 1 && (
        <div className="bg-paper border border-gray-300 rounded-[12px] p-4 mt-3">
          <p className="font-mono text-[9px] uppercase tracking-wider text-gray-500 mb-1">
            Last pipeline run — {fleet.last_pipeline.total_s}s wall-clock · parallel fan-out visible as overlapping bars
          </p>
          <Waterfall run={fleet.last_pipeline} />
        </div>
      )}
    </div>
  );
}
