import { useEffect, useState } from "react";
import { Badge, Panel } from "./ui";

/** Re-render every second so running timers and "last seen" stay current. */
function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

function Bar({ label, pct, detail }: { label: string; pct: number | null | undefined; detail?: string }) {
  const v = pct == null ? null : Math.max(0, Math.min(100, pct));
  const color = v == null ? "bg-slate-700" : v > 90 ? "bg-rose-500" : v > 70 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="text-xs">
      <div className="flex justify-between text-slate-400">
        <span>{label}</span>
        <span className="font-mono">{v == null ? "—" : `${v.toFixed(0)}%`}{detail ? ` · ${detail}` : ""}</span>
      </div>
      <div className="h-1.5 rounded bg-ink mt-0.5 overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${v ?? 0}%` }} />
      </div>
    </div>
  );
}

const gb = (mb?: number | null) => (mb == null ? "—" : `${(mb / 1024).toFixed(1)} GB`);
const secs = (ms: number) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);

export function MachinesPanel({ machines }: { machines: any[] }) {
  const now = useNow();
  return (
    <Panel title="Machines">
      {machines.length === 0 && (
        <div className="text-xs text-slate-500">
          No reports yet. On each laptop run:<br />
          <code className="text-slate-300 break-all">uv run scripts/node_monitor.py --server {location.origin} --token &lt;token&gt; --name &lt;name&gt;</code>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-3">
        {machines.map((m) => {
          // _rx = when this browser received the latest report (avoids clock differences between laptops)
          const age = (now - (m._rx ?? now)) / 1000;
          const stale = age > 10;
          const ramPct = m.ram_total_mb ? (100 * m.ram_used_mb) / m.ram_total_mb : null;
          return (
            <div key={m.name} className={`rounded-lg border p-3 space-y-2 ${stale ? "border-rose-700 opacity-70" : "border-line"}`}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium">{m.name}</span>
                <span className="text-xs text-slate-500">{m.os}</span>
                <span className="ml-auto">
                  {stale ? <Badge color="red">no report {Math.round(age)}s</Badge> : <Badge color="green">live</Badge>}
                </span>
              </div>
              <Bar label={`CPU (${m.cpu_count} cores)`} pct={m.cpu_pct} detail={m.cpu_temp_c != null ? `${Math.round(m.cpu_temp_c)}°C` : undefined} />
              <Bar label="RAM" pct={ramPct} detail={`${gb(m.ram_used_mb)} / ${gb(m.ram_total_mb)}${m.swap_used_mb > 256 ? ` · swap ${gb(m.swap_used_mb)}` : ""}`} />
              {(m.gpus || []).map((g: any, i: number) => (
                <div key={i} className="space-y-1">
                  <Bar label={`GPU ${g.name.replace("NVIDIA GeForce ", "")}`} pct={g.util_pct}
                    detail={[g.temp_c != null && `${Math.round(g.temp_c)}°C`, g.power_w != null && `${g.power_w.toFixed(0)} W`].filter(Boolean).join(" · ")} />
                  <Bar label="VRAM" pct={g.vram_total_mb ? (100 * g.vram_used_mb) / g.vram_total_mb : null}
                    detail={`${gb(g.vram_used_mb)} / ${gb(g.vram_total_mb)}`} />
                </div>
              ))}
              <div className="text-xs text-slate-400">
                {m.ollama?.reachable === false && <span className="text-rose-400">Ollama not reachable</span>}
                {m.ollama?.reachable && m.ollama.models.length === 0 && <span>Ollama idle (no model loaded)</span>}
                {m.ollama?.models?.map((o: any) => (
                  <div key={o.name} className="flex justify-between font-mono">
                    <span className="text-slate-300">{o.name}</span>
                    <span>{gb(o.size_mb)} · {o.gpu_pct}% on GPU</span>
                  </div>
                ))}
              </div>
              <div className="flex gap-3 text-[11px] text-slate-500 flex-wrap">
                {m.battery && <span>{m.battery.plugged ? "🔌" : "🔋"} {m.battery.percent}%{!m.battery.plugged && " (unplugged!)"}</span>}
                <span>↑ {m.net_up_kbps} kb/s ↓ {m.net_down_kbps} kb/s</span>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

const ROLE_LABEL: Record<string, string> = {
  agent: "chat agent", extractor: "signal extractor", twin: "digital twin", judge: "judge", sim_participant: "simulated participant",
};

export function ModelActivity({ llm, sessionFilter, compact }: { llm: { active: any[]; recent: any[]; totals: any[] }; sessionFilter?: string; compact?: boolean }) {
  const now = useNow(500);
  const pick = (c: any) => !sessionFilter || c.session_id === sessionFilter;
  const active = llm.active.filter(pick);
  const recent = llm.recent.filter(pick).slice(0, compact ? 5 : 12);
  return (
    <Panel title="Model activity (live)">
      <div className="space-y-1 mb-3">
        {active.length === 0 && <div className="text-xs text-slate-500">no model call running</div>}
        {active.map((c) => (
          <div key={c.call_id} className="flex items-center gap-2 text-xs rounded border border-amber-700 bg-amber-950/30 px-2 py-1">
            <span className="w-2.5 h-2.5 rounded-full border-2 border-amber-400 border-t-transparent animate-spin shrink-0" />
            <span className="text-amber-200">{ROLE_LABEL[c.role] ?? c.role}</span>
            <span className="text-slate-400 font-mono truncate">{c.node}/{c.model}</span>
            <span className="ml-auto font-mono">{secs((c.running_ms ?? 0) + (now - (c._rx ?? now)))}</span>
          </div>
        ))}
      </div>
      <div className="text-xs text-slate-400 mb-1">Recent calls</div>
      <div className="max-h-48 overflow-y-auto text-xs font-mono space-y-0.5">
        {recent.length === 0 && <div className="text-slate-500 font-sans">none yet</div>}
        {recent.map((c) => (
          <div key={c.call_id ?? c.created_at} className="flex gap-2">
            <span className={c.ok ? "text-emerald-400" : "text-rose-400"}>{c.ok ? "✓" : "✗"}</span>
            <span className="w-24 shrink-0 truncate">{c.role}</span>
            <span className="text-slate-500 truncate">{c.node}/{c.model}</span>
            {c.join_code && !sessionFilter && <span className="text-slate-500">{c.join_code}</span>}
            <span className="ml-auto">{secs(c.latency_ms)}</span>
          </div>
        ))}
      </div>
      {llm.totals.length > 0 && !sessionFilter && !compact && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-slate-500"><tr><th className="text-left font-normal">role → node/model</th><th className="text-right font-normal">calls</th><th className="text-right font-normal">avg</th><th className="text-right font-normal">fail</th></tr></thead>
            <tbody className="font-mono">
              {llm.totals.map((t) => (
                <tr key={`${t.role}@${t.node}/${t.model}`}>
                  <td className="truncate max-w-[12rem]">{t.role} → {t.node}/{t.model}</td>
                  <td className="text-right">{t.calls}</td>
                  <td className="text-right">{secs(t.avg_ms)}</td>
                  <td className={`text-right ${t.failed ? "text-rose-400" : ""}`}>{t.failed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/** One line per laptop: enough to spot trouble at a glance during a session. */
export function MachinesCompact({ machines }: { machines: any[] }) {
  const now = useNow(2000);
  const pct = (a?: number | null, b?: number | null) => (a != null && b ? Math.round((100 * a) / b) : null);
  const cell = (v: number | null | undefined) => (
    <span className={`font-mono ${v == null ? "text-slate-600" : v > 90 ? "text-rose-400" : v > 70 ? "text-amber-300" : "text-slate-300"}`}>
      {v == null ? "–" : `${Math.round(v)}%`}
    </span>
  );
  return (
    <Panel title="Machines">
      {machines.length === 0 && <div className="text-xs text-slate-500">no monitor running (see README → Monitoring)</div>}
      <table className="w-full text-xs">
        {machines.length > 0 && (
          <thead className="text-slate-500"><tr>
            <th className="text-left font-normal">laptop</th><th className="font-normal">CPU</th><th className="font-normal">RAM</th>
            <th className="font-normal">GPU</th><th className="font-normal">VRAM</th><th className="text-left font-normal pl-2">model</th>
          </tr></thead>
        )}
        <tbody>
          {machines.map((m) => {
            const stale = (now - (m._rx ?? now)) / 1000 > 10;
            const g = m.gpus?.[0];
            const model = m.ollama?.models?.[0];
            return (
              <tr key={m.name} className={stale ? "opacity-50" : ""}>
                <td className="py-0.5"><span className={stale ? "text-rose-400" : "text-emerald-400"}>●</span> {m.name}</td>
                <td className="text-center">{cell(m.cpu_pct)}</td>
                <td className="text-center">{cell(pct(m.ram_used_mb, m.ram_total_mb))}</td>
                <td className="text-center">{cell(g?.util_pct)}</td>
                <td className="text-center">{cell(pct(g?.vram_used_mb, g?.vram_total_mb))}</td>
                <td className="pl-2 truncate max-w-[9rem] text-slate-400">{model ? `${model.name}` : m.ollama?.reachable === false ? <span className="text-rose-400">ollama down</span> : "idle"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
