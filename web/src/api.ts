import type { QItem, SessionEvent } from "./types";

const base = ""; // same origin (served by FastAPI) or proxied in dev

export interface CreatedSession { session_id: string; join_code: string; }

export async function createSession(participantId?: string, experimentId?: string): Promise<CreatedSession> {
  const res = await fetch(`${base}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ participant_id: participantId, experiment_id: experimentId, consent: true }),
  });
  if (!res.ok) throw new Error(`createSession failed: ${res.status}`);
  return await res.json();
}

export interface PastSession {
  session_id: string; join_code: string | null; started_at: string | null; phase: string | null;
  status: "live" | "complete" | "aborted" | "interrupted"; abort_reason?: string | null;
  participant_messages?: number; real_outcome?: string | null; match_flag?: boolean | null;
  device?: string | null; steered?: boolean; saved: boolean; resumable: boolean; live: boolean;
}

export async function getHistory(token: string): Promise<PastSession[]> {
  const res = await fetch(`${base}/sessions/history`, { headers: { "X-Admin-Token": token } });
  if (!res.ok) throw new Error("unauthorized");
  return (await res.json()).sessions;
}

export async function reopenSession(token: string, sessionId: string): Promise<{ join_code: string; phase: string }> {
  const res = await fetch(`${base}/sessions/${sessionId}/reopen`, { method: "POST", headers: { "X-Admin-Token": token } });
  if (!res.ok) throw new Error((await res.json()).detail ?? "reopen failed");
  return await res.json();
}

/** Resolve a join code from the researcher to a session id (null if unknown). */
export async function joinByCode(code: string): Promise<{ session_id: string; join_code: string; finished: boolean; reason?: string | null; resumed?: boolean } | null> {
  const res = await fetch(`${base}/join/${encodeURIComponent(code.trim())}`);
  if (!res.ok) return null;
  return await res.json();
}

/** Report links. Markdown opens in the browser; PDF is rendered only when that link is used. */
export function reportUrl(token: string, sessionId: string | null, format: "md" | "pdf"): string {
  const path = sessionId ? `/sessions/${sessionId}/report` : "/report";
  return `${path}?admin_token=${encodeURIComponent(token)}${format === "pdf" ? "&format=pdf" : ""}`;
}

export function participantLink(code: string): string {
  return `${location.origin}/?view=participant&code=${code}`;
}

export async function getQuestionnaire(): Promise<QItem[]> {
  const res = await fetch(`${base}/questionnaire`);
  return (await res.json()).items;
}

export interface LiveSession {
  session_id: string; join_code: string | null; participant_connected: boolean;
  phase: string; turn_count: number; finished: boolean; participant_id?: string | null;
  participant_messages: number; agent_messages: number; max_turns: number;
  questionnaire_answered: number; questionnaire_submitted: boolean; questionnaire_total: number;
  interventions: number;
  device?: string | null;
  progress?: { overall: number; expected_turns_left: number; expected_seconds_left: number } | null;
}

export async function listSessions(token: string): Promise<LiveSession[]> {
  const res = await fetch(`${base}/sessions`, { headers: { "X-Admin-Token": token } });
  if (!res.ok) throw new Error("unauthorized");
  return (await res.json()).sessions;
}

export async function getNodes(token: string) {
  const res = await fetch(`${base}/nodes`, { headers: { "X-Admin-Token": token } });
  if (!res.ok) throw new Error("unauthorized");
  return (await res.json()).nodes;
}

export async function putRouting(token: string, role: string, routes: string[]) {
  const res = await fetch(`${base}/routing`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-Admin-Token": token },
    body: JSON.stringify({ role, routes }),
  });
  return res.ok;
}

export async function postByok(token: string, name: string, kind: string, url: string, apiKey: string) {
  const res = await fetch(`${base}/byok`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Token": token },
    body: JSON.stringify({ name, kind, url: url || null, api_key: apiKey || null }),
  });
  return res.ok;
}

export async function listExperiments(token: string) {
  const res = await fetch(`${base}/experiments`, { headers: { "X-Admin-Token": token } });
  if (!res.ok) return [];
  return (await res.json()).experiments;
}

export async function createExperiment(token: string, name: string) {
  await fetch(`${base}/experiments`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Token": token },
    body: JSON.stringify({ name }),
  });
}

export type ConnState = "connecting" | "open" | "reconnecting" | "closed";

export type Handlers = {
  onEvent: (e: SessionEvent) => void;
  /** Called on every (re)connect, before the server replays the session history. */
  onOpen?: () => void;
  onState?: (s: ConnState) => void;
};

/**
 * WebSocket that reconnects on its own (hotspot blips, laptop sleep). On each reconnect the
 * server replays the whole session, so the caller resets its view in `onOpen`.
 */
class ReconnectingSocket {
  private ws: WebSocket | null = null;
  private stopped = false;
  private attempt = 0;
  private timer: number | undefined;

  constructor(private path: string, private h: Handlers) { this.open(); }

  private open() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.h.onState?.(this.attempt ? "reconnecting" : "connecting");
    const ws = new WebSocket(`${proto}://${location.host}${this.path}`);
    this.ws = ws;
    ws.onopen = () => { this.attempt = 0; this.h.onOpen?.(); this.h.onState?.("open"); };
    ws.onmessage = (ev) => this.h.onEvent(JSON.parse(ev.data));
    ws.onclose = () => {
      if (this.ws !== ws) return;
      if (this.stopped) { this.h.onState?.("closed"); return; }
      this.attempt += 1;
      this.h.onState?.("reconnecting");
      const delay = Math.min(10000, 500 * 2 ** Math.min(this.attempt, 5));
      this.timer = window.setTimeout(() => this.open(), delay);
    };
  }

  send(obj: any) {
    if (this.ws?.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  /** Stop for good (session finished, or the view was closed on purpose). */
  close() { this.stopped = true; window.clearTimeout(this.timer); this.ws?.close(); }
}

export class SessionSocket extends ReconnectingSocket {
  constructor(sessionId: string, token: string | null, h: Handlers, device?: string) {
    const q = token ? `?admin_token=${encodeURIComponent(token)}` : device ? `?device=${device}` : "";
    super(`/sessions/${sessionId}/stream${q}`, h);
  }
  message(text: string) { return this.send({ kind: "message", text }); }
  questionnaire(responses: Record<number, number>) { return this.send({ kind: "questionnaire", responses }); }
  abort() { return this.send({ kind: "abort" }); }
  progress(answered: number) { return this.send({ kind: "questionnaire_progress", answered }); }
  // researcher only (the server ignores these from participant sockets)
  steer(focus: string[] | null, note: string | null) { return this.send({ kind: "steer", focus, note }); }
  finishProfiling() { return this.send({ kind: "finish_profiling" }); }
}

/** Researcher feed: live session list + node health, pushed by the server. */
export class AdminSocket extends ReconnectingSocket {
  constructor(token: string, h: Handlers) {
    super(`/admin/stream?admin_token=${encodeURIComponent(token)}`, h);
  }
}
