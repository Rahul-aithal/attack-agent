import { useCallback, useRef, useState } from "react";
import { SessionSocket } from "./api";
import type { ConnState } from "./api";
import type { SessionEvent, TraitInfo } from "./types";

export interface Check { value: number; target: number; progress: number; per_trait_target?: number }
export interface Progress {
  overall: number;
  checks: { turns: Check; traits_ready: Check; confidence: Check; stability: Check };
  max_turns: number; stopping_rule: boolean; converging: boolean;
  expected_turns_left: number; expected_seconds_left: number; seconds_per_turn: number;
}

export interface ChatMsg { who: "agent" | "participant" | "scenario"; text: string; scn?: boolean; }

export interface SessionState {
  phase: string;
  chat: ChatMsg[];
  streaming: string;
  traits: Record<string, TraitInfo>;
  stability: number;
  avgConfidence: number;
  convergence: { turn: number;[k: string]: number }[];
  evidence: { trait: string; signal: string; delta: number }[];
  trace: string[];
  scenario?: { message: string; principle: string; reason: string; fromAgent?: boolean };
  twin?: {
    predicted_outcome: string; confidence: number; reasoning: string; source?: string;
    samples?: { reply: string; outcome: string; confidence: number; reasoning: string; judged_by: string }[];
  };
  outcome?: { real_outcome: string; twin_outcome: string; match_flag: boolean | null; judged_by?: string | null; rationale?: string | null };
  questionnaireResult?: { answered: number; mae: number | null };
  debrief?: string;
  awaiting?: string;
  awaitQuestionnaire: boolean;
  selfReport?: Record<string, number>;
  error?: string;
  plan?: { turn: number; focus: string[]; auto_focus: string[]; note?: string | null; steered: boolean };
  memory: { turn: number; topic: string | null; question: string; answer: string }[];
  rewrites: number;
  progress?: Progress;
  interventions: { type: string; turn: number; phase: string; at: string; focus?: string[] | null; note?: string | null }[];
}

const initial: SessionState = {
  phase: "", chat: [], streaming: "", traits: {}, stability: 0, avgConfidence: 0,
  convergence: [], evidence: [], trace: [], awaitQuestionnaire: false, interventions: [], memory: [], rewrites: 0,
};

export function detectDevice(): "mobile" | "desktop" {
  const coarse = window.matchMedia?.("(pointer: coarse)").matches;
  return coarse && Math.min(window.innerWidth, window.innerHeight) < 820 ? "mobile" : "desktop";
}

export function useSession() {
  const [state, setState] = useState<SessionState>(initial);
  const [conn, setConn] = useState<ConnState>("closed");
  const sockRef = useRef<SessionSocket | null>(null);

  const handle = useCallback((e: SessionEvent) => {
    setState((s) => {
      const ns = { ...s };
      switch (e.type) {
        case "phase_change":
          ns.phase = e.phase;
          ns.awaiting = undefined; // a new phase always starts with the agent working
          ns.trace = [...s.trace, `→ phase: ${e.phase}`];
          break;
        case "agent_token":
          ns.streaming = s.streaming + e.token;
          break;
        case "memory":
          ns.memory = [...s.memory, { turn: e.turn, topic: e.topic, question: e.question, answer: e.answer }];
          break;
        case "agent_rewrite":
          ns.rewrites = s.rewrites + 1;
          ns.trace = [...s.trace, `repeat caught (turn ${e.turn}): “${e.repeated}” → ${e.fixed ? "rewritten" : "could not rewrite"}`];
          break;
        case "agent_plan":
          ns.plan = { turn: e.turn, focus: e.focus, auto_focus: e.auto_focus, note: e.note, steered: e.steered };
          break;
        case "intervention":
          ns.interventions = [...s.interventions, e as any];
          ns.trace = [...s.trace, `researcher: ${e.type}${e.focus ? ` → ${e.focus.join(", ")}` : ""}${e.note ? ` (“${e.note}”)` : ""}`];
          break;
        case "participant_message":
          ns.chat = [...s.chat, { who: "participant", text: e.text }];
          break;
        case "error":
          ns.error = e.message;
          break;
        case "replaced":
          ns.error = "replaced";
          break;
        case "agent_message":
          ns.chat = [...s.chat, { who: "agent", text: e.text }];
          ns.streaming = "";
          break;
        case "trait_update":
          ns.evidence = [{ trait: e.trait, signal: `Δ ${e.delta > 0 ? "+" : ""}${e.delta}`, delta: e.delta }, ...s.evidence].slice(0, 40);
          break;
        case "profile": {
          ns.traits = e.traits;
          ns.stability = e.stability;
          ns.avgConfidence = e.avg_confidence;
          if (e.progress) ns.progress = e.progress;
          const row: any = { turn: e.turn };
          for (const [k, v] of Object.entries(e.traits as Record<string, TraitInfo>)) row[k] = v.score;
          ns.convergence = [...s.convergence, row];
          break;
        }
        case "scenario_message":
          // from_agent: delivered by the chat assistant itself — renders as its own next message,
          // so only the separate-contact variant keeps the "scenario" presentation.
          ns.scenario = { message: e.message, principle: e.principle, reason: e.reason, fromAgent: !!e.from_agent };
          ns.chat = [...s.chat, e.from_agent
            ? { who: "agent", text: e.message, scn: true }
            : { who: "scenario", text: e.message }];
          break;
        case "twin_prediction":
          ns.twin = { predicted_outcome: e.predicted_outcome, confidence: e.confidence, reasoning: e.reasoning, source: e.source, samples: e.samples };
          ns.trace = [...s.trace, `twin predicts ${e.predicted_outcome} (${e.confidence})`];
          break;
        case "outcome":
          ns.outcome = { real_outcome: e.real_outcome, twin_outcome: e.twin_outcome, match_flag: e.match_flag, judged_by: e.judged_by, rationale: e.rationale };
          break;
        case "questionnaire_result":
          ns.questionnaireResult = { answered: e.answered, mae: e.comparison?.mae ?? null };
          ns.awaitQuestionnaire = false;
          if (e.comparison?.per_trait) {
            const sr: Record<string, number> = {};
            for (const [k, v] of Object.entries<any>(e.comparison.per_trait)) sr[k] = v.self_report;
            ns.selfReport = sr;
          }
          break;
        case "debrief":
          ns.debrief = e.message;
          break;
        case "await_message":
          ns.awaiting = e.context;
          break;
        case "await_questionnaire":
          ns.awaitQuestionnaire = true;
          break;
      }
      return ns;
    });
    // A finished (or unknown) session is closed by the server on purpose: stop reconnecting.
    if (e.type === "complete" || e.type === "aborted" || e.type === "replaced" || (e.type === "error" && e.message === "session not found")) {
      sockRef.current?.close();
    }
  }, []);

  const connect = useCallback((sessionId: string, token: string | null) => {
    sockRef.current?.close();
    // Every (re)connect replays the full session, so start from a clean view each time.
    sockRef.current = new SessionSocket(sessionId, token, {
      onEvent: handle,
      onOpen: () => {
        setState(initial);
        // participant only: lets the agent keep messages short on phones
        if (!token) sockRef.current?.send({ kind: "client_info", device: detectDevice() });
      },
      onState: setConn,
    }, token ? undefined : detectDevice());
  }, [handle]);

  // The server echoes the message back as `participant_message`, which adds it to the chat (and
  // restores it after a reconnect), so nothing is appended locally here.
  const sendMessage = useCallback((text: string): boolean => {
    const sent = sockRef.current?.message(text) ?? false;
    if (sent) setState((s) => ({ ...s, awaiting: undefined }));
    return sent;
  }, []);

  const sendQuestionnaire = useCallback((r: Record<number, number>) => sockRef.current?.questionnaire(r), []);
  const abort = useCallback(() => sockRef.current?.abort(), []);
  const sendProgress = useCallback((answered: number) => sockRef.current?.progress(answered), []);
  const steer = useCallback((focus: string[] | null, note: string | null) => sockRef.current?.steer(focus, note) ?? false, []);
  const finishProfiling = useCallback(() => sockRef.current?.finishProfiling() ?? false, []);
  const disconnect = useCallback(() => { sockRef.current?.close(); sockRef.current = null; }, []);
  const reset = useCallback(() => setState(initial), []);

  return { state, conn, connect, disconnect, sendMessage, sendQuestionnaire, sendProgress, steer, finishProfiling, abort, reset };
}
