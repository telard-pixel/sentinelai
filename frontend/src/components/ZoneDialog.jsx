import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { CATEGORY } from "@/lib/api";

export function ZoneFields({ zone, onChange, prefix }) {
  const set = (patch) => onChange({ ...zone, ...patch });
  const toggleCat = (c) => set({ categories: zone.categories.includes(c) ? zone.categories.filter((x) => x !== c) : [...zone.categories, c] });
  return (
    <div className="space-y-3">
      <Input data-testid={`${prefix}-name`} value={zone.name} onChange={(e) => set({ name: e.target.value })} placeholder="Nome zona" className="h-9 border-white/10 bg-black/30" />
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">Chi</span>
        {Object.entries(CATEGORY).map(([k, c]) => (
          <button key={k} type="button" data-testid={`${prefix}-cat-${k}`} onClick={() => toggleCat(k)} className="rounded border px-2 py-0.5 font-mono text-[11px]"
            style={zone.categories.includes(k) ? { borderColor: c.color, color: c.color, background: `${c.color}1A` } : { borderColor: "rgb(var(--c-white) / 0.1)", color: "rgb(var(--g400))" }}>
            {c.label}
          </button>
        ))}
        {zone.categories.length === 0 && <span className="font-mono text-[10px] text-gray-500">(chiunque)</span>}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <label className="flex items-center justify-between gap-2 rounded border border-white/5 bg-black/20 px-3 py-2 text-xs text-gray-300">
          Allarme all'ingresso
          <Switch data-testid={`${prefix}-alert-enter`} checked={zone.alert_on_enter} onCheckedChange={(v) => set({ alert_on_enter: v })} />
        </label>
        <label className="flex items-center justify-between gap-2 rounded border border-white/5 bg-black/20 px-3 py-2 text-xs text-gray-300">
          Allarme sosta oltre (s)
          <Input data-testid={`${prefix}-dwell`} type="number" min={0} max={3600} value={zone.dwell_seconds}
            onChange={(e) => set({ dwell_seconds: Math.max(0, Math.min(3600, parseInt(e.target.value || "0", 10))) })}
            className="h-7 w-20 border-white/10 bg-black/30 font-mono text-xs" />
        </label>
      </div>
      <p className="font-mono text-[10px] text-gray-500">0 secondi = nessun allarme di sosta. Il punto di riferimento è la base dell'oggetto (i piedi per le persone).</p>
    </div>
  );
}

export default function ZoneDialog({ zone, onSave, onCancel }) {
  const [d, setD] = useState(zone);
  useEffect(() => setD(zone), [zone]);
  return (
    <Dialog open={!!zone} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent data-testid="zone-dialog" className="max-w-lg border-white/10 bg-raised text-gray-100">
        <DialogHeader><DialogTitle className="font-heading">Nuova zona monitorata</DialogTitle></DialogHeader>
        {d && <ZoneFields zone={d} onChange={setD} prefix="zone-new" />}
        <div className="flex justify-end gap-2">
          <Button data-testid="zone-dialog-cancel" variant="ghost" onClick={onCancel}>Annulla</Button>
          <Button data-testid="zone-dialog-save" disabled={!d?.name?.trim()} onClick={() => onSave(d)} className="bg-emerald-500 text-[#04130D] hover:bg-emerald-400">Salva zona</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
