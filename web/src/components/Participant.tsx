import { useEffect, useRef, useState } from "react";
import { createSession, getQuestionnaire } from "../api";
import type { QItem } from "../types";
import { useSession } from "../useSession";
import { Badge, Button, Input, Panel } from "./ui";

const SCALE = ["Very inaccurate", "Moderately inaccurate", "Neither", "Moderately accurate", "Very accurate"];

export function Participant() {
  const { state, connect, sendMessage, sendQuestionnaire, abort } = useSession();
  const [consented, setConsented] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [items, setItems] = useState<QItem[]>([]);
  const [responses, setResponses] = useState<Record<number, number>>({});
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { getQuestionnaire().then(setItems).catch(() => {}); }, []);
  // Instant scroll while tokens stream in; a smooth scroll restarted on every token makes the chat jank.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: state.streaming ? "auto" : "smooth" });
  }, [state.chat, state.streaming]);

  async function start() {
    const id = await createSession();
    setSessionId(id);
    setConsented(true);
    connect(id, null);
  }

  if (!consented) {
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
          <div className="mt-4 flex gap-3">
            <Button onClick={start}>I consent — start</Button>
          </div>
        </Panel>
      </div>
    );
  }

  const inQuestionnaire = state.awaitQuestionnaire;
  const done = state.phase === "complete" || !!state.debrief;
  // The agent is working (reading signals / generating) until it asks for the next message.
  const thinking = !state.awaiting && !done && !inQuestionnaire && state.phase !== "aborted";

  return (
    <div className="max-w-2xl mx-auto mt-6 space-y-4">
      <div className="flex items-center justify-between">
        <Badge color="blue">session {sessionId?.slice(-6)}</Badge>
        <Badge color="slate">phase: {state.phase || "starting"}</Badge>
      </div>

      {!inQuestionnaire && !done && (
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
            onSubmit={(e) => { e.preventDefault(); if (draft.trim() && !thinking) { sendMessage(draft.trim()); setDraft(""); } }}
          >
            <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={thinking ? "Waiting for reply…" : "Type your reply…"} autoFocus />
            <Button type="submit" disabled={thinking}>Send</Button>
            <Button variant="ghost" onClick={abort}>Quit</Button>
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
            <Button onClick={() => sendQuestionnaire(responses)} disabled={Object.keys(responses).length === 0}>
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
