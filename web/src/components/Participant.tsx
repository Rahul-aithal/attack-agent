import { useEffect, useRef, useState } from "react";
import { createSession, getQuestionnaire, joinByCode } from "../api";
import type { QItem } from "../types";
import { useSession } from "../useSession";
import { Badge, Button, Input, Panel } from "./ui";

const SCALE = ["Very inaccurate", "Moderately inaccurate", "Neither", "Moderately accurate", "Very accurate"];

// Remembers which sessions this browser already consented to, so a refresh rejoins directly.
const consentKey = (sid: string) => `consented:${sid}`;

function setUrl(params: Record<string, string | null>) {
  const url = new URL(location.href);
  for (const [k, v] of Object.entries(params)) v === null ? url.searchParams.delete(k) : url.searchParams.set(k, v);
  history.replaceState(null, "", url);
}

export function Participant() {
  const { state, conn, connect, sendMessage, sendQuestionnaire, abort } = useSession();
  const params = new URLSearchParams(location.search);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [joinCode, setJoinCode] = useState<string>(params.get("code") || "");
  const [joinError, setJoinError] = useState("");
  const [draft, setDraft] = useState("");
  const [items, setItems] = useState<QItem[]>([]);
  const [responses, setResponses] = useState<Record<number, number>>({});
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { getQuestionnaire().then(setItems).catch(() => {}); }, []);
  // Instant scroll while tokens stream in; a smooth scroll restarted on every token makes the chat jank.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: state.streaming ? "auto" : "smooth" });
  }, [state.chat, state.streaming]);

  // Page refreshed mid-session (?session=… and consent already given here): rejoin straight away.
  useEffect(() => {
    const sid = params.get("session");
    const code = sid && localStorage.getItem(consentKey(sid));
    if (sid && code !== null) enter(sid, code || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function enter(sid: string, code: string) {
    localStorage.setItem(consentKey(sid), code);
    setSessionId(sid);
    setJoinCode(code);
    setUrl({ view: "participant", session: sid, code: null });
    connect(sid, null);
  }

  async function join() {
    setJoinError("");
    const found = await joinByCode(joinCode);
    if (!found) { setJoinError("No session with that code — check it with the researcher."); return; }
    if (found.finished) { setJoinError("That session has already finished."); return; }
    enter(found.session_id, found.join_code);
  }

  async function start() {
    const created = await createSession();
    enter(created.session_id, created.join_code);
  }

  function leave() {
    if (sessionId) localStorage.removeItem(consentKey(sessionId));
    setUrl({ session: null });
    location.reload();
  }

  if (!sessionId) {
    return (
      <div className="max-w-2xl mx-auto mt-10">
        <Panel title="Consent to participate">
          <div className="text-sm text-slate-300 space-y-3">
            <p>This is a <b>controlled academic research simulation</b> (Final Year Project).</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>We chat casually; the conversation is analysed to estimate personality traits.</li>
              <li>A <b>harmless simulated message</b> may follow — no real credentials, links, or payment details are ever involved.</li>
              <li>A short personality questionnaire comes afterwards.</li>
              <li>You can stop at any time. All data stays on the study's local machines.</li>
            </ul>
            <p className="text-slate-400">By continuing you consent to participate.</p>
          </div>
          <form className="mt-4 flex gap-2 items-center" onSubmit={(e) => { e.preventDefault(); if (joinCode.trim()) join(); }}>
            <Input value={joinCode} onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
              placeholder="Session code from the researcher, e.g. K7M2QX" className="font-mono tracking-widest" />
            <Button type="submit" disabled={!joinCode.trim()}>I consent — join</Button>
          </form>
          {joinError && <div className="text-xs text-rose-400 mt-2">{joinError}</div>}
          <div className="mt-3 text-xs text-slate-500">
            No code? <button className="underline hover:text-slate-300" onClick={start}>I consent — start a new session</button>
          </div>
        </Panel>
      </div>
    );
  }

  const inQuestionnaire = state.awaitQuestionnaire;
  const done = state.phase === "complete" || !!state.debrief;
  const aborted = state.phase === "aborted";
  const lost = state.error === "session not found";
  const offline = conn !== "open";
  // The agent is working (reading signals / generating) until it asks for the next message.
  const thinking = !state.awaiting && !done && !inQuestionnaire && !aborted;

  return (
    <div className="max-w-2xl mx-auto mt-6 space-y-4">
      <div className="flex items-center justify-between">
        <Badge color="blue">session {joinCode || sessionId.slice(-6)}</Badge>
        <Badge color="slate">phase: {state.phase || "starting"}</Badge>
      </div>

      {conn === "reconnecting" && !done && !aborted && (
        <div className="rounded-lg border border-amber-600 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          Connection lost — reconnecting… your chat is kept, just wait a moment.
        </div>
      )}

      {lost && (
        <Panel title="Session not available">
          <p className="text-sm text-slate-300">This session no longer exists (the server may have restarted). Please ask the researcher for a new code.</p>
          <div className="mt-3"><Button onClick={leave}>Back</Button></div>
        </Panel>
      )}

      {aborted && !lost && (
        <Panel title="Session ended">
          <p className="text-sm text-slate-300">You left the study. Nothing more will be recorded. Thank you for your time.</p>
          <div className="mt-3"><Button variant="ghost" onClick={leave}>Back to start</Button></div>
        </Panel>
      )}

      {!inQuestionnaire && !done && !aborted && !lost && (
        <Panel>
          <div className="h-[55vh] overflow-y-auto space-y-3 pr-1">
            {state.chat.map((m, i) => (
              <Bubble key={i} who={m.who} text={m.text} />
            ))}
            {state.streaming && <Bubble who="agent" text={state.streaming} />}
            {thinking && !state.streaming && <Typing />}
            <div ref={endRef} />
          </div>
          <form
            className="mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (draft.trim() && !thinking && sendMessage(draft.trim())) setDraft("");
            }}
          >
            <Input value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder={offline ? "Reconnecting…" : thinking ? "Waiting for reply…" : "Type your reply…"} autoFocus />
            <Button type="submit" disabled={thinking || offline}>Send</Button>
            <Button variant="ghost" onClick={() => { if (confirm("Leave the study? Your session will end.")) abort(); }}>Quit</Button>
          </form>
        </Panel>
      )}

      {inQuestionnaire && (
        <Panel title="A quick personality questionnaire">
          <p className="text-sm text-slate-400 mb-3">Rate how accurately each statement describes you.</p>
          <div className="max-h-[60vh] overflow-y-auto space-y-3">
            {items.map((it) => (
              <div key={it.id} className="border-b border-line pb-2">
                <div className="text-sm mb-1">I {it.text}</div>
                <div className="flex gap-1">
                  {SCALE.map((lbl, idx) => {
                    const v = idx + 1;
                    const on = responses[it.id] === v;
                    return (
                      <button key={v} title={lbl} onClick={() => setResponses({ ...responses, [it.id]: v })}
                        className={`flex-1 py-1 rounded text-xs border ${on ? "bg-accent text-white border-accent" : "bg-ink border-line text-slate-400"}`}>
                        {v}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4">
            <Button onClick={() => sendQuestionnaire(responses)} disabled={offline || items.length === 0 || Object.keys(responses).length < items.length}>
              Submit ({Object.keys(responses).length}/{items.length})
            </Button>
          </div>
        </Panel>
      )}

      {done && (
        <Panel title="Thank you">
          <p className="text-sm text-slate-300">{state.debrief}</p>
        </Panel>
      )}
    </div>
  );
}

function Typing() {
  return (
    <div className="flex justify-start">
      <div className="rounded-2xl px-3 py-2 text-sm bg-panel2 text-slate-400 flex gap-1 items-center">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" />
        <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:150ms]" />
        <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:300ms]" />
      </div>
    </div>
  );
}

function Bubble({ who, text }: { who: string; text: string }) {
  if (who === "scenario")
    return (
      <div className="border border-rose-700 bg-rose-950/40 rounded-lg p-3">
        <div className="text-xs text-rose-300 mb-1">Incoming message</div>
        <div className="text-sm whitespace-pre-wrap">{text}</div>
      </div>
    );
  const me = who === "participant";
  return (
    <div className={`flex ${me ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${me ? "bg-accent text-white" : "bg-panel2 text-slate-100"}`}>
        {text}
      </div>
    </div>
  );
}
