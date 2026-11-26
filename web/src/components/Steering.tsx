import { useEffect, useRef, useState } from "react";
import type { SessionState } from "../useSession";
import { Badge, Button, Input, Panel } from "./ui";

const TRAITS = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"];
const TOPIC: Record<string, string> = {
  openness: "hobbies, new experiences, curiosity",
  conscientiousness: "planning, routines, deadlines",
  extraversion: "social life, groups, free time",
  agreeableness: "helping, trust, disagreements",
  neuroticism: "stress, pressure, setbacks",
};

/** Live transcript as the researcher sees it (includes the streaming reply). */
export function Transcript({ s }: { s: SessionState }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [s.chat.length, s.streaming]);
  return (
    <Panel title="Live conversation">
      <div className="max-h-80 overflow-y-auto space-y-1.5 text-sm pr-1">
        {s.chat.length === 0 && <div className="text-xs text-slate-500">no messages yet</div>}
        {s.chat.map((m, i) => (
          <div key={i} className={m.who === "scenario" ? "border-l-2 border-rose-600 pl-2" : ""}>
            <span className={`text-xs font-mono mr-1 ${m.who === "participant" ? "text-blue-400" : m.who === "scenario" ? "text-rose-400" : "text-emerald-400"}`}>
              {m.who === "participant" ? "P" : m.who === "scenario" ? "SCN" : "A"}
            </span>
            <span className="whitespace-pre-wrap break-words">{m.text}</span>
          </div>
        ))}
        {s.streaming && (
          <div><span className="text-xs font-mono mr-1 text-emerald-400">A</span><span className="text-slate-300">{s.streaming}▍</span></div>
        )}
        <div ref={end} />
      </div>
    </Panel>
  );
}

/**
 * Topic coverage + optional researcher steering. Every action is logged with the session
 * (state.interventions) so steered sessions can be flagged or excluded in the analysis.
 */
export function Steering({ s, steer, finishProfiling }: {
  s: SessionState;
  steer: (focus: string[] | null, note: string | null) => boolean;
  finishProfiling: () => boolean;
}) {
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const profiling = s.phase === "profiling";
  // a steer is consumed by the next reply; clear the "queued" hint when a new plan arrives
  useEffect(() => { setPending(null); }, [s.plan?.turn, s.plan?.steered]);

  const send = (focus: string[] | null, text: string | null, label: string) => {
    if (steer(focus, text)) setPending(label);
  };

  return (
    <Panel title="Topic coverage & steering">
      <div className="text-[11px] text-slate-500 mb-2">
        Optional. Interventions change what the agent asks and are recorded with the session ({s.interventions.length} so far).
      </div>
      <div className="space-y-1.5">
        {TRAITS.map((t) => {
          const info = s.traits[t];
          const conf = info?.confidence ?? 0;
          const n = info?.evidence_count ?? 0;
          const next = s.plan?.focus?.includes(t);
          return (
            <div key={t} className="flex items-center gap-2 text-xs">
              <div className="w-28 shrink-0">
                <div className="capitalize text-slate-200">{t}</div>
                <div className="text-[10px] text-slate-500 truncate">{TOPIC[t]}</div>
              </div>
              <div className="flex-1">
                <div className="h-1.5 bg-ink rounded overflow-hidden">
                  <div className={`h-full ${conf >= 0.5 ? "bg-emerald-500" : conf > 0.2 ? "bg-amber-500" : "bg-rose-500"}`} style={{ width: `${Math.round(conf * 100)}%` }} />
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {n === 0 ? "not covered yet" : `${n} signal${n > 1 ? "s" : ""} · conf ${conf.toFixed(2)}`}
                  {next && <span className="text-amber-300"> · next reply</span>}
                </div>
              </div>
              <Button variant="ghost" className="!px-2 !py-1 text-xs" disabled={!profiling}
                onClick={() => send([t], null, `ask about ${t}`)}>ask next</Button>
            </div>
          );
        })}
      </div>

      {s.plan && (
        <div className="mt-3 text-xs text-slate-400">
          Last reply aimed at: <span className="text-slate-200">{s.plan.focus.join(", ") || "free conversation"}</span>
          {s.plan.steered && <Badge color="amber">steered</Badge>}
          {s.plan.note && <div className="text-slate-500">note: “{s.plan.note}”</div>}
        </div>
      )}
      {pending && <div className="mt-1 text-xs text-amber-300">queued for the next reply: {pending}</div>}

      <form className="mt-3 flex gap-2" onSubmit={(e) => {
        e.preventDefault();
        if (note.trim()) { send(null, note.trim(), `“${note.trim()}”`); setNote(""); }
      }}>
        <Input value={note} onChange={(e) => setNote(e.target.value)} disabled={!profiling}
          placeholder="One-off instruction for the next reply, e.g. ask what they do when plans change" />
        <Button type="submit" variant="ghost" disabled={!profiling || !note.trim()}>Send</Button>
      </form>

      <div className="mt-3 flex items-center gap-2">
        <Button variant="danger" disabled={!profiling}
          onClick={() => { if (confirm("End the chat now and move on to the twin + scenario?")) finishProfiling(); }}>
          End chat → twin
        </Button>
        {!profiling && <span className="text-xs text-slate-500">steering is available during the profiling chat</span>}
      </div>
    </Panel>
  );
}
