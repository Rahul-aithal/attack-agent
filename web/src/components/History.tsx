import { useEffect, useState } from "react";
import type { PastSession } from "../api";
import { getHistory, participantLink, reopenSession, reportUrl } from "../api";
import { Badge, Button, Panel } from "./ui";

const STATUS_COLOR: Record<string, string> = { live: "green", complete: "blue", aborted: "red", interrupted: "amber" };

/**
 * Every previous session (survives server restarts): open it, resume it so the participant can
 * rejoin with the same code, or get its report.
 */
export function PreviousSessions({ token, refreshKey, onOpen }: { token: string; refreshKey: string; onOpen: (id: string, code?: string | null) => void }) {
  const [rows, setRows] = useState<PastSession[] | null>(null);
  const [filter, setFilter] = useState<"all" | "resumable" | "complete">("all");
  const [msg, setMsg] = useState("");

  const load = () => getHistory(token).then(setRows).catch(() => setRows(null));
  useEffect(() => { if (token) load(); }, [token, refreshKey]);

  if (!token) return null;
  const shown = (rows ?? []).filter((r) => filter === "all" || (filter === "resumable" ? r.resumable : r.status === "complete"));

  async function resume(r: PastSession) {
    try {
      const out = await reopenSession(token, r.session_id);
      setMsg(`Session ${out.join_code} is open again (${out.phase}). The participant rejoins with code ${out.join_code}: ${participantLink(out.join_code)}`);
      load();
    } catch (e: any) { setMsg(`Could not reopen: ${e.message ?? e}`); }
  }

  return (
    <Panel title="Previous sessions">
      <div className="flex items-center gap-2 mb-2 flex-wrap text-xs">
        {(["all", "resumable", "complete"] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-2 py-1 rounded ${filter === f ? "bg-accent text-white" : "bg-panel2 text-slate-300"}`}>{f}</button>
        ))}
        <button onClick={load} className="ml-auto text-slate-400 underline">refresh</button>
      </div>
      {msg && <div className="text-xs text-emerald-300 mb-2 break-all">{msg}</div>}
      {rows === null && <div className="text-xs text-slate-500">loading…</div>}
      {rows && shown.length === 0 && <div className="text-xs text-slate-500">none</div>}
      <div className="max-h-80 overflow-y-auto space-y-1">
        {shown.map((r) => (
          <div key={r.session_id} className="flex items-center gap-x-2 gap-y-1 flex-wrap text-xs border-b border-line/60 py-1.5">
            <span className="font-mono tracking-widest text-sm">{r.join_code ?? r.session_id.slice(-6)}</span>
            <span className="text-slate-500">{r.started_at ? new Date(r.started_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</span>
            <Badge color={STATUS_COLOR[r.status] ?? "slate"}>{r.status}{r.status === "aborted" && r.abort_reason ? ` · ${r.abort_reason.replace("participant_", "")}` : ""}</Badge>
            {r.status !== "complete" && r.phase && <span className="text-slate-500">at {r.phase}</span>}
            <span className="text-slate-400">💬 {r.participant_messages ?? 0}</span>
            {r.real_outcome && <span className="text-slate-400">{r.real_outcome}{r.match_flag != null ? (r.match_flag ? " ✓" : " ✗") : ""}</span>}
            {r.device && <span className="text-slate-500">{r.device}</span>}
            {r.steered && <Badge color="amber">steered</Badge>}
            <span className="ml-auto flex gap-1 items-center">
              {r.saved && (
                <a className="underline text-slate-300" href={reportUrl(token, r.session_id, "md")} target="_blank" rel="noreferrer">report</a>
              )}
              {r.resumable && <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => resume(r)}>Resume</Button>}
              <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => onOpen(r.session_id, r.join_code)}>Open</Button>
            </span>
          </div>
        ))}
      </div>
      <div className="text-[11px] text-slate-500 mt-2">
        Interrupted = the server stopped mid-session. Resume makes a session live again; the participant then rejoins with the same code
        (a participant who only lost connection can also just re-enter the code themselves).
      </div>
    </Panel>
  );
}
