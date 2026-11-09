import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { http } from "@/lib/api";

// 1.0.19: monitor risorse in tempo reale (richiesta di Roberto). Il server prende un campione ogni 2 s
// (GET /api/risorse); qui si chiede solo mentre la finestra è aperta. Colori e larghezze in stile diretto:
// il CSS di Tailwind è precompilato (index.css) e le classi nuove non esisterebbero.

const VERDE = "#10B981", CIANO = "#06B6D4", AMBRA = "#F59E0B", ROSSO = "#EF4444";
const colore = (p) => (p == null ? "#6B7280" : p >= 85 ? ROSSO : p >= 60 ? AMBRA : VERDE);
const num = (v, suf = "") => (v == null ? "—" : `${v}${suf}`);

function Barra({ valore }) {
  const p = Math.max(0, Math.min(100, valore ?? 0));
  return (
    <div className="mt-2 h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
      <div className="h-full rounded-full" style={{ width: `${p}%`, background: colore(valore), transition: "width .4s" }} />
    </div>
  );
}

function Riquadro({ titolo, valore, sotto, barra, testid }) {
  return (
    <div className="rounded-md border border-white/10 p-3" data-testid={testid}>
      <p className="font-mono text-[10px] uppercase tracking-wider text-gray-500">{titolo}</p>
      <p className="font-heading text-xl font-semibold tabular-nums text-gray-100">{valore}</p>
      {sotto && <p className="font-mono text-[10px] text-gray-500">{sotto}</p>}
      {barra !== undefined && <Barra valore={barra} />}
    </div>
  );
}

// Andamento degli ultimi 2 minuti: linea del programma (in % di tutti i core) e occupazione dell'IA.
function Grafico({ storia, core }) {
  const W = 600, H = 90;
  if (storia.length < 2) return <p className="font-mono text-[11px] text-gray-500">Raccolgo i primi campioni…</p>;
  const linea = (f) => storia.map((s, i) => {
    const v = Math.max(0, Math.min(100, f(s) ?? 0));
    return `${(i / (storia.length - 1)) * W},${H - (v / 100) * H}`;
  }).join(" ");
  return (
    <div className="rounded-md border border-white/10 p-3">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: 90, display: "block" }} role="img" aria-label="Andamento degli ultimi 2 minuti">
        {[25, 50, 75].map((y) => <line key={y} x1="0" x2={W} y1={H - (y / 100) * H} y2={H - (y / 100) * H} stroke="rgba(255,255,255,0.07)" strokeWidth="1" />)}
        <polyline fill="none" stroke={CIANO} strokeWidth="2" vectorEffect="non-scaling-stroke" points={linea((s) => s.ia_occupata)} />
        <polyline fill="none" stroke={VERDE} strokeWidth="2" vectorEffect="non-scaling-stroke" points={linea((s) => (s.cpu_programma == null ? null : s.cpu_programma / (core || 1)))} />
        {storia.some((s) => s.cpu_sistema != null) && (
          <polyline fill="none" stroke={AMBRA} strokeWidth="1.5" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" points={linea((s) => s.cpu_sistema)} />
        )}
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 font-mono text-[10px] text-gray-400">
        <span><span style={{ color: VERDE }}>■</span> SentinelAI (% di tutto il processore)</span>
        <span><span style={{ color: AMBRA }}>■</span> tutto il sistema</span>
        <span><span style={{ color: CIANO }}>■</span> IA occupata</span>
        <span className="ml-auto">ultimi 2 minuti</span>
      </div>
    </div>
  );
}

export default function ResourcesDialog({ open, onClose }) {
  const [dati, setDati] = useState(null);
  const [errore, setErrore] = useState("");

  useEffect(() => {
    if (!open) return undefined;
    let vivo = true;
    const leggi = () => http.get("/risorse")
      .then((r) => { if (vivo) { setDati(r.data); setErrore(""); } })
      .catch(() => { if (vivo) setErrore("Il server non risponde."); });
    leggi();
    const t = setInterval(leggi, 2000);
    return () => { vivo = false; clearInterval(t); };
  }, [open]);

  const u = dati?.ultimo || {};
  const core = u.core || 1;
  const cpuProg = u.cpu_programma;
  const tel = u.telecamere || [];

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="resources-dialog" className="max-h-[90vh] max-w-2xl overflow-y-auto border-white/10 bg-raised text-gray-100">
        <DialogHeader><DialogTitle className="font-heading">Risorse in tempo reale</DialogTitle></DialogHeader>
        {errore && <p className="font-mono text-[11px] text-amber-400">{errore}</p>}
        {!dati ? <p className="text-sm text-gray-500">Carico…</p> : (
          <div className="space-y-4">
            <p className="font-mono text-[11px] text-gray-400" data-testid="resources-engine">Motore IA: <span className="text-gray-200">{u.motore || "—"}</span> · {core} core</p>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              <Riquadro testid="res-cpu-programma" titolo="Processore SentinelAI" valore={num(cpuProg == null ? null : Math.round(cpuProg / core), "%")}
                sotto={cpuProg == null ? "" : `${cpuProg}% di un core`} barra={cpuProg == null ? null : cpuProg / core} />
              <Riquadro testid="res-cpu-sistema" titolo="Processore sistema" valore={num(u.cpu_sistema == null ? null : Math.round(u.cpu_sistema), "%")}
                sotto="tutti i programmi" barra={u.cpu_sistema} />
              <Riquadro testid="res-mem" titolo="Memoria" valore={num(u.mem_programma, " MB")}
                sotto={u.mem_totale ? `sistema ${u.mem_sistema} / ${u.mem_totale} MB` : ""}
                barra={u.mem_totale ? (u.mem_sistema / u.mem_totale) * 100 : undefined} />
              <Riquadro testid="res-ia-sec" titolo="Analisi IA" valore={num(u.ia_al_secondo, "/s")} sotto="tutte le telecamere" />
              <Riquadro testid="res-ia-ms" titolo="Durata analisi" valore={num(u.ia_ms, " ms")} sotto="media degli ultimi 2 s" />
              <Riquadro testid="res-ia-occ" titolo="IA occupata" valore={num(u.ia_occupata, "%")} sotto="tempo passato nel motore" barra={u.ia_occupata} />
            </div>
            <Grafico storia={dati.storia || []} core={core} />
            <div className="space-y-1.5">
              <p className="font-mono text-[11px] uppercase tracking-wider text-gray-400">Telecamere sorvegliate dal server ({tel.length})</p>
              {tel.length === 0 && <p className="text-sm text-gray-500">Nessuna telecamera accesa.</p>}
              {tel.length > 0 && (
                <div className="overflow-hidden rounded-md border border-white/10">
                  <div className="grid grid-cols-4 gap-2 border-b border-white/10 px-3 py-1.5 font-mono text-[9px] uppercase tracking-widest text-gray-500">
                    <span>Telecamera</span><span>Ricevuti</span><span>Elaborati</span><span>Analisi IA</span>
                  </div>
                  {tel.map((c) => (
                    <div key={c.id} className="grid grid-cols-4 gap-2 border-b border-white/10 px-3 py-1.5 font-mono text-xs tabular-nums text-gray-300" data-testid={`res-cam-${c.id}`}>
                      <span className="truncate text-gray-100" title={c.nome}>
                        <span style={{ color: c.stato === "live" ? VERDE : c.stato === "error" ? ROSSO : AMBRA }}>● </span>{c.nome}
                        {c.prova && <span style={{ color: "#7DD3FC" }}> · prova</span>}
                      </span>
                      <span>{num(c.ricevuti, " fps")}</span>
                      <span>{num(c.elaborati, " fps")}</span>
                      <span>{num(c.analizzati, "/s")}{c.spettatori > 0 && <span className="text-gray-500"> · 👁 {c.spettatori}</span>}</span>
                    </div>
                  ))}
                </div>
              )}
              <p className="font-mono text-[10px] text-gray-500">Ricevuti = fotogrammi che arrivano dalla telecamera (tutti vanno decodificati). Elaborati = giri di controllo del movimento. Analisi IA = fotogrammi passati all'intelligenza artificiale.</p>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
