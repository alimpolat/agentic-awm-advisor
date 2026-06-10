/**
 * AgentMonitor — "Agent Ops" panel: the agent fleet as live status cards.
 *
 * Pokémon-box vibe, house style: each agent has an emoji avatar, a stage tag,
 * a status pill (idle / running / done / error), the activity it's performing
 * right now, last duration and run count. Polls GET /api/agents (2s while the
 * pipeline runs, 6s when idle). "Regenerate brief" triggers a live run so you
 * can watch the fleet light up stage by stage.
 */
import { useCallback, useEffect, useRef, useState } from "react";

interface AgentStatus {
  key: string;
  emoji: string;
  name: string;
  stage: string;
  role: string;
  status: "idle" | "running" | "done" | "error";
  activity: string | null;
  duration_s: number | null;
  runs: number;
  last_error: string | null;
}

interface FleetSnapshot {
  agents: AgentStatus[];
  pipeline_running: boolean;
}

const STATUS_STYLES: Record<AgentStatus["status"], string> = {
  idle: "bg-gray-100 text-gray-500 border-gray-300",
  running: "bg-clay/10 text-clay border-clay/40",
  done: "bg-olive/10 text-olive border-olive/30",
  error: "bg-rust/10 text-rust border-rust/40",
};

function StatusPill({ status }: { status: AgentStatus["status"] }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border font-mono text-[9px] uppercase tracking-wider ${STATUS_STYLES[status]}`}
    >
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

function AgentCard({ a }: { a: AgentStatus }) {
  const running = a.status === "running";
  return (
    <div
      className={`bg-paper border rounded-[12px] p-4 transition-all duration-300 ${
        running
          ? "border-clay/60 shadow-[0_0_0_3px_rgba(217,119,87,0.10)]"
          : "border-gray-300"
      }`}
    >
      <div className="flex items-start gap-3">
        <span
          className={`text-[26px] leading-none ${running ? "animate-bounce" : ""}`}
          style={running ? { animationDuration: "1.2s" } : undefined}
        >
          {a.emoji}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="font-serif font-semibold text-sm text-slate truncate">{a.name}</p>
            <StatusPill status={a.status} />
          </div>
          <p className="font-mono text-[9px] uppercase tracking-wider text-gray-500 mt-0.5">
            {a.stage}
          </p>
        </div>
      </div>

      <p className="font-serif text-[11px] text-gray-700 leading-snug mt-2 min-h-[28px]">
        {a.role}
      </p>

      {/* live activity line */}
      <p
        className={`font-mono text-[10px] mt-2 truncate ${
          a.status === "error" ? "text-rust" : running ? "text-clay" : "text-gray-500"
        }`}
        title={a.last_error ?? a.activity ?? undefined}
      >
        {a.status === "error"
          ? `✗ ${a.last_error ?? "failed"}`
          : a.activity ?? "waiting for work"}
      </p>

      <div className="flex justify-between font-mono text-[9px] text-gray-500 mt-2 pt-2 border-t border-gray-150">
        <span>{a.duration_s != null ? `last run ${a.duration_s}s` : "not run yet"}</span>
        <span>runs ×{a.runs}</span>
      </div>
    </div>
  );
}

export default function AgentMonitor({ clientId }: { clientId: string }) {
  const [fleet, setFleet] = useState<FleetSnapshot | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const timer = useRef<number | null>(null);

  const poll = useCallback(async () => {
    try {
      const res = await fetch("/api/agents");
      if (res.ok) {
        const snap: FleetSnapshot = await res.json();
        setFleet(snap);
        if (!snap.pipeline_running) setRegenerating(false);
        return snap.pipeline_running;
      }
    } catch {
      /* backend briefly away — keep last snapshot */
    }
    return false;
  }, []);

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

  return (
    <div className="mt-8">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-clay">
            Agent ops
          </p>
          <p className="font-serif text-sm text-gray-700">
            The fleet — every agent, live, instrumented at one seam
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider ${
              busy ? "text-clay" : "text-gray-500"
            }`}
          >
            {busy && (
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-clay opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-clay" />
              </span>
            )}
            {busy ? "pipeline running" : "fleet idle"}
          </span>
          <button
            onClick={regenerate}
            disabled={busy}
            className="font-mono text-[10px] uppercase tracking-wider px-3 py-1.5 rounded-full border border-clay/40 text-clay hover:bg-clay/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
          >
            {busy ? "running…" : "Regenerate brief"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {(fleet?.agents ?? []).map((a) => (
          <AgentCard key={a.key} a={a} />
        ))}
      </div>
    </div>
  );
}
