/**
 * API wrappers using relative URLs so the same code works in:
 *   dev  → Vite proxy at /api → http://localhost:8001
 *   prod → served from app/static by uvicorn
 */
import type {
  BriefSchema,
  ClientSnapshot,
  HitlRequest,
  ChatRequest,
  ChatResponse,
} from "./types";

async function apiFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const res = await fetch(input, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.detail ?? JSON.stringify(body);
    } catch {
      // ignore parse failure
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function getBrief(clientId: string): Promise<BriefSchema> {
  return apiFetch<BriefSchema>(`/api/brief/${clientId}`);
}

export function getClient(clientId: string): Promise<ClientSnapshot> {
  return apiFetch<ClientSnapshot>(`/api/client/${clientId}`);
}

export type HitlAction = "approve" | "edit" | "regenerate" | "reject";

export interface HitlResponse {
  ok: boolean;
  action: HitlAction;
  logged: boolean;
  log_size: number;
}

export function postHitl(
  action: HitlAction,
  req: HitlRequest
): Promise<HitlResponse> {
  return apiFetch<HitlResponse>(`/api/hitl/${action}`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export interface FollowUpResponse {
  ok: boolean;
  saved: string;
  regenerating: boolean;
}

/** Persist after-meeting notes; server regenerates the brief in the background. */
export function postFollowUp(
  clientId: string,
  notes: string
): Promise<FollowUpResponse> {
  return apiFetch<FollowUpResponse>(`/api/followup/${clientId}`, {
    method: "POST",
    body: JSON.stringify({ notes }),
  });
}

export interface TrendSeries {
  closes: number[];
  source: "live" | "unavailable";
}
export type TrendsMap = Record<string, TrendSeries>;

/** Real per-holding 30-day close trends (free live feed, cached server-side). */
export function getTrends(clientId: string): Promise<TrendsMap> {
  return apiFetch<TrendsMap>(`/api/trends/${clientId}`);
}

export function postChat(req: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify(req),
  });
}
