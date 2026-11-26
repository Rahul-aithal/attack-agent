import type { QItem, SessionEvent } from "./types";

const base = ""; // same origin (served by FastAPI) or proxied in dev

export async function createSession(participantId?: string, experimentId?: string): Promise<string> {
  const res = await fetch(`${base}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ participant_id: participantId, experiment_id: experimentId, consent: true }),
  });
  if (!res.ok) throw new Error(`createSession failed: ${res.status}`);
  return (await res.json()).session_id;
}

export async function getQuestionnaire(): Promise<QItem[]> {
  const res = await fetch(`${base}/questionnaire`);
  return (await res.json()).items;
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

export type Handlers = {
  onEvent: (e: SessionEvent) => void;
  onOpen?: () => void;
  onClose?: () => void;
};

export class SessionSocket {
  ws: WebSocket;
  constructor(sessionId: string, token: string | null, h: Handlers) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const q = token ? `?admin_token=${encodeURIComponent(token)}` : "";
    this.ws = new WebSocket(`${proto}://${location.host}/sessions/${sessionId}/stream${q}`);
    this.ws.onmessage = (ev) => h.onEvent(JSON.parse(ev.data));
    this.ws.onopen = () => h.onOpen?.();
    this.ws.onclose = () => h.onClose?.();
  }
  send(obj: any) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }
  message(text: string) { this.send({ kind: "message", text }); }
  questionnaire(responses: Record<number, number>) { this.send({ kind: "questionnaire", responses }); }
  abort() { this.send({ kind: "abort" }); }
  close() { this.ws.close(); }
}
