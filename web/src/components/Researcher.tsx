import { useEffect, useRef, useState } from "react";
import { AdminSocket, createSession, createExperiment, listExperiments, participantLink, postByok, putRouting, reportUrl } from "../api";
import type { ConnState, LiveSession } from "../api";
import type { SessionState } from "../useSession";
import { useSession } from "../useSession";
import { Convergence, TraitRadar } from "./charts";
import { MachinesPanel, ModelActivity } from "./Monitor";
import { Memory, Steering, Transcript } from "./Steering";
import { PreviousSessions } from "./History";
import { PhaseStepper, ProfilingProgress, Tabs, roughTime } from "./SessionView";
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

/** Live session list + node health pushed by the server over /admin/stream. */
function useAdminFeed(token: string) {
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  const [nodes, setNodes] = useState<any[]>([]);
  const [machines, setMachines] = useState<any[]>([]);
  const [llm, setLlm] = useState<{ active: any[]; recent: any[]; totals: any[] }>({ active: [], recent: [], totals: [] });
  const seen = useRef<Record<string, { at: string; rx: number }>>({});
  const [conn, setConn] = useState<ConnState>("closed");
  const [denied, setDenied] = useState(false);
  const sock = useRef<AdminSocket | null>(null);
  useEffect(() => {
    setDenied(false);
    if (!token) return;
    const s = new AdminSocket(token, {
      onState: setConn,
      onEvent: (e) => {
        if (e.type === "sessions") setSessions(e.sessions);
        else if (e.type === "nodes") setNodes(e.nodes);
        else if (e.type === "machines") {
          const rx = Date.now();
          setMachines(e.machines.map((m: any) => {
            const prev = seen.current[m.name];
            if (!prev || prev.at !== m.received_at) seen.current[m.name] = { at: m.received_at, rx };
            return { ...m, _rx: seen.current[m.name].rx };
          }));
        }
        else if (e.type === "llm") {
          const rx = Date.now();
          setLlm({ ...e, active: e.active.map((c: any) => ({ ...c, _rx: rx })) } as any);
        }
        else if (e.type === "error") { setDenied(true); s.close(); }
      },
    });
    sock.current = s;
    return () => s.close();
  }, [token]);
  return { sessions, nodes, machines, llm, conn, denied };
}

function LiveSessions({ rows, denied, onAttach, token }: { rows: LiveSession[]; denied: boolean; onAttach: (id: string, code?: string | null) => void; token: string }) {
  if (denied) return <div className="text-xs text-rose-400">token not accepted (copy it again from the server terminal; it changes on every restart)</div>;
  if (rows.length === 0) return <div className="text-xs text-slate-500">no sessions yet</div>;
  return (
    <div className="space-y-1">
      {rows.map((r) => (
        <div key={r.session_id} className="flex items-center gap-x-2 gap-y-1 flex-wrap text-sm border-b border-line/60 py-1.5">
          <span className="font-mono text-xs tracking-widest">{r.join_code ?? r.session_id.slice(-6)}</span>
          <Badge color={r.finished ? "slate" : "green"}>{r.finished ? "done" : r.phase}</Badge>
          <span className="text-xs text-slate-400" title="participant chat replies / max">💬 {r.participant_messages}/{r.max_turns}</span>
          {r.interventions > 0 && <Badge color="amber">steered ×{r.interventions}</Badge>}
          {r.progress && r.phase === "profiling" && (
            <span className="flex items-center gap-1.5 text-xs text-slate-400" title="progress to the twin (expected time)">
              <span className="w-16 h-1.5 rounded-full bg-ink overflow-hidden inline-block">
                <span className="block h-full bg-accent" style={{ width: `${Math.round(r.progress.overall * 100)}%` }} />
              </span>
              {Math.round(r.progress.overall * 100)}%
              {r.progress.expected_turns_left > 0 && <> · ~{r.progress.expected_turns_left} more, {roughTime(r.progress.expected_seconds_left)}</>}
            </span>
          )}
          <span className={`text-xs ${r.questionnaire_submitted ? "text-emerald-400" : "text-slate-400"}`} title="questionnaire answered">📝 {r.questionnaire_answered}/{r.questionnaire_total}</span>
          {!r.finished && (
            <span className={`text-xs ${r.participant_connected ? "text-emerald-400" : "text-slate-500"}`}>
              {r.participant_connected ? "● participant online" : "○ waiting for participant"}
            </span>
          )}
          {r.finished && <ReportLinks token={token} sessionId={r.session_id} label="report" />}
          <span className="ml-auto"><Button variant="ghost" onClick={() => onAttach(r.session_id, r.join_code)}>{r.finished ? "Open" : "Watch"}</Button></span>
        </div>
      ))}
    </div>
  );
}

function ReportLinks({ token, sessionId, label }: { token: string; sessionId: string | null; label: string }) {
  const cls = "text-xs underline text-slate-300 hover:text-white";
  return (
    <span className="text-xs text-slate-400 whitespace-nowrap">
      {label}:{" "}
      <a className={cls} href={reportUrl(token, sessionId, "md")} target="_blank" rel="noreferrer">Markdown</a>
      {" · "}
      <a className={cls} href={reportUrl(token, sessionId, "pdf")} title="converts to PDF on the server">PDF</a>
    </span>
  );
}

function NodeStatus({ nodes }: { nodes: any[] }) {
  return (
    <Panel title="Node status">
      <div className="space-y-2 text-sm">
        {nodes.map((n) => (
          <div key={n.node} className="space-y-0.5">
            <div className="flex items-center justify-between">
              <span>{n.node} <span className="text-slate-500 text-xs">({n.kind})</span></span>
              <Badge color={!n.healthy ? "red" : n.models_missing?.length ? "amber" : "green"}>
                {!n.healthy ? "down" : n.models_missing?.length ? "model missing" : "up"}
              </Badge>
            </div>
            {!!n.roles?.length && <div className="text-[11px] text-slate-500">main for: {n.roles.join(", ")}</div>}
            {!!n.models_missing?.length && (
              <div className="text-[11px] text-amber-300">not installed: {n.models_missing.join(", ")} → run <code>ollama pull {n.models_missing[0]}</code> on {n.node}</div>
            )}
          </div>
        ))}
        {nodes.length === 0 && <div className="text-slate-500">no nodes / unauthorized</div>}
      </div>
    </Panel>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel px-2 py-2">
      <div className="text-lg font-semibold font-mono">{value}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
      {sub && <div className="text-[10px] text-slate-500">{sub}</div>}
    </div>
  );
}

function JoinCard({ code }: { code: string }) {
  const link = participantLink(code);
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-lg border border-accent/60 bg-panel px-4 py-3 text-sm">
      <div className="text-xs text-slate-400">Give the participant this code (Participant → enter code) or link</div>
      <div className="flex items-center gap-3 mt-1">
        <span className="font-mono text-2xl tracking-[0.3em]">{code}</span>
        <Button variant="ghost" onClick={() => { navigator.clipboard?.writeText(link).then(() => setCopied(true)); }}>
          {copied ? "link copied" : "copy link"}
        </Button>
      </div>
      <div className="text-xs text-slate-500 mt-1 break-all">{link}</div>
    </div>
  );
}

export function Researcher() {
  const { state, connect, disconnect, reset, steer, finishProfiling } = useSession();
  const [token, setToken] = useState(localStorage.getItem("adminToken") || "");
  const [sessionId, setSessionId] = useState(new URLSearchParams(location.search).get("session") || "");
  const [attached, setAttached] = useState(false);
  const [joinCode, setJoinCode] = useState<string | null>(null);
  const [experiments, setExperiments] = useState<any[]>([]);
  const feed = useAdminFeed(token);
  const nodes = feed.nodes;
  const watched = feed.sessions.find((r) => r.session_id === sessionId);

  // Node status arrives over the feed; routing/BYOK changes show up on its next health check.
  const refreshNodes = () => {};
  const refreshExp = () => listExperiments(token).then(setExperiments).catch(() => setExperiments([]));

  useEffect(() => { if (attached) refreshExp(); }, [attached]);
  useEffect(() => { if (token) localStorage.setItem("adminToken", token); }, [token]);

  async function newForParticipant() {
    const created = await createSession();
    attach(created.session_id, created.join_code);
  }

  function attach(id: string, code?: string | null) {
    localStorage.setItem("adminToken", token);
    setSessionId(id);
    setJoinCode(code ?? null);
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

  const authed = !!token && !feed.denied;

  if (!attached) {
    return (
      <div className="max-w-6xl mx-auto mt-4 sm:mt-6 space-y-4">
        {/* top bar: token + the two main actions */}
        <div className="rounded-xl border border-line bg-panel px-4 py-3 flex flex-col lg:flex-row lg:items-center gap-3">
          <div className="flex-1 min-w-0">
            <label className="text-xs text-slate-400">Admin token</label>
            <Input value={token} onChange={(e) => setToken(e.target.value)} placeholder="printed in the server terminal at startup" className="mt-1" />
            {feed.denied && <div className="text-xs text-rose-400 mt-1">Token not accepted — copy it again from the server terminal (it changes on restart unless fixed in .env).</div>}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs ${feed.conn === "open" ? "text-emerald-400" : "text-slate-500"}`}>{feed.conn === "open" ? "● live" : token ? "○ connecting…" : ""}</span>
            <Button onClick={newForParticipant} disabled={!authed}>+ New session</Button>
            {authed && <ReportLinks token={token} sessionId={null} label="Study report" />}
          </div>
        </div>

        {authed && (
          <Tabs tabs={[
            {
              key: "sessions", label: "Sessions", badge: feed.sessions.filter((r) => !r.finished).length,
              content: (
                <>
                  <Panel title="Live now">
                    <LiveSessions rows={feed.sessions} denied={feed.denied} onAttach={attach} token={token} />
                  </Panel>
                  <PreviousSessions token={token} onOpen={attach}
                    refreshKey={feed.sessions.map((r) => `${r.session_id}:${r.phase}:${r.finished}`).join(",")} />
                </>
              ),
            },
            {
              key: "system", label: "Machines & models",
              badge: feed.nodes.filter((n) => !n.healthy || n.models_missing?.length).length || undefined,
              content: (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="space-y-4"><NodeStatus nodes={feed.nodes} /><ModelActivity llm={feed.llm} /></div>
                  <MachinesPanel machines={feed.machines} />
                </div>
              ),
            },
            {
              key: "settings", label: "Settings",
              content: (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <Settings token={token} onChange={refreshNodes} />
                  <Experiments token={token} experiments={experiments} onChange={refreshExp} />
                </div>
              ),
            },
          ]} />
        )}
      </div>
    );
  }

  const code = joinCode ?? watched?.join_code ?? sessionId.slice(-6);
  const waiting = watched?.phase === "waiting";
  return (
    <div className="max-w-6xl mx-auto mt-3 sm:mt-5 space-y-4">
      {/* header: which session, who is connected, where it is */}
      <div className="rounded-xl border border-line bg-panel px-4 py-3 space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="ghost" className="!px-2.5" onClick={detach}>←</Button>
          <span className="font-mono text-xl tracking-[0.25em]">{code}</span>
          {watched && !watched.finished && (
            <Badge color={watched.participant_connected ? "green" : "red"}>
              {watched.participant_connected ? "● participant online" : "○ participant offline"}
            </Badge>
          )}
          {watched?.device && <Badge color="slate">{watched.device}</Badge>}
          {state.interventions.length > 0 && <Badge color="amber">steered ×{state.interventions.length}</Badge>}
          <span className="ml-auto">{watched?.finished && <ReportLinks token={token} sessionId={sessionId} label="Report" />}</span>
        </div>
        <PhaseStepper phase={waiting ? "" : state.phase} waiting={waiting} />
        {waiting
          ? <div className="text-sm text-slate-400">Waiting for the participant to join — the session starts when they connect.</div>
          : <ActivityBar s={state} />}
      </div>

      {code && !watched?.participant_connected && (watched?.turn_count ?? 0) === 0 && <JoinCard code={code} />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2"><ProfilingProgress s={state} /></div>
        {watched && (
          <div className="grid grid-cols-3 lg:grid-cols-1 gap-2 text-center lg:text-left">
            <Stat label="participant replies" value={`${watched.participant_messages}`} />
            <Stat label="agent messages" value={`${watched.agent_messages}`} />
            <Stat label="questionnaire" value={`${watched.questionnaire_answered}/${watched.questionnaire_total}`}
              sub={watched.questionnaire_submitted ? "submitted" : state.phase === "questionnaire" ? "in progress" : "not started"} />
          </div>
        )}
      </div>

      <Tabs tabs={[
        {
          key: "chat", label: "Conversation", badge: state.chat.length,
          content: (
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
              <div className="lg:col-span-3 space-y-4"><Transcript s={state} /><Memory s={state} /></div>
              <div className="lg:col-span-2 space-y-4"><Steering s={state} steer={steer} finishProfiling={finishProfiling} /></div>
            </div>
          ),
        },
        {
          key: "profile", label: "Personality",
          content: (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Panel title="Big Five — inferred vs self-report"><TraitRadar traits={state.traits} selfReport={state.selfReport} /></Panel>
              <Panel title="How the scores settled, reply by reply">
                {state.convergence.length > 1 ? <Convergence history={state.convergence} />
                  : <div className="text-sm text-slate-500 py-8 text-center">appears after two replies</div>}
              </Panel>
              <Panel title="Evidence (latest first)" className="lg:col-span-2">
                <div className="max-h-60 overflow-y-auto text-xs grid grid-cols-1 sm:grid-cols-2 gap-x-6">
                  {state.evidence.map((e, i) => (
                    <div key={i} className="flex justify-between border-b border-line/60 py-1">
                      <span className="text-slate-300 capitalize">{e.trait}</span>
                      <span className={e.delta >= 0 ? "text-emerald-400" : "text-rose-400"}>{e.signal}</span>
                    </div>
                  ))}
                  {state.evidence.length === 0 && <div className="text-slate-500">no evidence yet</div>}
                </div>
              </Panel>
            </div>
          ),
        },
        {
          key: "twin", label: "Twin & outcome", badge: state.twin ? "✓" : undefined,
          content: (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2"><TwinPanel s={state} /></div>
              <Panel title="Decision trace">
                <div className="text-xs font-mono text-slate-400 max-h-80 overflow-y-auto space-y-1">
                  {state.trace.slice(-40).map((t, i) => <div key={i}>{t}</div>)}
                </div>
              </Panel>
            </div>
          ),
        },
        {
          key: "system", label: "Models & machines",
          content: (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="space-y-4"><ModelActivity llm={feed.llm} sessionFilter={sessionId} /><NodeStatus nodes={nodes} /></div>
              <MachinesPanel machines={feed.machines} />
            </div>
          ),
        },
      ]} />
    </div>
  );
}

function TwinPanel({ s }: { s: SessionState }) {
  return (
    <Panel title="Twin prediction vs real outcome">
      {s.twin ? (
        <div className="text-sm space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-line p-3">
              <div className="text-xs text-slate-400">Twin predicted</div>
              <div className="text-lg font-semibold">{s.twin.predicted_outcome}</div>
              <div className="text-xs text-slate-500">agreement {Math.round(s.twin.confidence * 100)}%</div>
            </div>
            <div className="rounded-lg border border-line p-3">
              <div className="text-xs text-slate-400">Real outcome</div>
              <div className="text-lg font-semibold">{s.outcome?.real_outcome ?? "…"}</div>
              {s.outcome && (s.outcome.match_flag == null
                ? <Badge color="slate">no match score</Badge>
                : <Badge color={s.outcome.match_flag ? "green" : "red"}>{s.outcome.match_flag ? "MATCH" : "MISS"}</Badge>)}
            </div>
          </div>
          {s.twin.source && s.twin.source !== "model" && <Badge color="red">⚠ {s.twin.source}: not a real prediction</Badge>}
          {s.outcome?.judged_by === "rules" && <Badge color="amber">⚠ outcome judged by keyword rules</Badge>}
          <div className="text-slate-400 text-xs">{s.twin.reasoning}</div>
          {s.outcome?.rationale && <div className="text-slate-400 text-xs">Judge: {s.outcome.rationale}</div>}
          {!!s.twin.samples?.length && (
            <details className="text-xs" open>
              <summary className="cursor-pointer text-slate-300">What the twin simulated ({s.twin.samples.length} runs)</summary>
              <div className="mt-2 space-y-2">
                {s.twin.samples.map((x, i) => (
                  <div key={i} className="border-l-2 border-line pl-2">
                    <div className="text-slate-200 whitespace-pre-wrap">“{x.reply}”</div>
                    <div className="text-slate-500">→ {x.outcome} ({x.confidence}){x.judged_by !== "model" && " · keyword rules"} — {x.reasoning}</div>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      ) : s.phase === "twin_handoff"
        ? <div className="text-sm text-amber-300 flex items-center gap-2"><span className="w-3 h-3 rounded-full border-2 border-amber-400 border-t-transparent animate-spin" />twin is running…</div>
        : <div className="text-sm text-slate-500">Starts when profiling finishes — see “Progress to the twin” above.</div>}
    </Panel>
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
