import { useEffect, useState } from "react";
import { UserButton } from "@clerk/react";
import { Download, Settings2, ShieldHalf } from "lucide-react";

const TABS = [
  ["monitor", "Monitor"],
  ["registro", "Registro"],
  ["analisi", "Analisi"],
  ["clip", "Clip"],
  ["allarmi", "Allarmi"],
];

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span data-testid="system-clock" className="font-mono text-xs tabular-nums text-gray-400">{now.toLocaleDateString("it-IT")} {now.toLocaleTimeString("it-IT")}</span>;
}

export default function AppHeader({ tab, setTab, modelOk, alertCount, onSettings }) {
  const [installEvt, setInstallEvt] = useState(null);
  useEffect(() => {
    const h = (e) => { e.preventDefault(); setInstallEvt(e); };
    window.addEventListener("beforeinstallprompt", h);
    return () => window.removeEventListener("beforeinstallprompt", h);
  }, []);
  const install = async () => {
    if (!installEvt) return;
    installEvt.prompt();
    await installEvt.userChoice;
    setInstallEvt(null);
  };

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-6 border-b border-white/10 bg-app/90 px-4 backdrop-blur-xl md:px-6">
      <div className="flex items-center gap-2.5">
        <div className="grid h-8 w-8 place-items-center rounded border border-emerald-500/40 bg-emerald-500/10"><ShieldHalf className="h-4 w-4 text-emerald-400" /></div>
        <div className="leading-none">
          <div className="font-heading text-[15px] font-bold tracking-[0.12em] text-gray-100">SENTINEL<span className="text-emerald-400">·AI</span></div>
          <div className="font-mono text-[9px] uppercase tracking-[0.25em] text-gray-500">Vision Guard</div>
        </div>
      </div>
      <nav className="flex gap-1">
        {TABS.map(([id, label]) => (
          <button key={id} data-testid={`nav-tab-${id}`} onClick={() => setTab(id)}
            className={`relative rounded px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider transition-colors ${tab === id ? "text-emerald-400" : "text-gray-400 hover:text-gray-100"}`}>
            {label}
            {id === "allarmi" && alertCount > 0 && (
              <span data-testid="alert-notification-badge" className="absolute -right-1 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[9px] text-[#fff]">{alertCount}</span>
            )}
            {tab === id && <span className="absolute inset-x-2 -bottom-[11px] h-[2px] bg-emerald-400" />}
          </button>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-4">
        <span data-testid="model-status" className="hidden items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-gray-400 md:flex">
          <span className={`h-2 w-2 rounded-full ${modelOk ? "bg-emerald-400 shadow-[0_0_8px_#10B981]" : "bg-amber-400"}`} />
          {modelOk ? "YOLOv8 pronto" : "Motore in avvio"}
        </span>
        <span className="hidden lg:inline"><Clock /></span>
        {installEvt && (
          <button data-testid="pwa-install-button" onClick={install} className="flex items-center gap-1.5 rounded border border-cyan-500/40 bg-cyan-500/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-cyan-300 hover:bg-cyan-500/20">
            <Download className="h-3.5 w-3.5" /> Installa app
          </button>
        )}
        <span data-testid="user-menu"><UserButton /></span>
        <button data-testid="settings-open-button" onClick={onSettings} className="rounded p-2 text-gray-400 transition-colors hover:bg-white/5 hover:text-gray-100"><Settings2 className="h-4 w-4" /></button>
      </div>
    </header>
  );
}
