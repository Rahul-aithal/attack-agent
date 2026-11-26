import { useState } from "react";
import { Participant } from "./components/Participant";
import { Researcher } from "./components/Researcher";

export default function App() {
  const params = new URLSearchParams(location.search);
  const [mode, setMode] = useState<"participant" | "researcher" | null>(
    params.get("view") === "researcher" ? "researcher" : params.get("view") === "participant" ? "participant" : null
  );

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-panel/60 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="font-semibold">Attack Agent <span className="text-slate-500 font-normal text-sm">· susceptibility study</span></div>
          <nav className="flex gap-2 text-sm">
            <button onClick={() => setMode("participant")} className={`px-3 py-1 rounded ${mode === "participant" ? "bg-accent text-white" : "text-slate-400 hover:text-white"}`}>Participant</button>
            <button onClick={() => setMode("researcher")} className={`px-3 py-1 rounded ${mode === "researcher" ? "bg-accent text-white" : "text-slate-400 hover:text-white"}`}>Researcher</button>
          </nav>
        </div>
      </header>
      <main className="px-4 pb-16">
        {mode === null && (
          <div className="max-w-xl mx-auto mt-20 text-center space-y-6">
            <h1 className="text-2xl font-semibold">Choose how you're joining</h1>
            <div className="flex gap-4 justify-center">
              <button onClick={() => setMode("participant")} className="bg-panel border border-line rounded-xl p-6 w-48 hover:border-accent transition">
                <div className="text-lg font-medium">I'm a participant</div>
                <div className="text-xs text-slate-400 mt-1">Have a short chat</div>
              </button>
              <button onClick={() => setMode("researcher")} className="bg-panel border border-line rounded-xl p-6 w-48 hover:border-accent transition">
                <div className="text-lg font-medium">Researcher</div>
                <div className="text-xs text-slate-400 mt-1">Live presenter dashboard</div>
              </button>
            </div>
            <p className="text-xs text-slate-500">Academic research prototype. All scenarios are fictional and harmless.</p>
          </div>
        )}
        {mode === "participant" && <Participant />}
        {mode === "researcher" && <Researcher />}
      </main>
    </div>
  );
}
