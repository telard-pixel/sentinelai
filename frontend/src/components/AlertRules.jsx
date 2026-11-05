import { useEffect, useState } from "react";
import { Plus, Trash2, BellRing, Volume2, MonitorSmartphone, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { CATEGORY } from "@/lib/api";
import TimeSelect from "@/components/TimeSelect";
import TelegramPanel from "@/components/TelegramPanel";
import { askNotifyPermission, beep, desktopNotify } from "@/lib/alarm";
import { toast } from "sonner";

function RuleRow({ rule, i, onChange, onDelete }) {
  const set = (patch) => onChange({ ...rule, ...patch });
  const toggleCat = (c) => set({ categories: rule.categories.includes(c) ? rule.categories.filter((x) => x !== c) : [...rule.categories, c] });
  return (
    <div className={`panel space-y-3 p-4 ${rule.enabled ? "" : "opacity-60"}`} data-testid={`alert-rule-${i}`}>
      <div className="flex items-center gap-3">
        <Switch data-testid={`alert-rule-${i}-enabled`} checked={rule.enabled} onCheckedChange={(v) => set({ enabled: v })} />
        <Input data-testid={`alert-rule-${i}-name`} value={rule.name} onChange={(e) => set({ name: e.target.value })} className="h-9 border-white/10 bg-black/30" />
        <Button data-testid={`alert-rule-${i}-delete`} variant="ghost" onClick={onDelete} className="h-9 px-2 text-gray-500 hover:text-red-400"><Trash2 className="h-4 w-4" /></Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">Se rilevo</span>
        {Object.entries(CATEGORY).map(([k, c]) => (
          <button key={k} data-testid={`alert-rule-${i}-cat-${k}`} onClick={() => toggleCat(k)}
            className="rounded border px-2.5 py-1 font-mono text-[11px] transition-colors"
            style={rule.categories.includes(k) ? { borderColor: c.color, color: c.color, background: `${c.color}1A` } : { borderColor: "rgb(var(--c-white) / 0.1)", color: "rgb(var(--g400))" }}>
            {c.label}
          </button>
        ))}
        {rule.categories.length === 0 && <span className="font-mono text-[10px] text-gray-500">(qualsiasi)</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">Evento</span>
        <Select value={rule.direction} onValueChange={(v) => set({ direction: v })}>
          <SelectTrigger data-testid={`alert-rule-${i}-direction`} className="h-8 w-44 border-white/10 bg-black/30 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent className="border-white/10 bg-slate-900/95 backdrop-blur-md">
            <SelectItem value="any">Qualsiasi passaggio</SelectItem>
            <SelectItem value="IN">Entrata nel varco</SelectItem>
            <SelectItem value="OUT">Uscita dal varco</SelectItem>
          </SelectContent>
        </Select>
        <span className="ml-2 font-mono text-[10px] uppercase tracking-widest text-gray-500">dalle</span>
        <TimeSelect testid={`alert-rule-${i}-start`} value={rule.start} onChange={(v) => set({ start: v })} />
        <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">alle</span>
        <TimeSelect testid={`alert-rule-${i}-end`} value={rule.end} onChange={(v) => set({ end: v })} />
      </div>
    </div>
  );
}

export default function AlertRules({ settings, onSave }) {
  const [draft, setDraft] = useState(settings);
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "unsupported");
  useEffect(() => setDraft(settings), [settings]);
  if (!draft) return null;
  const rules = draft.alert_rules;
  const setRules = (r) => setDraft({ ...draft, alert_rules: r });

  const test = () => {
    if (draft.sound) beep();
    if (draft.desktop_notifications) desktopNotify("ALLERTA · SentinelAI", "Test allarme: persona rilevata nell'area monitorata");
    toast.error("ALLERTA: test allarme", { description: "Persona rilevata nell'area monitorata" });
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4" data-testid="alerts-panel">
      <div className="flex items-center gap-3">
        <h2 className="mr-auto font-heading text-2xl font-semibold text-gray-100">Allarmi e notifiche</h2>
        <Button data-testid="alert-test-button" variant="outline" onClick={test} className="gap-2 border-amber-500/40 bg-transparent font-mono text-xs text-amber-300"><BellRing className="h-4 w-4" /> Prova allarme</Button>
        <Button data-testid="alerts-save-button" onClick={() => onSave(draft)} className="gap-2 bg-emerald-500 font-mono text-xs text-[#04130D] hover:bg-emerald-400"><Save className="h-4 w-4" /> Salva regole</Button>
      </div>
      <div className="panel grid gap-4 p-4 md:grid-cols-3">
        <label className="flex items-center gap-3 text-sm text-gray-300"><Volume2 className="h-4 w-4 text-amber-400" /> Sirena sonora
          <Switch data-testid="sound-toggle" className="ml-auto" checked={draft.sound} onCheckedChange={(v) => setDraft({ ...draft, sound: v })} /></label>
        <label className="flex items-center gap-3 text-sm text-gray-300"><MonitorSmartphone className="h-4 w-4 text-cyan-400" /> Notifiche Windows
          <Switch data-testid="desktop-notify-toggle" className="ml-auto" checked={draft.desktop_notifications} onCheckedChange={(v) => setDraft({ ...draft, desktop_notifications: v })} /></label>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          Permesso: <span data-testid="notify-permission-status" className="font-mono text-gray-200">{perm === "granted" ? "concesso" : perm === "denied" ? "negato" : "da richiedere"}</span>
          {perm !== "granted" && <Button data-testid="notify-permission-button" size="sm" variant="outline" className="ml-auto h-7 border-white/10 bg-transparent text-xs" onClick={async () => setPerm(await askNotifyPermission())}>Abilita</Button>}
        </div>
      </div>
      <TelegramPanel draft={draft} setDraft={setDraft} />
      {rules.map((r, i) => (
        <RuleRow key={r.id} rule={r} i={i} onChange={(nr) => setRules(rules.map((x, j) => (j === i ? nr : x)))} onDelete={() => setRules(rules.filter((_, j) => j !== i))} />
      ))}
      <button data-testid="alert-rule-add-button" onClick={() => setRules([...rules, { id: crypto.randomUUID(), name: "Nuova regola", enabled: true, categories: ["persona"], direction: "any", start: "00:00", end: "23:59" }])}
        className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-white/15 py-4 font-mono text-xs uppercase tracking-wider text-gray-400 transition-colors hover:border-emerald-500/50 hover:text-emerald-400">
        <Plus className="h-4 w-4" /> Aggiungi regola
      </button>
    </div>
  );
}
