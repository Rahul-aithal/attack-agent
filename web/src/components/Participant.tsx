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
  const { state, conn, connect, sendMessage, sendQuestionnaire, sendProgress, abort } = useSession();
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
      <div className="max-w-2xl mx-auto mt-4 sm:mt-10">
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
          <form className="mt-4 flex flex-col sm:flex-row gap-2 sm:items-center" onSubmit={(e) => { e.preventDefault(); if (joinCode.trim()) join(); }}>
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
  const answeredCount = Object.keys(responses).length;
  function answer(id: number, v: number) {
    const next = { ...responses, [id]: v };
    setResponses(next);
    sendProgress(Object.keys(next).length); // live "n/50" on the researcher dashboard
  }

  return (
    <div className="max-w-2xl mx-auto mt-3 sm:mt-6 space-y-3 sm:space-y-4">
      <div className="flex items-center gap-2">
        <Badge color="blue">session {joinCode || sessionId.slice(-6)}</Badge>
        <span className="text-xs text-slate-500">{conn === "open" ? "● connected" : "○ offline"}</span>
        {!done && !aborted && !lost && (
          <button className="ml-auto text-xs text-slate-400 underline hover:text-slate-200 px-2 py-1"
            onClick={() => { if (confirm("Leave the study? Your session will end.")) abort(); }}>
            Leave study
          </button>
        )}
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
        <Panel className="!p-2 sm:!p-4 flex flex-col h-[calc(100dvh-8.5rem)] sm:h-[70vh] min-h-[20rem]">
          <div className="flex-1 overflow-y-auto space-y-3 px-1 overscroll-contain">
            {state.chat.map((m, i) => (
              <Bubble key={i} who={m.who} text={m.text} />
            ))}
            {state.streaming && <Bubble who="agent" text={state.streaming} />}
            {thinking && !state.streaming && <Typing />}
            <div ref={endRef} />
          </div>
          <form
            className="mt-2 sm:mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (draft.trim() && !thinking && sendMessage(draft.trim())) setDraft("");
            }}
          >
            <Input value={draft} onChange={(e) => setDraft(e.target.value)} enterKeyHint="send" autoComplete="off"
              placeholder={offline ? "Reconnecting…" : thinking ? "Waiting for reply…" : "Type your reply…"} />
            <Button type="submit" disabled={thinking || offline || !draft.trim()}>Send</Button>
          </form>
        </Panel>
      )}

      {inQuestionnaire && (
        <Panel className="!p-3 sm:!p-4">
          <div className="sticky top-14 z-[5] -mx-3 sm:-mx-4 -mt-3 sm:-mt-4 mb-3 px-3 sm:px-4 pt-3 pb-2 bg-panel border-b border-line rounded-t-xl">
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-semibold text-slate-200">A quick personality questionnaire</span>
              <span className="text-xs font-mono text-slate-400">{answeredCount}/{items.length}</span>
            </div>
            <div className="h-1 bg-ink rounded mt-1 overflow-hidden">
              <div className="h-full bg-accent transition-all" style={{ width: `${items.length ? (100 * answeredCount) / items.length : 0}%` }} />
            </div>
            <div className="flex justify-between text-[10px] text-slate-500 mt-1">
              <span>1 = very inaccurate</span><span>3 = neither</span><span>5 = very accurate</span>
            </div>
          </div>
          <div className="space-y-4">
            {items.map((it, n) => (
              <div key={it.id} className={`pb-3 border-b border-line/60 ${responses[it.id] ? "" : "border-l-2 border-l-amber-600/60 pl-2"}`}>
                <div className="text-sm mb-2"><span className="text-slate-500 mr-1">{n + 1}.</span>I {it.text}</div>
                <div className="grid grid-cols-5 gap-1.5">
                  {SCALE.map((lbl, idx) => {
                    const v = idx + 1;
                    const on = responses[it.id] === v;
                    return (
                      <button key={v} title={lbl} aria-label={lbl} onClick={() => answer(it.id, v)}
                        className={`py-2.5 rounded-lg text-sm border transition ${on ? "bg-accent text-white border-accent" : "bg-ink border-line text-slate-300 active:bg-line"}`}>
                        {v}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <div className="sticky bottom-0 -mx-3 sm:-mx-4 -mb-3 sm:-mb-4 mt-3 px-3 sm:px-4 py-3 bg-panel border-t border-line rounded-b-xl">
            <Button className="w-full" onClick={() => sendQuestionnaire(responses)} disabled={offline || items.length === 0 || answeredCount < items.length}>
              {answeredCount < items.length ? `Answer all statements (${items.length - answeredCount} left)` : "Submit"}
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
      <div className={`max-w-[85%] sm:max-w-[80%] rounded-2xl px-3 py-2 text-[15px] sm:text-sm leading-snug whitespace-pre-wrap break-words ${me ? "bg-accent text-white" : "bg-panel2 text-slate-100"}`}>
        {text}
      </div>
    </div>
  );
}
