import React from "react";

export function Panel({ title, children, className = "" }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-panel border border-line rounded-xl p-4 ${className}`}>
      {title && <div className="text-sm font-semibold text-slate-300 mb-3">{title}</div>}
      {children}
    </div>
  );
}

export function Button({ children, onClick, variant = "primary", disabled, type = "button" }: {
  children: React.ReactNode; onClick?: () => void; variant?: "primary" | "ghost" | "danger"; disabled?: boolean; type?: "button" | "submit";
}) {
  const styles = {
    primary: "bg-accent hover:bg-blue-500 text-white",
    ghost: "bg-panel2 hover:bg-line text-slate-200",
    danger: "bg-rose-600 hover:bg-rose-500 text-white",
  }[variant];
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={`px-4 py-2 rounded-lg text-sm font-medium transition ${styles} disabled:opacity-40 disabled:cursor-not-allowed`}>
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`bg-ink border border-line rounded-lg px-3 py-2 text-sm w-full outline-none focus:border-accent ${props.className || ""}`} />;
}

export function Badge({ children, color = "slate" }: { children: React.ReactNode; color?: string }) {
  const map: Record<string, string> = {
    green: "bg-emerald-900/50 text-emerald-300 border-emerald-700",
    red: "bg-rose-900/50 text-rose-300 border-rose-700",
    blue: "bg-blue-900/50 text-blue-300 border-blue-700",
    slate: "bg-slate-800 text-slate-300 border-slate-600",
    amber: "bg-amber-900/50 text-amber-300 border-amber-700",
  };
  return <span className={`inline-block px-2 py-0.5 rounded-md text-xs border ${map[color] || map.slate}`}>{children}</span>;
}
