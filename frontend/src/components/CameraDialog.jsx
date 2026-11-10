import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ZoneFields } from "@/components/ZoneDialog";
import { SOURCE_META } from "@/components/CameraTile";
import { CATEGORY } from "@/lib/api";

// 1.0.23: allarmi di QUESTA telecamera. alarm_categories vuoto = tutte le categorie.
function AlarmFields({ d, setD }) {
  const all = Object.keys(CATEGORY);
  const active = d.alarm_categories?.length ? d.alarm_categories : all;
  const on = d.alarm_enabled !== false;
  const toggle = (k) => {
    const next = active.includes(k) ? active.filter((x) => x !== k) : all.filter((x) => active.includes(x) || x === k);
    if (!next.length) return;                       // almeno una: per non avere allarmi c'è l'interruttore
    setD({ ...d, alarm_categories: next.length === all.length ? [] : next });
  };
  return (
    <div className="space-y-3 rounded-md border border-white/10 p-3" data-testid="camera-alarm">
      <label className="flex items-center gap-2">
        <Switch data-testid="camera-alarm-switch" checked={on} onCheckedChange={(v) => setD({ ...d, alarm_enabled: v })} />
        <span className="text-xs text-gray-400"><span className="font-semibold text-gray-200">Allarme attivo</span>: {on
          ? "questa telecamera dà gli allarmi impostati (regole e zone), con Telegram e clip."
          : "spento: la telecamera guarda e registra gli eventi, ma non dà allarmi, Telegram né clip."}</span>
      </label>
      <div className="flex flex-wrap items-center gap-2" style={on ? undefined : { opacity: 0.45 }}>
        <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">Allarmi per</span>
        {Object.entries(CATEGORY).map(([k, c]) => (
          <button key={k} type="button" data-testid={`camera-alarm-cat-${k}`} onClick={() => toggle(k)} className="rounded border px-2 py-0.5 font-mono text-[11px]"
            style={active.includes(k) ? { borderColor: c.color, color: c.color, background: `${c.color}1A` } : { borderColor: "rgb(var(--c-white) / 0.1)", color: "rgb(var(--g400))", textDecoration: "line-through" }}>
            {c.label}
          </button>
        ))}
        {active.length === all.length && <span className="font-mono text-[10px] text-gray-500">(tutti)</span>}
      </div>
      <p className="font-mono text-[10px] text-gray-500">Tocca una categoria per toglierla dagli allarmi di questa telecamera (es. Animali in Sala): continuerà a vederla e a registrarla, senza avvisare.</p>
    </div>
  );
}

const NEW_CAMERA = { name: "", type: "nvr", url: "", device_id: "", nvr_brand: "hikvision", nvr_host: "", nvr_port: 554, nvr_username: "", nvr_password: "", nvr_channel: 1, nvr_stream: "sub", nvr_path: "", prova: false, alarm_enabled: true, alarm_categories: [], line: { enabled: true, x1: 0.08, y1: 0.62, x2: 0.92, y2: 0.62, invert: false }, zones: [] };

const inp = "h-9 border-white/10 bg-black/30 font-mono text-xs";

function NvrFields({ d, setD }) {
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  return (
    <div className="space-y-1.5 rounded-md border border-white/10 p-3" data-testid="nvr-fields">
      <div className="grid grid-cols-3 gap-2 font-mono text-[9px] uppercase tracking-widest text-gray-500"><span>Marca</span><span className="col-span-2">Indirizzo IP / host</span></div>
      <div className="grid grid-cols-3 gap-2">
        <Select value={d.nvr_brand} onValueChange={(v) => setD({ ...d, nvr_brand: v })}>
          <SelectTrigger data-testid="nvr-brand-select" className={inp}><SelectValue /></SelectTrigger>
          <SelectContent className="border-white/10 bg-slate-900/95 backdrop-blur-md">
            <SelectItem value="hikvision">Hikvision / HiLook</SelectItem>
            <SelectItem value="dahua">Dahua / Imou</SelectItem>
            <SelectItem value="custom">Altro (percorso RTSP)</SelectItem>
          </SelectContent>
        </Select>
        <Input data-testid="nvr-host-input" value={d.nvr_host} onChange={set("nvr_host")} placeholder="IP NVR es. 192.168.1.64" className={`${inp} col-span-2`} />
      </div>
      <div className="grid grid-cols-2 gap-2 font-mono text-[9px] uppercase tracking-widest text-gray-500"><span>Utente</span><span>Password</span></div>
      <div className="grid grid-cols-2 gap-2">
        <Input data-testid="nvr-username-input" value={d.nvr_username} onChange={set("nvr_username")} placeholder="Utente NVR" autoComplete="off" className={inp} />
        <Input data-testid="nvr-password-input" type="password" value={d.nvr_password} onChange={set("nvr_password")} autoComplete="new-password"
          placeholder={d.has_nvr_password ? "•••• salvata" : "Password NVR"} className={inp} />
      </div>
      <div className="grid grid-cols-3 gap-2 font-mono text-[9px] uppercase tracking-widest text-gray-500"><span>Canale</span><span>Porta RTSP</span><span>Flusso</span></div>
      <div className="grid grid-cols-3 gap-2">
        <Input data-testid="nvr-channel-input" type="number" min={1} max={256} value={d.nvr_channel} onChange={(e) => setD({ ...d, nvr_channel: Number(e.target.value) || 1 })} placeholder="Canale" className={inp} />
        <Input data-testid="nvr-port-input" type="number" min={1} max={65535} value={d.nvr_port} onChange={(e) => setD({ ...d, nvr_port: Number(e.target.value) || 554 })} placeholder="Porta RTSP" className={inp} />
        <Select value={d.nvr_stream} onValueChange={(v) => setD({ ...d, nvr_stream: v })}>
          <SelectTrigger data-testid="nvr-stream-select" className={inp}><SelectValue /></SelectTrigger>
          <SelectContent className="border-white/10 bg-slate-900/95 backdrop-blur-md">
            <SelectItem value="sub">Flusso secondario (consigliato)</SelectItem>
            <SelectItem value="main">Flusso principale (alta qualità)</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {d.nvr_brand === "custom" && <Input data-testid="nvr-path-input" value={d.nvr_path} onChange={set("nvr_path")} placeholder="Percorso, es. /h264/ch1/sub/av_stream" className={inp} />}
      <p className="font-mono text-[10px] text-gray-500">Canale = numero della telecamera sull'NVR. La password resta sul server e non viene mai mostrata; lascia il campo vuoto per non cambiarla.{d.url ? ` Indirizzo: ${d.url}` : ""}</p>
    </div>
  );
}

function SourceFields({ d, setD }) {
  const [devices, setDevices] = useState([]);
  useEffect(() => {
    if (d.type === "webcam") navigator.mediaDevices?.enumerateDevices?.().then((x) => setDevices(x.filter((v) => v.kind === "videoinput" && v.deviceId)));
  }, [d.type]);
  return (
    <>
      <div className="grid grid-cols-5 gap-1 rounded-md border border-white/10 bg-black/30 p-0.5">
        {Object.entries(SOURCE_META).map(([k, { label, icon: Icon }]) => (
          <button key={k} type="button" data-testid={`camera-type-${k}`} onClick={() => setD({ ...d, type: k })}
            className={`flex items-center justify-center gap-1.5 rounded px-2 py-1.5 font-mono text-[11px] uppercase ${d.type === k ? "bg-emerald-500/15 text-emerald-400" : "text-gray-400 hover:text-gray-100"}`}>
            <Icon className="h-3.5 w-3.5" /> {label}
          </button>
        ))}
      </div>
      {d.type === "nvr" && <NvrFields d={d} setD={setD} />}
      {d.type === "rtsp" && (
        <Input data-testid="camera-url-input" value={d.url} onChange={(e) => setD({ ...d, url: e.target.value })}
          placeholder="rtsp://utente:password@192.168.1.20:554/stream1" className="h-9 border-white/10 bg-black/30 font-mono text-xs" />
      )}
      {d.type === "webcam" && (
        <Select value={d.device_id || "default"} onValueChange={(v) => setD({ ...d, device_id: v === "default" ? "" : v })}>
          <SelectTrigger data-testid="camera-device-select" className="h-9 border-white/10 bg-black/30 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent className="border-white/10 bg-slate-900/95 backdrop-blur-md">
            <SelectItem value="default">Webcam predefinita</SelectItem>
            {devices.map((v, i) => <SelectItem key={v.deviceId} value={v.deviceId}>{v.label || `Telecamera ${i + 1}`}</SelectItem>)}
          </SelectContent>
        </Select>
      )}
      {d.type === "file" && <p className="font-mono text-[11px] text-gray-500">Il file video verrà scelto ogni volta che premi Avvia.</p>}
      {d.type === "demo" && <p className="font-mono text-[11px] text-gray-500">Video di esempio: strada con pedoni, bici e auto.</p>}
    </>
  );
}

export default function CameraDialog({ camera, onClose, onSave, onDelete }) {
  const isNew = camera === "new";
  const [d, setD] = useState(NEW_CAMERA);
  useEffect(() => { if (camera) setD(isNew ? NEW_CAMERA : camera); }, [camera, isNew]);
  const valid = d.name.trim() && (d.type !== "rtsp" || d.url.trim()) && d.zones.every((z) => z.name.trim());
  const setZone = (i, z) => setD({ ...d, zones: d.zones.map((x, j) => (j === i ? z : x)) });

  return (
    <Dialog open={!!camera} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="camera-dialog" className="max-h-[90vh] max-w-2xl overflow-y-auto border-white/10 bg-raised text-gray-100">
        <DialogHeader><DialogTitle className="font-heading">{isNew ? "Aggiungi telecamera" : "Configura telecamera"}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <Input data-testid="camera-name-input" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} placeholder="Nome (es. Ingresso principale)" className="h-9 border-white/10 bg-black/30" />
          <SourceFields d={d} setD={setD} />
          <label className="flex items-center gap-2 rounded-md border border-white/10 p-3" data-testid="camera-prova">
            <Switch data-testid="camera-prova-switch" checked={!!d.prova} onCheckedChange={(v) => setD({ ...d, prova: v })} />
            <span className="text-xs text-gray-400"><span className="font-semibold text-gray-200">Telecamera di prova</span>: l'IA analizza e conta, ma non manda mai allarmi, foto su Telegram né clip (per esempio una webcam pubblica del traffico).</span>
          </label>
          {!d.prova && <AlarmFields d={d} setD={setD} />}
          {d.type === "nvr" && !d.nvr_host.trim() && (
            <p data-testid="nvr-host-missing-warning" className="font-mono text-[11px] text-amber-400">Senza indirizzo NVR la telecamera verrà salvata come disattivata.</p>
          )}
          {!isNew && (
            <div className="space-y-3">
              <p className="font-mono text-[11px] uppercase tracking-wider text-gray-400">Zone monitorate ({d.zones.length})</p>
              {d.zones.length === 0 && <p className="text-sm text-gray-500">Nessuna zona. Usa "Disegna zona" sull'immagine per crearne una.</p>}
              {d.zones.map((z, i) => (
                <div key={z.id} className="space-y-3 rounded-md border border-white/10 p-3" data-testid={`zone-item-${i}`}>
                  <div className="flex items-center gap-2">
                    <Switch data-testid={`zone-${i}-enabled`} checked={z.enabled} onCheckedChange={(v) => setZone(i, { ...z, enabled: v })} />
                    <span className="text-xs text-gray-400">{z.points.length} vertici</span>
                    <Button data-testid={`zone-${i}-delete`} variant="ghost" onClick={() => setD({ ...d, zones: d.zones.filter((_, j) => j !== i) })} className="ml-auto h-8 px-2 text-gray-500 hover:text-red-400"><Trash2 className="h-4 w-4" /></Button>
                  </div>
                  <ZoneFields zone={z} onChange={(nz) => setZone(i, nz)} prefix={`zone-${i}`} />
                </div>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2 pt-2">
            {!isNew && (
              <Button data-testid="camera-delete-button" variant="ghost" className="text-red-400 hover:text-red-300"
                onClick={() => window.confirm(`Eliminare la telecamera "${camera.name}"?`) && onDelete(camera)}>
                <Trash2 className="mr-1 h-4 w-4" /> Elimina
              </Button>
            )}
            <Button data-testid="camera-dialog-cancel" variant="ghost" className="ml-auto" onClick={onClose}>Annulla</Button>
            <Button data-testid="camera-save-button" disabled={!valid} onClick={() => onSave(d)} className="bg-emerald-500 text-[#04130D] hover:bg-emerald-400">Salva</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
