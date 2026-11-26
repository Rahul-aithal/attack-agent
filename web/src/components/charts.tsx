import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer,
  LineChart, Line, XAxis, YAxis, Tooltip, Legend, CartesianGrid,
} from "recharts";
import type { TraitInfo, TraitName } from "../types";

// Accessible categorical palette (distinct in light & dark), one hue per trait.
export const TRAIT_COLORS: Record<string, string> = {
  openness: "#5b8cff",
  conscientiousness: "#36c2a6",
  extraversion: "#f2a541",
  agreeableness: "#b980f0",
  neuroticism: "#ef6f6c",
};

const TRAITS: TraitName[] = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"];

export function TraitRadar({ traits, selfReport }: { traits: Record<string, TraitInfo>; selfReport?: Record<string, number> }) {
  const data = TRAITS.map((t) => ({
    trait: t.slice(0, 4).toUpperCase(),
    inferred: traits[t] ? Math.round(traits[t].score * 100) : 0,
    self: selfReport && selfReport[t] != null ? Math.round(selfReport[t] * 100) : undefined,
  }));
  return (
    <ResponsiveContainer width="100%" height={280}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="#243149" />
        <PolarAngleAxis dataKey="trait" tick={{ fill: "#9fb0d0", fontSize: 12 }} />
        <PolarRadiusAxis domain={[0, 100]} tick={{ fill: "#5b6b8c", fontSize: 10 }} />
        <Radar name="Inferred" dataKey="inferred" stroke="#5b8cff" fill="#5b8cff" fillOpacity={0.35} />
        {selfReport && <Radar name="Self-report" dataKey="self" stroke="#36c2a6" fill="#36c2a6" fillOpacity={0.15} />}
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Tooltip contentStyle={{ background: "#121a2b", border: "1px solid #243149", borderRadius: 8 }} />
      </RadarChart>
    </ResponsiveContainer>
  );
}

export function Convergence({ history }: { history: { turn: number;[k: string]: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={history}>
        <CartesianGrid stroke="#1a2540" />
        <XAxis dataKey="turn" tick={{ fill: "#9fb0d0", fontSize: 11 }} label={{ value: "turn", fill: "#5b6b8c", position: "insideBottom", offset: -2 }} />
        <YAxis domain={[0, 1]} tick={{ fill: "#9fb0d0", fontSize: 11 }} />
        <Tooltip contentStyle={{ background: "#121a2b", border: "1px solid #243149", borderRadius: 8 }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {TRAITS.map((t) => (
          <Line key={t} type="monotone" dataKey={t} stroke={TRAIT_COLORS[t]} dot={false} strokeWidth={2} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
