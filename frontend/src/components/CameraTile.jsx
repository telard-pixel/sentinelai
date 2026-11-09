import { useEffect, useRef } from "react";
import { Play, Square, Maximize2, Minimize2, Settings2, Camera, Radio, Film, Clapperboard, Server, GripVertical } from "lucide-react";
import { useStream } from "@/hooks/useStream";
import LiveFeed from "@/components/LiveFeed";

export const SOURCE_META = {
  webcam: { label: "Webcam", icon: Camera },
  nvr: { label: "NVR", icon: Server },
  rtsp: { label: "RTSP / IP", icon: Radio },
  file: { label: "File video", icon: Film },
  demo: { label: "Demo", icon: Clapperboard },
};

function Stat({ label, value, color, testid }) {
  return (
    <div className="flex items-baseline gap-1.5" data-testid={testid}>
      <span className="font-mono text-[9px] uppercase tracking-widest text-gray-500">{label}</span>
      <span className="font-mono text-sm font-semibold tabular-nums" style={{ color }}>{value}</span>
    </div>
  );
}

export default function CameraTile({ camera, onEvents, onResult, onCameraChange, onMonitor, onEdit, expanded, onToggleExpand, compact, dragHandle, dragging }) {
  const stream = useStream(onEvents);
  const fileRef = useRef(null);
  const Icon = SOURCE_META[camera.type].icon;
  const isNet = ["rtsp", "nvr"].includes(camera.type);
  // 06/11/2026 (agente di prova): una telecamera di rete accesa sul server ma che non si collega mostrava solo
  // "Avvia" e non si poteva più fermare. Ora per RTSP/NVR "Ferma" c'è sempre quando il monitoraggio è acceso.
  const live = ["live", "connecting"].includes(stream.status.state) || (isNet && camera.monitor);

  useEffect(() => onResult(camera.id, stream.result), [camera.id, stream.result, onResult]);
  useEffect(() => () => onResult(camera.id, null), [camera.id, onResult]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => stream.send({ type: "reload" }), [camera]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => stream.stop(), [camera.type, camera.url, camera.device_id]);

  const start = (file) => stream.start({ cameraId: camera.id, source: camera.type, deviceId: camera.device_id, file });
  // RTSP/NVR: il server le controlla di continuo (anche a finestra chiusa). Avvia = accendi il monitoraggio sul
  // server (poi la finestra si collega da sola); Ferma = spegnilo davvero.
  const onStart = () => {
    if (camera.type === "file") return fileRef.current?.click();
    // 1.0.20: solo l'interruttore, non tutta la telecamera (una pagina vecchia riscriveva nome e indirizzo)
    if (isNet) return onMonitor(true).catch(() => {});
    return start();
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (isNet && camera.monitor && !camera.disabled) start(); }, [camera.id, camera.monitor, camera.type, camera.url]);
  const onStop = async () => {
    if (isNet) {
      await onMonitor(false).catch(() => {});
    }
    stream.stop();
  };

  return (
    <div className={`panel overflow-hidden ${expanded ? "col-span-full" : ""} ${dragging ? "camera-dragging" : ""}`} data-testid={`camera-tile-${camera.id}`} data-camera-id={camera.id}>
      <div className="flex items-center gap-2 border-b border-white/10 bg-raised px-3 py-2">
        {/* 1.0.20: maniglia per spostare la telecamera trascinandola (mouse e dito) */}
        {dragHandle && (
          <button type="button" {...dragHandle} data-testid={`camera-drag-${camera.id}`} title="Trascina per spostare (o Tab e frecce)" aria-label={`Sposta ${camera.name}`}
            style={{ marginLeft: -4 }} className="camera-drag-handle rounded p-0.5 text-gray-500 hover:bg-white/5 hover:text-gray-200"><GripVertical className="h-4 w-4" /></button>
        )}
        <Icon className="h-3.5 w-3.5 text-emerald-400" />
        <span className="truncate font-heading text-sm font-semibold text-gray-100" data-testid={`camera-name-${camera.id}`}>{camera.name}</span>
        {camera.prova && <span className="rounded px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider" style={{ background: "rgba(14,165,233,0.15)", color: "#7DD3FC" }} data-testid={`camera-prova-${camera.id}`}>prova</span>}
        <span className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[9px] uppercase text-gray-500">{SOURCE_META[camera.type].label}</span>
        <div className="ml-auto flex items-center gap-1">
          <input ref={fileRef} type="file" accept="video/*" className="hidden" data-testid={`camera-file-input-${camera.id}`}
            onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) start(f); }} />
          {camera.disabled ? (
            <span data-testid={`camera-disabled-${camera.id}`} className="rounded border border-amber-500/40 px-2 py-1 font-mono text-[10px] uppercase text-amber-400">Disattivata</span>
          ) : live ? (
            <button data-testid={`camera-stop-${camera.id}`} onClick={onStop} className="flex items-center gap-1 rounded bg-red-500/90 px-2.5 py-1 font-mono text-[10px] uppercase text-[#fff] hover:bg-red-500"><Square className="h-3 w-3" /> Ferma</button>
          ) : (
            <button data-testid={`camera-start-${camera.id}`} onClick={onStart} className="flex items-center gap-1 rounded bg-emerald-500 px-2.5 py-1 font-mono text-[10px] uppercase text-[#04130D] hover:bg-emerald-400"><Play className="h-3 w-3" /> Avvia</button>
          )}
          <button data-testid={`camera-expand-${camera.id}`} onClick={onToggleExpand} title={expanded ? "Riduci" : "Espandi"} className="rounded p-1.5 text-gray-400 hover:bg-white/5 hover:text-white">
            {expanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
          <button data-testid={`camera-edit-${camera.id}`} onClick={() => onEdit(camera)} title="Configura" className="rounded p-1.5 text-gray-400 hover:bg-white/5 hover:text-white"><Settings2 className="h-3.5 w-3.5" /></button>
        </div>
      </div>
      <LiveFeed stream={stream} camera={camera} onCameraChange={onCameraChange} compact={compact && !expanded} maxH={expanded || !compact ? "64vh" : undefined} />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-white/5 px-3 py-2">
        <Stat testid={`camera-in-${camera.id}`} label="Ingressi" value={stream.result.counts.in} color="#62937B" />
        <Stat testid={`camera-out-${camera.id}`} label="Uscite" value={stream.result.counts.out} color="#EF4444" />
        <Stat testid={`camera-present-${camera.id}`} label="In scena" value={stream.result.tracks.filter((t) => !t.fixed).length} color="#06B6D4" />
        <Stat testid={`camera-zones-${camera.id}`} label="Zone" value={`${stream.result.zones_active.length}/${camera.zones.filter((z) => z.enabled).length}`} color="#F472B6" />
      </div>
    </div>
  );
}
