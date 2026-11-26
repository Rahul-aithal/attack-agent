import { useState } from "react";
import type { Progress, SessionState } from "../useSession";

/** Rough, friendly duration for an *expected* time ("about 4 min"), never a precise countdown. */
export function roughTime(seconds: number): string {
  if (seconds <= 45) return "under a minute";
  const min = Math.round(seconds / 60);
  if (min <= 1) return "about 1 min";
  if (min < 10) return `about ${min} min`;
  return `about ${Math.round(min / 5) * 5} min`;
}

const STEPS: { key: string; label: string; phases: string[] }[] = [
  { key: "chat", label: "Chat", phases: ["", "consent", "profiling"] },
  { key: "twin", label: "Twin", phases: ["twin_handoff"] },
  { key: "scenario", label: "Scenario", phases: ["simulation"] },
  { key: "judge", label: "Judge", phases: ["evaluation"] },
  { key: "survey", label: "Questionnaire", phases: ["questionnaire"] },
  { key: "done", label: "Done", phases: ["debrief", "complete"] },
];

/** Where the session is: Chat → Twin → Scenario → Judge → Questionnaire → Done. */
export function PhaseStepper({ phase, waiting }: { phase: string; waiting?: boolean }) {
  const current = phase === "aborted" ? -1 : STEPS.findIndex((s) => s.phases.includes(phase));
  return (
    <div className="flex items-center gap-1 overflow-x-auto text-xs">
      {STEPS.map((s, i) => {
        const done = current > i;
        const active = current === i && !waiting;
        return (
          <div key={s.key} className="flex items-center gap-1 shrink-0">
            <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 border ${
              active ? "border-accent bg-accent/20 text-white"
                : done ? "border-emerald-700 bg-emerald-950/40 text-emerald-300"
                  : "border-line text-slate-500"}`}>
              <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] ${
                active ? "bg-accent text-white" : done ? "bg-emerald-600 text-white" : "bg-panel2"}`}>
                {done ? "✓" : i + 1}
              </span>
              {s.label}
            </div>
            {i < STEPS.length - 1 && <span className={`w-3 h-px ${done ? "bg-emerald-700" : "bg-line"}`} />}
          </div>
        );
      })}
      {phase === "aborted" && <span className="ml-2 text-rose-400">aborted</span>}
    </div>
  );
}

function Meter({ label, check, format, hint }: { label: string; check: { value: number; target: number; progress: number }; format: (v: number) => string; hint?: string }) {
  const pct = Math.round(check.progress * 100);
  const met = check.progress >= 1;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-slate-300">{label}</span>
        <span className={`font-mono ${met ? "text-emerald-400" : "text-slate-400"}`}>
          {format(check.value)} / {format(check.target)} {met && "✓"}
        </span>
      </div>
      <div className="h-2 rounded-full bg-ink mt-1 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${met ? "bg-emerald-500" : pct > 60 ? "bg-amber-400" : "bg-accent"}`} style={{ width: `${pct}%` }} />
      </div>
      {hint && <div className="text-[10px] text-slate-500 mt-0.5">{hint}</div>}
    </div>
  );
}

/**
 * How close the chat is to handing over to the twin: overall %, each stop condition, and an
 * expected (not measured) number of turns / minutes left.
 */
export function ProfilingProgress({ s }: { s: SessionState }) {
  const p: Progress | undefined = s.progress;
  const profiling = s.phase === "profiling" || s.phase === "" || s.phase === "consent";
  if (!profiling) {
    const handedOver = ["twin_handoff", "simulation", "evaluation", "questionnaire", "debrief", "complete"].includes(s.phase);
    return (
      <div className="rounded-xl border border-emerald-800 bg-emerald-950/30 px-4 py-3 text-sm">
        {handedOver
          ? <>Profiling finished after <b>{s.convergence.length}</b> participant replies, average confidence <b>{Math.round(s.avgConfidence * 100)}%</b>. The twin has taken over.</>
          : <>Session {s.phase}.</>}
      </div>
    );
  }
  if (!p) {
    return (
      <div className="rounded-xl border border-line bg-panel px-4 py-3 text-sm text-slate-400">
        Progress to the twin appears after the participant's first reply.
      </div>
    );
  }
  const overall = Math.round(p.overall * 100);
  const c = p.checks;
  return (
    <div className="rounded-xl border border-line bg-panel px-4 py-3 space-y-3">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <div className="text-xs text-slate-400">Progress to the twin</div>
          <div className="text-2xl font-semibold font-mono">{overall}%</div>
        </div>
        <div className="text-right text-sm">
          {p.expected_turns_left === 0
            ? <span className="text-emerald-300">ready — handing over after this reply</span>
            : <>
                <div>expected <b>~{p.expected_turns_left}</b> more repl{p.expected_turns_left === 1 ? "y" : "ies"}</div>
                <div className="text-xs text-slate-400">{roughTime(p.expected_seconds_left)} (≈{Math.round(p.seconds_per_turn)} s per reply)</div>
              </>}
        </div>
      </div>
      <div className="h-3 rounded-full bg-ink overflow-hidden">
        <div className="h-full rounded-full bg-gradient-to-r from-accent to-emerald-500 transition-all duration-700" style={{ width: `${overall}%` }} />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-2.5">
        <Meter label="Replies (minimum)" check={c.turns} format={(v) => `${v}`} hint={`hard limit: reply ${p.max_turns}`} />
        <Meter label="Traits confident" check={c.traits_ready} format={(v) => `${v}`}
          hint={`a trait counts at ≥ ${Math.round((c.traits_ready.per_trait_target ?? 0.5) * 100)}% confidence`} />
        <Meter label="Average confidence" check={c.confidence} format={(v) => `${Math.round(v * 100)}%`} />
        <Meter label="Profile stability" check={c.stability} format={(v) => `${Math.round(v * 100)}%`} hint="scores stopped moving much" />
      </div>
      {!p.converging && p.stopping_rule && (
        <div className="text-xs text-amber-300">Confidence isn't rising much — the chat will continue until the reply limit ({p.max_turns}). Steering toward weak traits can help.</div>
      )}
    </div>
  );
}

/** Minimal tabs. */
export function Tabs({ tabs, initial }: { tabs: { key: string; label: string; badge?: string | number; content: React.ReactNode }[]; initial?: string }) {
  const [active, setActive] = useState(initial ?? tabs[0]?.key);
  return (
    <div>
      <div className="flex gap-1 border-b border-line overflow-x-auto">
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setActive(t.key)}
            className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px transition ${
              active === t.key ? "border-accent text-white" : "border-transparent text-slate-400 hover:text-slate-200"}`}>
            {t.label}
            {t.badge != null && t.badge !== 0 && <span className="ml-1.5 text-[10px] rounded-full bg-panel2 px-1.5 py-0.5 text-slate-300">{t.badge}</span>}
          </button>
        ))}
      </div>
      {/* keep every tab mounted so scroll positions and inputs survive switching */}
      {tabs.map((t) => <div key={t.key} hidden={t.key !== active} className="pt-4 space-y-4">{t.content}</div>)}
    </div>
  );
}
