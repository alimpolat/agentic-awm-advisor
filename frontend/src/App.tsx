/**
 * App.tsx — Advisor Cockpit, 70/30 split.
 * Left (70%): ClientHeader → OpportunitiesPanel → WeekendChangesPanel
 *             → 3 × NbaCard → RiskFlags → FollowUpPanel
 * Right (30%): Chat placeholder (Task 4.4 fills this).
 * CitationDrawer managed at App level.
 */
import { useState, useEffect } from "react";
import { getBrief, getClient } from "./api";
import type { BriefSchema, ClientSnapshot, EvidenceRef } from "./types";

import ClientHeader from "./components/ClientHeader";
import OpportunitiesPanel from "./components/OpportunitiesPanel";
import WeekendChangesPanel from "./components/WeekendChangesPanel";
import NbaCard from "./components/NbaCard";
import RiskFlags from "./components/RiskFlags";
import FollowUpPanel from "./components/FollowUpPanel";
import CitationDrawer from "./components/CitationDrawer";
import ChatPanel from "./components/ChatPanel";
import AgentMonitor from "./components/AgentMonitor";
import ChartsDemo from "./ChartsDemo";

const CLIENT_ID = "bergstrom";

// ── Loading skeleton ─────────────────────────────────────────────────────────

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`bg-gray-150 rounded-lg animate-pulse ${className}`}
    />
  );
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-48" />
      <Skeleton className="h-32" />
      <Skeleton className="h-64" />
      <Skeleton className="h-80" />
      <Skeleton className="h-80" />
      <Skeleton className="h-80" />
      <Skeleton className="h-20" />
    </div>
  );
}

// ── Error state ──────────────────────────────────────────────────────────────

function ErrorState({ message }: { message: string }) {
  return (
    <div className="bg-paper border border-rust/30 rounded-[14px] p-8 text-center">
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-rust mb-3">
        Error loading brief
      </p>
      <p className="font-serif text-slate text-base mb-2">
        Could not connect to the advisor API.
      </p>
      <p className="font-mono text-xs text-gray-500 mb-4">{message}</p>
      <p className="text-sm font-serif text-gray-500">
        Ensure uvicorn is running on{" "}
        <code className="font-mono bg-gray-100 px-1.5 py-0.5 rounded text-xs">
          localhost:8001
        </code>{" "}
        and the brief cache is populated.
      </p>
    </div>
  );
}

// ── Main cockpit ─────────────────────────────────────────────────────────────

function Cockpit({
  brief,
  client,
  onRefresh,
}: {
  brief: BriefSchema;
  client: ClientSnapshot;
  onRefresh?: () => void;
}) {
  const [citeRefs, setCiteRefs] = useState<EvidenceRef[] | null>(null);

  return (
    <>
      {/* 70/30 split */}
      <div className="flex gap-6 items-start">
        {/* Left column — 70% */}
        <div className="flex-1 min-w-0 space-y-5">
          <ClientHeader client={client} brief={brief} />
          <OpportunitiesPanel
            opportunities={brief.opportunities}
            onCite={setCiteRefs}
          />
          <WeekendChangesPanel
            changes={brief.weekend_changes}
            onCite={setCiteRefs}
          />

          {/* NBA section header */}
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-clay mb-3">
              Next best actions
            </p>
            <div className="space-y-5">
              {brief.three_nbas.map((nba, i) => (
                <NbaCard
                  key={i}
                  nba={nba}
                  index={i}
                  clientId={CLIENT_ID}
                  onCite={setCiteRefs}
                />
              ))}
            </div>
          </div>

          <RiskFlags flags={brief.risk_flags} />
          <FollowUpPanel />
          <AgentMonitor clientId={CLIENT_ID} onPipelineComplete={onRefresh} />
        </div>

        {/* Right column — 30% */}
        <div className="w-80 xl:w-96 flex-shrink-0">
          <ChatPanel clientId={CLIENT_ID} onCite={setCiteRefs} brief={brief} />
        </div>
      </div>

      {/* Citation drawer — managed at App level */}
      <CitationDrawer
        refs={citeRefs}
        onClose={() => setCiteRefs(null)}
      />
    </>
  );
}

// ── App root ─────────────────────────────────────────────────────────────────

export default function App() {
  // Hash-based route to the charts demo
  const isChartsRoute =
    window.location.hash === "#charts" ||
    window.location.pathname === "/charts";

  const [brief, setBrief] = useState<BriefSchema | null>(null);
  const [client, setClient] = useState<ClientSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // silent=true refreshes data in place (no skeleton flash) — used after a
  // pipeline run completes so new headlines/NBAs/chips appear automatically.
  const load = (silent = false) => {
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    Promise.all([getBrief(CLIENT_ID), getClient(CLIENT_ID)])
      .then(([b, c]) => {
        setBrief(b);
        setClient(c);
      })
      .catch((e: Error) => {
        if (!silent) setError(e.message);
      })
      .finally(() => {
        if (!silent) setLoading(false);
      });
  };

  useEffect(() => {
    if (isChartsRoute) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isChartsRoute]);

  if (isChartsRoute) return <ChartsDemo />;

  return (
    <div className="min-h-screen bg-ivory">
      {/* Top strip */}
      <header className="bg-paper border-b border-gray-300 px-6 py-3">
        <div className="max-w-[1400px] mx-auto flex items-center justify-between">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-clay">
            AWM AI · Advisor Cockpit
          </p>
          {client && (
            <p className="font-serif text-slate text-sm font-semibold">
              {client.client_name}
            </p>
          )}
          <a
            href="#charts"
            className="font-mono text-[10px] text-gray-500 hover:text-clay transition-colors"
          >
            Chart library →
          </a>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-[1400px] mx-auto px-6 py-6">
        {loading && <LoadingState />}
        {error && <ErrorState message={error} />}
        {!loading && !error && brief && client && (
          <Cockpit brief={brief} client={client} onRefresh={() => load(true)} />
        )}
      </main>
    </div>
  );
}
