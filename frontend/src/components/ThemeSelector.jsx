import { useState } from "react";
import { Monitor, Sun, Moon } from "lucide-react";

const OPTIONS = [
  ["auto", "Automatico", Monitor],
  ["light", "Chiaro", Sun],
  ["dark", "Scuro", Moon],
];

export default function ThemeSelector() {
  const [pref, setPref] = useState(() => localStorage.getItem("themePref") || "auto");
  const choose = (p) => {
    localStorage.setItem("themePref", p);
    setPref(p);
    window.__applyTheme?.();
  };
  return (
    <div className="space-y-2" data-testid="theme-selector">
      <p className="font-mono text-[11px] uppercase tracking-wider text-gray-400">Tema</p>
      <div className="grid grid-cols-3 gap-1 rounded-md border border-white/10 bg-black/30 p-0.5">
        {OPTIONS.map(([id, label, Icon]) => (
          <button key={id} type="button" data-testid={`theme-${id}-button`} onClick={() => choose(id)}
            className={`flex items-center justify-center gap-1.5 rounded px-2 py-1.5 font-mono text-[11px] uppercase transition-colors ${pref === id ? "bg-emerald-500/15 text-emerald-400" : "text-gray-400 hover:text-gray-100"}`}>
            <Icon className="h-3.5 w-3.5" /> {label}
          </button>
        ))}
      </div>
      <p className="text-[11px] text-gray-500">{pref === "auto" ? "Segue il tema chiaro/scuro di Windows." : "Applicato subito, su questo dispositivo."}</p>
    </div>
  );
}
