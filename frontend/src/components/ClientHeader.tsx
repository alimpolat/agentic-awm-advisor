/**
 * ClientHeader — top banner with client overview, intel badge, AllocationDonut,
 * and a holdings table where each row has an inline Sparkline.
 *
 * Current allocation is computed from holdings:
 *   current[asset_class] = sum(current_mv for that class) / aum_sek
 */
import { useEffect, useState } from "react";
import type { ClientSnapshot, BriefSchema } from "../types";
import { getTrends, type TrendsMap } from "../api";
import AllocationDonut from "../charts/AllocationDonut";
import Sparkline from "../charts/Sparkline";

interface Props {
  client: ClientSnapshot;
  brief: BriefSchema;
}

const INTEL_CLASSES: Record<string, string> = {
  live: "bg-olive/10 text-olive border-olive/40",
  snapshot: "bg-amber/10 text-amber-dark border-amber/40",
  mixed: "bg-clay/10 text-clay border-clay/40",
};

const INTEL_LABELS: Record<string, string> = {
  live: "Live data",
  snapshot: "Snapshot",
  mixed: "Mixed",
};

/** Format SEK with M/B suffix */
function fmtSek(n: number): string {
  if (n >= 1_000_000_000) return `SEK ${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `SEK ${(n / 1_000_000).toFixed(0)}M`;
  return `SEK ${n.toLocaleString("sv-SE")}`;
}

/** Generate a deterministic ~30-point sparkline series from ytd_return_pct */
function sparkSeries(ytd: number, seed: number): number[] {
  const base = 100;
  return Array.from({ length: 30 }, (_, i) => {
    const trend = base + ytd * (i / 29);
    const noise = Math.sin(i * 0.7 + seed) * Math.abs(ytd) * 0.3;
    return +(trend + noise).toFixed(2);
  });
}

/** Compute current allocation from holdings */
function computeCurrentAlloc(
  holdings: ClientSnapshot["holdings"],
  aum: number
): Record<string, number> {
  const byClass: Record<string, number> = {};
  for (const h of holdings) {
    byClass[h.asset_class] = (byClass[h.asset_class] ?? 0) + h.current_mv;
  }
  const result: Record<string, number> = {};
  for (const [cls, mv] of Object.entries(byClass)) {
    result[cls] = mv / aum;
  }
  return result;
}

export default function ClientHeader({ client, brief }: Props) {
  const currentAlloc = computeCurrentAlloc(client.holdings, client.aum_sek);

  // Real per-holding 30-day price trends (live feed). Falls back to an
  // indicative line per holding that has no market price (bonds, illiquid funds).
  const [trends, setTrends] = useState<TrendsMap>({});
  useEffect(() => {
    let alive = true;
    getTrends(client.client_id)
      .then((t) => alive && setTrends(t))
      .catch(() => {}); // fall back to indicative shapes on any failure
    return () => {
      alive = false;
    };
  }, [client.client_id]);

  // Format generated_at
  const genAt = new Date(brief.generated_at);
  const genAtStr = genAt.toLocaleTimeString("en-SE", {
    hour: "2-digit",
    minute: "2-digit",
  });

  // Format last_meeting_date
  const lastMeeting = new Date(client.last_meeting_date).toLocaleDateString(
    "en-SE",
    { day: "numeric", month: "short", year: "numeric" }
  );

  return (
    <div className="bg-paper border border-gray-300 rounded-[14px] overflow-hidden">
      {/* Top info bar */}
      <div className="px-6 py-4 border-b border-gray-300">
        <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
          <div className="flex-1 min-w-0">
            <h2 className="font-serif text-slate text-2xl font-semibold leading-tight">
              {client.client_name}
            </h2>
            <p className="font-mono text-[12px] text-gray-500 mt-0.5">
              {fmtSek(client.aum_sek)} AUM
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs font-mono text-gray-500 mt-1">
            <span className="bg-gray-100 border border-gray-300 rounded-full px-2.5 py-0.5">
              Meeting today 14:00
            </span>
            <span className="bg-gray-100 border border-gray-300 rounded-full px-2.5 py-0.5">
              Last touch {lastMeeting}
            </span>
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full border ${INTEL_CLASSES[brief.intel_mode]}`}
            >
              {INTEL_LABELS[brief.intel_mode]}
            </span>
            <span className="text-gray-500">Generated {genAtStr}</span>
          </div>
        </div>

        {/* Stated concerns + restrictions */}
        {(client.stated_concerns.length > 0 || client.restrictions.length > 0) && (
          <div className="mt-3 flex flex-wrap gap-4 text-xs font-mono text-gray-700">
            {client.stated_concerns.length > 0 && (
              <div>
                <span className="text-clay uppercase tracking-wide text-[10px]">
                  Concerns:{" "}
                </span>
                {client.stated_concerns.join(" · ")}
              </div>
            )}
            {client.restrictions.length > 0 && (
              <div>
                <span className="text-rust uppercase tracking-wide text-[10px]">
                  Restrictions:{" "}
                </span>
                {client.restrictions.join(" · ")}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Allocation donut + holdings table */}
      <div className="grid lg:grid-cols-[360px_1fr] gap-0">
        {/* Donut */}
        <div className="px-4 py-4 border-b lg:border-b-0 lg:border-r border-gray-300">
          <p className="font-mono text-[10px] uppercase tracking-widest text-gray-500 mb-0.5 px-2">
            Allocation
          </p>
          <p className="font-mono text-[10px] text-gray-500 px-2 mb-1">
            current allocation · drift vs IPS target
          </p>
          <AllocationDonut
            target={client.target_allocation}
            current={currentAlloc}
            height={340}
          />
        </div>

        {/* Holdings table */}
        <div className="px-6 py-4 overflow-x-auto">
          <p className="font-mono text-[10px] uppercase tracking-widest text-gray-500 mb-3">
            Holdings ({client.holdings.length})
          </p>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-300">
                {["Name", "Asset class", "MV (SEK)", "YTD %", "FX", "Trend"].map(
                  (h) => (
                    <th
                      key={h}
                      className="text-left font-mono text-[10px] uppercase tracking-wide text-gray-500 pb-2 pr-4 whitespace-nowrap"
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {client.holdings.map((h, i) => {
                const series = trends[h.ticker];
                const live = series?.source === "live" && series.closes.length > 1;
                const spark = live
                  ? series!.closes
                  : sparkSeries(h.ytd_return_pct, i * 3.7);
                // YTD cell reflects the actual YTD return; the sparkline
                // reflects the 30-day trend — they can legitimately disagree
                // (e.g. up YTD but down over the last month).
                const ytdPositive = h.ytd_return_pct >= 0;
                const trendPositive = live
                  ? spark[spark.length - 1] >= spark[0]
                  : ytdPositive;
                return (
                  <tr
                    key={h.ticker}
                    className="border-b border-gray-300/50 last:border-0"
                  >
                    <td className="py-2 pr-4">
                      <p className="font-serif text-slate text-xs leading-tight">
                        {h.name}
                      </p>
                      <p className="font-mono text-[10px] text-gray-500">
                        {h.ticker}
                      </p>
                    </td>
                    <td className="py-2 pr-4 font-mono text-[11px] text-gray-700 whitespace-nowrap">
                      {h.asset_class}
                    </td>
                    <td className="py-2 pr-4 font-mono text-[11px] text-slate tabular-nums whitespace-nowrap">
                      {(h.current_mv / 1_000_000).toFixed(1)}M
                    </td>
                    <td
                      className={`py-2 pr-4 font-mono text-[11px] tabular-nums whitespace-nowrap font-semibold ${
                        ytdPositive ? "text-olive" : "text-rust"
                      }`}
                    >
                      {ytdPositive ? "+" : ""}
                      {h.ytd_return_pct.toFixed(1)}%
                    </td>
                    <td className="py-2 pr-4 font-mono text-[11px] text-gray-700">
                      {h.fx_exposure}
                    </td>
                    <td className="py-2">
                      <Sparkline
                        data={spark}
                        positive={trendPositive}
                        indicative={!live}
                        width={80}
                        height={24}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
