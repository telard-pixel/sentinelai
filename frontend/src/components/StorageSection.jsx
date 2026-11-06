import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Eraser } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { fmtDate, fmtTime, http } from "@/lib/api";

const OPTIONS = [[0, "Mai (conserva tutto)"], [1, "1 giorno"], [3, "3 giorni"], [7, "7 giorni"], [14, "14 giorni"], [30, "30 giorni"], [90, "90 giorni"], [180, "6 mesi"], [365, "1 anno"]];

export default function StorageSection({ days, onDays }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["storage"], queryFn: () => http.get("/storage").then((r) => r.data), refetchInterval: 15000 });
  const options = OPTIONS.some(([v]) => v === days) ? OPTIONS : [...OPTIONS, [days, `${days} giorni`]];
  const clean = async () => {
    if (!window.confirm(`Eliminare definitivamente eventi e screenshot più vecchi di ${days} giorni?`)) return;
    try {
      const r = await http.post("/storage/cleanup").then((x) => x.data);
      qc.invalidateQueries();
      toast.success("Pulizia completata", { description: `${r.events} eventi, ${r.snapshots} screenshot e ${r.clips ?? 0} clip eliminati` });
    } catch (e) {
      toast.error("Pulizia non riuscita", { description: e.message });
    }
  };
  return (
    <div className="space-y-3 rounded-md border border-white/10 bg-black/20 p-4" data-testid="storage-section">
      <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-gray-400"><Database className="h-3.5 w-3.5" /> Conservazione dati</p>
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-300">Elimina eventi, screenshot e clip più vecchi di</span>
        <Select value={String(days)} onValueChange={(v) => onDays(Number(v))}>
          <SelectTrigger data-testid="retention-select" className="ml-auto h-8 w-44 border-white/10 bg-black/30 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent className="border-white/10 bg-slate-900/95 backdrop-blur-md">
            {options.map(([v, l]) => <SelectItem key={v} value={String(v)}>{l}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-4 gap-2 font-mono text-xs">
        {[["Eventi", data?.events], ["Screenshot", data?.snapshots], ["Clip", data?.clips], ["Spazio", data ? `${Math.round((data.size_mb + (data.clips_files_mb || 0)) * 10) / 10} MB` : "—"]].map(([k, v]) => (
          <div key={k} className="rounded border border-white/5 bg-black/30 p-2" data-testid={`storage-${k.toLowerCase()}`}>
            <div className="text-[9px] uppercase tracking-widest text-gray-500">{k}</div><div className="mt-1 text-gray-100">{v ?? "—"}</div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 text-[11px] text-gray-500">
        <span data-testid="storage-last-cleanup">Ultima pulizia: {data?.last_cleanup ? `${fmtDate(data.last_cleanup)} ${fmtTime(data.last_cleanup)}` : "mai"} · automatica ogni ora</span>
        <Button data-testid="storage-cleanup-button" size="sm" variant="outline" onClick={clean} disabled={!days} className="ml-auto h-7 gap-1 border-white/10 bg-transparent text-xs"><Eraser className="h-3.5 w-3.5" /> Pulisci ora</Button>
      </div>
      <p className="text-[11px] text-gray-500">Salva le impostazioni prima di usare "Pulisci ora" se hai cambiato il periodo.</p>
    </div>
  );
}
