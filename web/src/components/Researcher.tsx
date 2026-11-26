import { useEffect, useState } from "react";
import { createSession, createExperiment, getNodes, listExperiments, listSessions, postByok, putRouting } from "../api";
import type { LiveSession } from "../api";
import type { SessionState } from "../useSession";
import { useSession } from "../useSession";
import { Convergence, TraitRadar } from "./charts";
import { Badge, Button, Input, Panel } from "./ui";

const ROLES = ["agent", "extractor", "twin", "judge", "sim_participant"];

// What the engine is doing right now, derived from the phase and the events seen so far.
function activity(s: SessionState): { text: string; busy: boolean; who?: string } {
  switch (s.phase) {
    case "":
    case "consent":
      return { text: "starting session", busy: true, who: "agent" };
    case "profiling":
      return s.awaiting === "profiling"
        ? { text: `waiting for participant (turn ${s.convergence.length + 1})`, busy: false }
        : { text: "reading signals + writing reply", busy: true, who: "extractor → agent" };
    case "twin_handoff":
      return s.twin
        ? { text: `twin predicted: ${s.twin.predicted_outcome}`, busy: false }
        : { text: "twin is running — drafting scenario and predicting the outcome", busy: true, who: "agent → twin" };
    case "simulation":
      return s.awaiting === "scenario"
        ? { text: "scenario sent — waiting for participant's response", busy: false }
        : { text: "sending scenario message", busy: true, who: "agent" };
    case "evaluation":
      return { text: "judging the real outcome", busy: true, who: "judge" };
    case "questionnaire":
      return { text: "participant is filling in the questionnaire", busy: false };
    case "debrief":
    case "complete":
      return { text: "session complete", busy: false };
    case "aborted":
      return { text: "session aborted", busy: false };
    default:
      return { text: s.phase, busy: false };
  }
}

function ActivityBar({ s }: { s: SessionState }) {
  const a = activity(s);
  return (
    <div className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-sm ${a.busy ? "border-amber-600 bg-amber-950/30" : "border-line bg-panel"}`}>
      {a.busy
        ? <span className="w-3 h-3 rounded-full border-2 border-amber-400 border-t-transparent animate-spin" />
        : <span className="w-3 h-3 rounded-full bg-emerald-500" />}
      <span>{a.text}</span>
      {a.who && <span className="ml-auto text-xs text-slate-400 font-mono">{a.who}</span>}
    </div>
  );
}

function LiveSessions({ token, onAttach }: { token: string; onAttach: (id: string) => void }) {
  const [rows, setRows] = useState<LiveSession[] | null>(null);
  useEffect(() => {
    if (!token) { setRows(null); return; }
    const load = () => listSessions(token).then(setRows).catch(() => setRows(null));
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [token]);
  if (!token) return null;
  if (rows === null) return <div className="text-xs text-rose-400">token not accepted (check the server log)</div>;
  if (rows.length === 0) return <div className="text-xs text-slate-500">no sessions yet — start one on the participant device</div>;
  return (
    <div className="space-y-1">
      {rows.map((r) => (
        <div key={r.session_id} className="flex items-center gap-2 text-sm border-b border-line/60 py-1">
          <span className="font-mono text-xs">{r.session_id.slice(-6)}</span>
          <Badge color={r.finished ? "slate" : "green"}>{r.finished ? "done" : r.phase}</Badge>
          <span className="text-xs text-slate-500">turn {r.turn_count}</span>
          <span className="ml-auto"><Button variant="ghost" onClick={() => onAttach(r.session_id)}>Watch</Button></span>
        </div>
      ))}
    </div>
  );
}

export function Researcher() {
  const { state, connect, disconnect, reset } = useSession();
  const [token, setToken] = useState(localStorage.getItem("adminToken") || "");
  const [sessionId, setSessionId] = useState(new URLSearchParams(location.search).get("session") || "");
  const [attached, setAttached] = useState(false);
  const [nodes, setNodes] = useState<any[]>([]);
  const [experiments, setExperiments] = useState<any[]>([]);

  const refreshNodes = () => getNodes(token).then(setNodes).catch(() => setNodes([]));
  const refreshExp = () => listExperiments(token).then(setExperiments).catch(() => setExperiments([]));

  useEffect(() => {
    if (attached) { refreshNodes(); refreshExp(); const t = setInterval(refreshNodes, 8000); return () => clearInterval(t); }
  }, [attached]);

  function attach(id: string) {
    localStorage.setItem("adminToken", token);
    setSessionId(id);
    setAttached(true);
    reset();
    connect(id, token);
    // Remember the watched session in the URL so a reload or a shared link reopens it.
    const url = new URL(location.href);
    url.searchParams.set("view", "researcher");
    url.searchParams.set("session", id);
    history.replaceState(null, "", url);
  }

  function detach() {
    disconnect();
    reset();
    setAttached(false);
    const url = new URL(location.href);
    url.searchParams.delete("session");
    history.replaceState(null, "", url);
  }

  // Opened with ?session=<id> and a saved token: attach straight away.
  useEffect(() => {
    if (sessionId && token && !attached) attach(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!attached) {
    return (
      <div className="max-w-xl mx-auto mt-10 space-y-4">
        <Panel title="Researcher / presenter access">
          <label className="text-xs text-slate-400">Admin token</label>
          <Input value={token} onChange={(e) => setToken(e.target.value)} placeholder="printed in server logs at startup" className="mt-1 mb-3" />
          <label className="text-xs text-slate-400">Live sessions (refreshes every few seconds)</label>
          <div className="mt-1 mb-3"><LiveSessions token={token} onAttach={attach} /></div>
          <label className="text-xs text-slate-400">Or attach by session id</label>
          <div className="flex gap-2 mt-1">
            <Input value={sessionId} onChange={(e) => setSessionId(e.target.value)} placeholder="sess_…" />
            <Button onClick={() => sessionId && attach(sessionId)} disabled={!token || !sessionId}>Attach</Button>
          </div>
          <div className="text-center text-xs text-slate-500 my-2">— or —</div>
          <Button variant="ghost" onClick={async () => attach(await createSession())} disabled={!token}>
            Create a new session to drive myself
          </Button>
        </Panel>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 space-y-4">
        <div className="flex items-center gap-2">
          <Badge color="blue">session {sessionId.slice(-6)}</Badge>
          <Button variant="ghost" onClick={detach}>← all sessions</Button>
          <Badge color="slate">phase: {state.phase || "—"}</Badge>
          <Badge color="amber">stability {state.stability.toFixed(2)}</Badge>
          <Badge color="amber">avg conf {state.avgConfidence.toFixed(2)}</Badge>
        </div>
        <ActivityBar s={state} />
        <Panel title="Big Five — inferred vs self-report">
          <TraitRadar traits={state.traits} selfReport={state.selfReport} />
        </Panel>
        <Panel title="Per-turn convergence">
          {state.convergence.length > 1 ? <Convergence history={state.convergence} />
            : <div className="text-sm text-slate-500 py-8 text-center">waiting for turns…</div>}
        </Panel>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Panel title="Twin prediction vs outcome">
            {state.twin ? (
              <div className="text-sm space-y-2">
                <div>twin predicts: <b>{state.twin.predicted_outcome}</b> <span className="text-slate-500">({state.twin.confidence})</span></div>
                <div className="text-slate-400 text-xs">{state.twin.reasoning}</div>
                {state.outcome && (
                  <div className="mt-2 pt-2 border-t border-line">
                    real outcome: <b>{state.outcome.real_outcome}</b>{" "}
                    <Badge color={state.outcome.match_flag ? "green" : "red"}>
                      {state.outcome.match_flag ? "MATCH" : "MISS"}
                    </Badge>
                  </div>
                )}
              </div>
            ) : state.phase === "twin_handoff"
              ? <div className="text-sm text-amber-300 flex items-center gap-2"><span className="w-3 h-3 rounded-full border-2 border-amber-400 border-t-transparent animate-spin" />twin is running…</div>
              : <div className="text-sm text-slate-500">starts after profiling (≥ 8 participant messages, or once confident)</div>}
          </Panel>
          <Panel title="ReAct trace">
            <div className="text-xs font-mono text-slate-400 max-h-40 overflow-y-auto space-y-1">
              {state.trace.slice(-20).map((t, i) => <div key={i}>{t}</div>)}
            </div>
          </Panel>
        </div>
      </div>

      <div className="space-y-4">
        <Panel title="Evidence feed">
          <div className="max-h-48 overflow-y-auto text-xs space-y-1">
            {state.evidence.map((e, i) => (
              <div key={i} className="flex justify-between border-b border-line/60 py-1">
                <span className="text-slate-300">{e.trait}</span>
                <span className={e.delta >= 0 ? "text-emerald-400" : "text-rose-400"}>{e.signal}</span>
              </div>
            ))}
            {state.evidence.length === 0 && <div className="text-slate-500">no evidence yet</div>}
          </div>
        </Panel>

        <Panel title="Node status">
          <div className="space-y-2 text-sm">
            {nodes.map((n) => (
              <div key={n.node} className="flex items-center justify-between">
                <span>{n.node} <span className="text-slate-500 text-xs">({n.kind})</span></span>
                <Badge color={n.healthy ? "green" : "red"}>{n.healthy ? "up" : "down"}</Badge>
              </div>
            ))}
            {nodes.length === 0 && <div className="text-slate-500">no nodes / unauthorized</div>}
          </div>
        </Panel>

        <Settings token={token} onChange={refreshNodes} />
        <Experiments token={token} experiments={experiments} onChange={refreshExp} />
      </div>
    </div>
  );
}

function Settings({ token, onChange }: { token: string; onChange: () => void }) {
  const [role, setRole] = useState("agent");
  const [routes, setRoutes] = useState("");
  const [byok, setByok] = useState({ name: "", kind: "openai", url: "", key: "" });
  return (
    <Panel title="Routing & BYOK">
      <div className="text-xs text-slate-400 mb-1">Set role routing (comma-separated node/model)</div>
      <select value={role} onChange={(e) => setRole(e.target.value)} className="bg-ink border border-line rounded px-2 py-1 text-sm w-full mb-2">
        {ROLES.map((r) => <option key={r}>{r}</option>)}
      </select>
      <Input value={routes} onChange={(e) => setRoutes(e.target.value)} placeholder="laptop16/llama3.1:8b, host/llama3.2:3b" />
      <div className="mt-2 mb-4">
        <Button variant="ghost" onClick={async () => { await putRouting(token, role, routes.split(",").map((s) => s.trim()).filter(Boolean)); onChange(); }}>
          Apply routing
        </Button>
      </div>
      <div className="text-xs text-slate-400 mb-1">Add a BYOK node (key kept in memory only)</div>
      <div className="grid grid-cols-2 gap-2">
        <Input placeholder="name" value={byok.name} onChange={(e) => setByok({ ...byok, name: e.target.value })} />
        <select value={byok.kind} onChange={(e) => setByok({ ...byok, kind: e.target.value })} className="bg-ink border border-line rounded px-2 text-sm">
          {["openai", "anthropic", "gemini", "openai_compat", "groq", "openrouter", "ollama"].map((k) => <option key={k}>{k}</option>)}
        </select>
        <Input placeholder="url (optional)" value={byok.url} onChange={(e) => setByok({ ...byok, url: e.target.value })} />
        <Input placeholder="api key" type="password" value={byok.key} onChange={(e) => setByok({ ...byok, key: e.target.value })} />
      </div>
      <div className="mt-2">
        <Button variant="ghost" onClick={async () => { await postByok(token, byok.name, byok.kind, byok.url, byok.key); setByok({ ...byok, key: "" }); onChange(); }}>
          Add node
        </Button>
      </div>
    </Panel>
  );
}

function Experiments({ token, experiments, onChange }: { token: string; experiments: any[]; onChange: () => void }) {
  const [name, setName] = useState("");
  return (
    <Panel title="Experiments">
      <div className="flex gap-2 mb-2">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="experiment name" />
        <Button variant="ghost" onClick={async () => { if (name) { await createExperiment(token, name); setName(""); onChange(); } }}>Add</Button>
      </div>
      <div className="text-xs space-y-1">
        {experiments.map((e) => (
          <div key={e.id} className="flex justify-between"><span>{e.name}</span><span className="text-slate-500">{e.sessions} sessions</span></div>
        ))}
        {experiments.length === 0 && <div className="text-slate-500">none yet</div>}
      </div>
    </Panel>
  );
}
