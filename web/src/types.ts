export type TraitName =
  | "openness" | "conscientiousness" | "extraversion" | "agreeableness" | "neuroticism";

export interface TraitInfo {
  score: number;
  score_1_5?: number;
  confidence: number;
  evidence_count: number;
}

export interface SessionEvent {
  type: string;
  session_id?: string;
  [k: string]: any;
}

export interface QItem { id: number; text: string; }
