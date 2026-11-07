import { useState } from "react";
import { Spline, ArrowLeftRight, RotateCcw, Eye, EyeOff, Loader2, AlertTriangle, ScanEye, Hexagon, Flame, Check, X } from "lucide-react";
import OverlayCanvas from "@/components/OverlayCanvas";
import HeatmapCanvas, { useHeatmap } from "@/components/HeatmapCanvas";
import ZoneDialog from "@/components/ZoneDialog";
import { newId } from "@/lib/utils";

function HudButton({ testid, active, onClick, icon: Icon, children, compact, tone = "amber" }) {
  const on = tone === "red" ? "border-red-500/60 bg-red-500/15 text-red-300" : "border-amber-500/60 bg-amber-500/15 text-amber-300";
  return (
    <button data-testid={testid} onClick={onClick} title={typeof children === "string" ? children : undefined}
      className={`flex items-center gap-1.5 rounded border px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider backdrop-blur-md transition-colors ${
        active ? on : "border-white/10 bg-app/75 text-gray-300 hover:text-white"}`}>
      <Icon className="h-3.5 w-3.5" /> {!compact && children}
    </button>
  );
}

const Center = ({ children }) => <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[#000000] p-4">{children}</div>;

function Hud({ camera, stream, mode, setMode, heat, setHeat, compact, onCameraChange, zoneDraft, finishZone, cancelZone }) {
  const line = camera.line;
  if (mode === "zone") {
    return (
      <div className="absolute bottom-2 right-2 flex flex-wrap items-center justify-end gap-2">
        <span className="pointer-events-none rounded bg-black/75 px-2 py-1 font-mono text-[10px] text-amber-300">Clicca per aggiungere vertici · {zoneDraft.length} punti</span>
        <HudButton testid={`zone-finish-${camera.id}`} icon={Check} active onClick={finishZone}>Completa zona</HudButton>
        <HudButton testid={`zone-cancel-${camera.id}`} icon={X} onClick={cancelZone}>Annulla</HudButton>
      </div>
    );
  }
  return (
    <div className="absolute bottom-2 right-2 flex flex-wrap justify-end gap-1.5">
      <HudButton compact={compact} testid={`virtual-line-toggle-${camera.id}`} icon={line.enabled ? Eye : EyeOff} active={line.enabled}
        onClick={() => onCameraChange({ ...camera, line: { ...line, enabled: !line.enabled } })}>{line.enabled ? "Linea attiva" : "Linea spenta"}</HudButton>
      <HudButton compact={compact} testid={`virtual-line-edit-${camera.id}`} icon={Spline} active={mode === "line"} onClick={() => setMode(mode === "line" ? null : "line")}>
        {mode === "line" ? "Fine modifica" : "Modifica linea"}
      </HudButton>
      <HudButton compact={compact} testid={`virtual-line-invert-${camera.id}`} icon={ArrowLeftRight} onClick={() => onCameraChange({ ...camera, line: { ...line, invert: !line.invert } })}>Inverti IN/OUT</HudButton>
      <HudButton compact={compact} testid={`zone-draw-${camera.id}`} icon={Hexagon} tone="red" onClick={() => setMode("zone")}>Disegna zona</HudButton>
      <HudButton compact={compact} testid={`heatmap-toggle-${camera.id}`} icon={Flame} tone="red" active={heat} onClick={() => setHeat(!heat)}>Mappa calore</HudButton>
      <HudButton compact={compact} testid={`counters-reset-${camera.id}`} icon={RotateCcw} onClick={() => stream.send({ type: "reset" })}>Azzera</HudButton>
    </div>
  );
}

export default function LiveFeed({ stream, camera, onCameraChange, compact, maxH }) {
  const [mode, setMode] = useState(null);
  const [heat, setHeat] = useState(false);
  const [zoneDraft, setZoneDraft] = useState([]);
  const [pendingZone, setPendingZone] = useState(null);
  const [heatData] = useHeatmap(camera.id, null, heat, 5000);
  const { status, result, frame, dims, videoRef } = stream;
  const isNet = ["rtsp", "nvr"].includes(status.source);
  const live = status.state === "live";
  const ratio = dims.w / dims.h;

  const finishZone = () => {
    if (zoneDraft.length < 3) return;
    setPendingZone({ id: newId(), name: `Zona ${camera.zones.length + 1}`, points: zoneDraft, enabled: true, categories: [], alert_on_enter: true, dwell_seconds: 0, color: "#F472B6" });
    setMode(null);
    setZoneDraft([]);
  };

  return (
    <div className="force-dark relative bg-black" data-testid={`live-feed-${camera.id}`}>
      <div className="relative mx-auto w-full" style={{ aspectRatio: `${dims.w} / ${dims.h}`, ...(maxH && { maxHeight: maxH, maxWidth: `calc(${maxH} * ${ratio})` }) }}>
        <video ref={videoRef} playsInline muted data-testid={`live-video-${camera.id}`}
          onLoadedMetadata={(e) => stream.setDims({ w: e.target.videoWidth, h: e.target.videoHeight })}
          className={`absolute inset-0 h-full w-full object-fill ${isNet || frame || status.state === "idle" ? "invisible" : ""}`} />
        {frame && <img src={frame} alt="Fotogramma analizzato" data-testid={`analyzed-frame-${camera.id}`} className="absolute inset-0 h-full w-full object-fill" />}
        {status.state === "idle" && (
          <Center>
            <div className="hud-grid absolute inset-0 opacity-40" />
            <ScanEye className="relative h-10 w-10 text-emerald-500/70" strokeWidth={1.25} />
            <p className="relative font-heading text-lg text-gray-200">Nessun flusso attivo</p>
            {!compact && <p className="relative max-w-sm text-center text-sm text-gray-500">Premi <span className="text-emerald-400">Avvia</span> per iniziare il monitoraggio di questa telecamera.</p>}
          </Center>
        )}
        {status.state === "connecting" && <Center><Loader2 className="h-8 w-8 animate-spin text-emerald-400" /><p className="font-mono text-xs uppercase tracking-widest text-gray-400">Connessione al motore YOLO11…</p></Center>}
        {status.state === "error" && <Center><AlertTriangle className="h-8 w-8 text-red-400" /><p data-testid={`stream-error-${camera.id}`} className="max-w-md text-center text-sm text-red-300">{status.error}</p></Center>}
        {heat && heatData && <HeatmapCanvas data={heatData} testid={`heatmap-overlay-${camera.id}`} />}
        <OverlayCanvas tracks={live ? result.tracks : []} line={camera.line} showLine={live || mode === "line"} mode={mode}
          onLineChange={(l) => onCameraChange({ ...camera, line: l })} zones={live || mode ? camera.zones : []} zonesActive={result.zones_active}
          zoneDraft={zoneDraft} onZonePoint={(p) => setZoneDraft((z) => [...z, p])} />
        <div className="scanlines pointer-events-none absolute inset-0" />
        <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap gap-1.5 font-mono text-[10px] uppercase tracking-wider">
          <span data-testid={`stream-status-${camera.id}`} className={`flex items-center gap-1.5 rounded border px-2 py-1 backdrop-blur-md ${live ? "border-red-500/50 bg-red-500/15 text-red-300" : "border-white/10 bg-black/60 text-gray-400"}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${live ? "animate-pulse bg-red-500" : "bg-gray-500"}`} />{live ? "LIVE" : "OFFLINE"}
          </span>
          <span data-testid={`fps-counter-${camera.id}`} className="rounded border border-white/10 bg-black/60 px-2 py-1 text-cyan-300 backdrop-blur-md">{result.fps.toFixed(1)} FPS</span>
          {result.zones_active.length > 0 && <span data-testid={`zone-alert-${camera.id}`} className="animate-pulse rounded border border-red-500/60 bg-red-500/20 px-2 py-1 text-red-300">ZONA OCCUPATA</span>}
        </div>
        <Hud camera={camera} stream={stream} mode={mode} setMode={(m) => { setMode(m); setZoneDraft([]); }} heat={heat} setHeat={setHeat} compact={compact}
          onCameraChange={onCameraChange} zoneDraft={zoneDraft} finishZone={finishZone} cancelZone={() => { setMode(null); setZoneDraft([]); }} />
      </div>
      <ZoneDialog zone={pendingZone} onCancel={() => setPendingZone(null)}
        onSave={(z) => { onCameraChange({ ...camera, zones: [...camera.zones, z] }); setPendingZone(null); }} />
    </div>
  );
}
