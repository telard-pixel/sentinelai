import { useEffect, useRef, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { errorText, http } from "@/lib/api";

// 1.0.12 (richiesta di Roberto): aggiornare SentinelAI dall'app, senza riscaricare l'installer a mano.
// Il server scarica la versione nuova firmata e la installa; SentinelAI si riavvia da solo e la pagina si ricarica.
const IN_CORSO = ["scarico", "installo", "richiesto"];

export default function UpdateSection() {
  const [info, setInfo] = useState(null);
  const [checking, setChecking] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [run, setRun] = useState(null); // { target, since, msg, pct, restarting }
  const timer = useRef(null);

  const check = async (forza = false) => {
    setChecking(true);
    try {
      setInfo((await http.get("/aggiornamento", { params: { forza } })).data);
    } catch (e) {
      setInfo({ errore: errorText(e) || "controllo non riuscito" });
    } finally {
      setChecking(false);
    }
  };
  useEffect(() => { check(false); return () => clearTimeout(timer.current); }, []);

  const poll = (target, since) => {
    const step = async () => {
      if (Date.now() - since > 6 * 60 * 1000) {
        setRun(null);
        toast.error("Aggiornamento senza risposta", { description: "Riapri le Impostazioni per vedere la versione installata." });
        return;
      }
      try {
        const v = (await http.get("/version")).data?.version;
        if (v === target.replace(/^v/, "")) {
          toast.success(`SentinelAI aggiornato alla ${v}`);
          setTimeout(() => window.location.reload(), 1500);
          return;
        }
        const s = (await http.get("/aggiornamento/stato")).data;
        const srv = s.servizio;
        const srvNow = srv && srv.tag === target && Date.parse(srv.ora) >= since - 5000;
        if (s.fase === "errore" || (srvNow && srv.fase === "errore")) {
          setRun(null);
          toast.error("Aggiornamento non riuscito", { description: (srvNow && srv.fase === "errore" ? srv.messaggio : s.messaggio) || "" });
          check(true);
          return;
        }
        setRun((r) => r && { ...r, restarting: false, msg: (srvNow && srv.messaggio) || s.messaggio, pct: s.percentuale });
      } catch {
        setRun((r) => r && { ...r, restarting: true });   // il server si sta riavviando
      }
      timer.current = setTimeout(step, 2000);
    };
    timer.current = setTimeout(step, 1500);
  };

  const install = async () => {
    if (!confirm) { setConfirm(true); return; }
    setConfirm(false);
    const since = Date.now();
    try {
      const s = (await http.post("/aggiornamento/installa")).data;
      setRun({ target: info.ultima, since, msg: s.messaggio, pct: s.percentuale, restarting: false });
      poll(info.ultima, since);
    } catch (e) {
      toast.error("Aggiornamento non partito", { description: errorText(e) });
      check(true);
    }
  };

  let body;
  if (run) {
    body = (
      <div data-testid="update-progress" className="space-y-2">
        <p className="text-xs text-gray-300">{run.restarting ? "SentinelAI si sta riavviando…" : run.msg || "Aggiornamento in corso…"}</p>
        {run.pct != null && !run.restarting && (
          <div className="h-1.5 overflow-hidden rounded bg-white/10"><div className="h-full bg-emerald-500 transition-all" style={{ width: `${run.pct}%` }} /></div>
        )}
        <p className="text-[11px] text-gray-500">Le telecamere si fermano per meno di un minuto. Non serve fare niente: la pagina si ricarica da sola.</p>
      </div>
    );
  } else if (!info) {
    body = <p className="text-xs text-gray-500">Controllo…</p>;
  } else {
    const busy = info.stato && IN_CORSO.includes(info.stato.fase);
    body = (
      <div className="space-y-2">
        <p data-testid="update-status" className="text-xs text-gray-300">
          {info.errore
            ? `Non riesco a controllare: ${info.errore}.`
            : info.disponibile
              ? `È disponibile la versione ${info.ultima.replace(/^v/, "")} (installata: ${info.attuale}).`
              : info.ultima
                ? `SentinelAI è aggiornato (versione ${info.attuale}).`
                : "Nessuna versione pubblicata."}
        </p>
        {!info.modo && !info.errore && <p className="text-[11px] text-gray-500">Qui l'aggiornamento dall'app non è disponibile: si aggiorna a mano.</p>}
        {info.disponibile && info.note && <p className="whitespace-pre-line text-[11px] text-gray-500">{info.note}</p>}
        <div className="flex flex-wrap items-center gap-2">
          {info.disponibile && (
            <Button data-testid="update-install-button" size="sm" disabled={busy} onClick={install} onBlur={() => setConfirm(false)}
              className="h-8 gap-1 bg-emerald-500 text-xs text-[#04130D] hover:bg-emerald-400">
              <Download className="h-3.5 w-3.5" /> {confirm ? "Conferma: SentinelAI si riavvia" : `Aggiorna alla ${info.ultima.replace(/^v/, "")}`}
            </Button>
          )}
          <Button data-testid="update-check-button" size="sm" variant="outline" disabled={checking} onClick={() => check(true)}
            className="h-8 gap-1 border-white/10 bg-transparent text-xs">
            <RefreshCw className={`h-3.5 w-3.5 ${checking ? "animate-spin" : ""}`} /> Controlla ora
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-3 rounded-md border border-white/10 bg-black/20 p-4" data-testid="update-section">
      <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-gray-400"><Download className="h-3.5 w-3.5" /> Aggiornamenti</p>
      {body}
    </div>
  );
}
