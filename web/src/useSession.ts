import { useCallback, useRef, useState } from "react";
import { SessionSocket } from "./api";
import type { SessionEvent, TraitInfo } from "./types";

export interface ChatMsg { who: "agent" | "participant" | "scenario"; text: string; }

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
  scenario?: { message: string; principle: string; reason: string };
  twin?: { predicted_outcome: string; confidence: number; reasoning: string };
  outcome?: { real_outcome: string; twin_outcome: string; match_flag: boolean };
  questionnaireResult?: { answered: number; mae: number | null };
  debrief?: string;
  awaiting?: string;
  awaitQuestionnaire: boolean;
  selfReport?: Record<string, number>;
}

const initial: SessionState = {
  phase: "", chat: [], streaming: "", traits: {}, stability: 0, avgConfidence: 0,
  convergence: [], evidence: [], trace: [], awaitQuestionnaire: false,
};

export function useSession() {
  const [state, setState] = useState<SessionState>(initial);
  const sockRef = useRef<SessionSocket | null>(null);

  const handle = useCallback((e: SessionEvent) => {
    setState((s) => {
      const ns = { ...s };
      switch (e.type) {
        case "phase_change":
          ns.phase = e.phase;
          ns.trace = [...s.trace, `→ phase: ${e.phase}`];
          break;
        case "agent_token":
          ns.streaming = s.streaming + e.token;
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
          const row: any = { turn: e.turn };
          for (const [k, v] of Object.entries(e.traits as Record<string, TraitInfo>)) row[k] = v.score;
          ns.convergence = [...s.convergence, row];
          break;
        }
        case "scenario_message":
          ns.scenario = { message: e.message, principle: e.principle, reason: e.reason };
          ns.chat = [...s.chat, { who: "scenario", text: e.message }];
          break;
        case "twin_prediction":
          ns.twin = { predicted_outcome: e.predicted_outcome, confidence: e.confidence, reasoning: e.reasoning };
          ns.trace = [...s.trace, `twin predicts ${e.predicted_outcome} (${e.confidence})`];
          break;
        case "outcome":
          ns.outcome = { real_outcome: e.real_outcome, twin_outcome: e.twin_outcome, match_flag: e.match_flag };
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
  }, []);

  const connect = useCallback((sessionId: string, token: string | null) => {
    sockRef.current?.close();
    sockRef.current = new SessionSocket(sessionId, token, { onEvent: handle });
  }, [handle]);

  const sendMessage = useCallback((text: string) => {
    setState((s) => ({ ...s, awaiting: undefined, chat: [...s.chat, { who: "participant", text }] }));
    sockRef.current?.message(text);
  }, []);

  const sendQuestionnaire = useCallback((r: Record<number, number>) => sockRef.current?.questionnaire(r), []);
  const abort = useCallback(() => sockRef.current?.abort(), []);
  const disconnect = useCallback(() => { sockRef.current?.close(); sockRef.current = null; }, []);
  const reset = useCallback(() => setState(initial), []);

  return { state, connect, disconnect, sendMessage, sendQuestionnaire, abort, reset };
}
