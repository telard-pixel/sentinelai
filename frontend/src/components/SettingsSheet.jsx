import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import { CATEGORY, http } from "@/lib/api";
import StorageSection from "@/components/StorageSection";
import ThemeSelector from "@/components/ThemeSelector";
import UsersSection from "@/components/UsersSection";
import LogSection from "@/components/LogSection";
import VersionLine from "@/components/VersionLine";
import PasswordSection from "@/components/PasswordSection";
import ClipsFolderSection from "@/components/ClipsFolderSection";
import { Switch } from "@/components/ui/switch";

function SliderRow({ testid, label, value, min, max, step, onChange, fmt }) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between font-mono text-[11px] uppercase tracking-wider text-gray-400">
        <span>{label}</span><span className="text-emerald-400" data-testid={`${testid}-value`}>{fmt(value)}</span>
      </div>
      <Slider data-testid={testid} value={[value]} min={min} max={max} step={step} onValueChange={([v]) => onChange(v)} />
    </div>
  );
}

export default function SettingsSheet({ open, onOpenChange, settings, onSave }) {
  const [d, setD] = useState(settings);
  useEffect(() => setD(settings), [settings, open]);
  const { data: classes = [] } = useQuery({ queryKey: ["classes"], queryFn: () => http.get("/classes").then((r) => r.data), staleTime: Infinity });
  if (!d) return null;
  const toggle = (id) => setD({ ...d, classes: d.classes.includes(id) ? d.classes.filter((x) => x !== id) : [...d.classes, id] });
  const setCat = (cat, on) => {
    const ids = classes.filter((c) => c.category === cat).map((c) => c.id);
    setD({ ...d, classes: on ? [...new Set([...d.classes, ...ids])] : d.classes.filter((x) => !ids.includes(x)) });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent data-testid="settings-sheet" className="w-full overflow-y-auto border-white/10 bg-raised text-gray-100 sm:max-w-lg">
        <SheetHeader><SheetTitle className="font-heading text-gray-100">Impostazioni</SheetTitle></SheetHeader>
        <div className="mt-6 space-y-6">
          <ThemeSelector />
          <PasswordSection />
          <UsersSection />
          <div className="space-y-4 rounded-md border border-white/10 bg-black/20 p-4" data-testid="clips-section">
            <label className="flex items-center justify-between font-mono text-[11px] uppercase tracking-wider text-gray-400">
              Clip video degli allarmi
              <Switch data-testid="clips-enabled-toggle" checked={d.clips_enabled ?? true} onCheckedChange={(v) => setD({ ...d, clips_enabled: v })} />
            </label>
            {(d.clips_enabled ?? true) && (
              <>
                <SliderRow testid="clip-pre-slider" label="Secondi prima dell'allarme" value={d.clip_pre_seconds ?? 5} min={1} max={15} step={1} fmt={(v) => `${v}s`} onChange={(v) => setD({ ...d, clip_pre_seconds: v })} />
                <SliderRow testid="clip-post-slider" label="Secondi dopo l'allarme" value={d.clip_post_seconds ?? 5} min={1} max={20} step={1} fmt={(v) => `${v}s`} onChange={(v) => setD({ ...d, clip_post_seconds: v })} />
                <p className="text-[11px] text-gray-500">Allarmi ravvicinati vengono uniti nella stessa clip (massimo 30 secondi, secondi precedenti inclusi).</p>
              </>
            )}
          </div>
          <ClipsFolderSection />
          <p className="font-mono text-[11px] uppercase tracking-wider text-gray-400">Motore AI</p>
          <SliderRow testid="confidence-slider" label="Soglia confidenza" value={d.conf} min={0.1} max={0.95} step={0.05} fmt={(v) => `${Math.round(v * 100)}%`} onChange={(v) => setD({ ...d, conf: v })} />
          <SliderRow testid="iou-slider" label="Soglia IOU (sovrapposizione)" value={d.iou} min={0.1} max={0.9} step={0.05} fmt={(v) => v.toFixed(2)} onChange={(v) => setD({ ...d, iou: v })} />
          <SliderRow testid="transit-distance-slider" label="Spostamento minimo per transito" value={d.transit_min_dist} min={0.05} max={0.6} step={0.01} fmt={(v) => `${Math.round(v * 100)}% inquadratura`} onChange={(v) => setD({ ...d, transit_min_dist: v })} />
          <div className="space-y-4">
            <p className="font-mono text-[11px] uppercase tracking-wider text-gray-400">Oggetti da rilevare ({d.classes.length}/80)</p>
            {Object.entries(CATEGORY).map(([cat, meta]) => {
              const list = classes.filter((c) => c.category === cat);
              const all = list.length > 0 && list.every((c) => d.classes.includes(c.id));
              return (
                <div key={cat} className="space-y-2" data-testid={`classes-group-${cat}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium" style={{ color: meta.color }}>{meta.label}</span>
                    <button data-testid={`classes-toggle-all-${cat}`} onClick={() => setCat(cat, !all)} className="font-mono text-[10px] uppercase text-gray-500 hover:text-gray-200">{all ? "Deseleziona" : "Seleziona tutti"}</button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {list.map((c) => {
                      const on = d.classes.includes(c.id);
                      return (
                        <button key={c.id} data-testid={`class-chip-${c.id}`} onClick={() => toggle(c.id)}
                          className="rounded border px-2 py-0.5 text-xs capitalize transition-colors"
                          style={on ? { borderColor: meta.color, color: meta.color, background: `${meta.color}14` } : { borderColor: "rgb(var(--c-white) / 0.08)", color: "rgb(var(--g500))" }}>
                          {c.name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
          <StorageSection days={d.retention_days ?? 30} onDays={(v) => setD({ ...d, retention_days: v })} />
          <LogSection />
          <Button data-testid="settings-save-button" onClick={() => { onSave(d); onOpenChange(false); }} className="w-full bg-emerald-500 font-mono text-xs uppercase tracking-wider text-[#04130D] hover:bg-emerald-400">Salva impostazioni</Button>
          <VersionLine />
        </div>
      </SheetContent>
    </Sheet>
  );
}
