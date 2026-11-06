import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Play, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { API, CATEGORY, TZ, fmtDate, fmtTime, http, snapshotUrl } from "@/lib/api";
import ClipPlayer from "@/components/ClipPlayer";
import { DirectionBadge } from "@/components/LiveEvents";

const tz = new Date().getTimezoneOffset();
const tzName = TZ ? { tz: TZ } : {};
const dayLabel = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("it-IT", { weekday: "short", day: "2-digit", month: "long", year: "numeric" });

function Filter({ testid, value, onChange, options }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger data-testid={testid} className="h-9 w-56 border-white/10 bg-black/30 font-mono text-xs"><SelectValue /></SelectTrigger>
      <SelectContent className="border-white/10 bg-slate-900/95 backdrop-blur-md">
        {options.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

function ClipCard({ clip, onOpen }) {
  const [hover, setHover] = useState(false);
  const ev = clip.event;
  const ready = clip.status === "ready";
  return (
    <button data-testid={`clip-card-${clip.id}`} onClick={() => onOpen(clip)} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      className="panel group overflow-hidden text-left transition-transform hover:-translate-y-0.5">
      <div className="force-dark relative aspect-video bg-black">
        {ev?.has_snapshot && <img src={snapshotUrl(ev.id)} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />}
        {hover && ready && <video src={`${API}/clips/${clip.id}/video`} autoPlay muted loop playsInline className="absolute inset-0 h-full w-full object-cover" />}
        {!hover && <span className="absolute inset-0 grid place-items-center"><span className="grid h-10 w-10 place-items-center rounded-full bg-black/60 text-white backdrop-blur"><Play className="h-4 w-4" /></span></span>}
        <span className="absolute right-2 top-2 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-gray-200">{ready ? `${clip.duration}s` : "REC…"}</span>
        {clip.event_ids?.length > 1 && <span className="absolute left-2 top-2 rounded bg-red-500/90 px-1.5 py-0.5 font-mono text-[10px] text-[#fff]">{clip.event_ids.length} allarmi</span>}
      </div>
      <div className="space-y-1 p-3">
        <p className="truncate text-sm font-medium text-gray-100">{ev?.alert_rule || "Allarme"}</p>
        <div className="flex items-center gap-2 text-xs">
          {ev && <span className="inline-flex items-center gap-1 capitalize text-gray-300"><span className="h-1.5 w-1.5 rounded-full" style={{ background: CATEGORY[ev.category]?.color }} />{ev.class_name}</span>}
          {ev && <DirectionBadge ev={ev} />}
        </div>
        <p className="font-mono text-[10px] text-gray-500">{clip.camera_name} · {fmtDate(clip.timestamp)} {fmtTime(clip.timestamp)}</p>
      </div>
    </button>
  );
}

export default function ClipArchive({ onOpenEvent }) {
  const qc = useQueryClient();
  const [camera, setCamera] = useState("all");
  const [day, setDay] = useState("all");
  const [open, setOpen] = useState(null);
  const { data: cameras = [] } = useQuery({ queryKey: ["cameras"], queryFn: () => http.get("/cameras").then((r) => r.data) });
  const camParams = camera !== "all" ? { camera_id: camera } : {};
  const { data: days = [] } = useQuery({ queryKey: ["clip-days", camera], queryFn: () => http.get("/clips/days", { params: { tz_offset: tz, ...tzName, ...camParams } }).then((r) => r.data), refetchInterval: 20000 });
  const { data: clips = [], isLoading } = useQuery({
    queryKey: ["clips", camera, day],
    queryFn: () => http.get("/clips", { params: { tz_offset: tz, ...tzName, ...camParams, ...(day !== "all" && { day }) } }).then((r) => r.data),
    refetchInterval: 10000,
  });

  const remove = async (c) => {
    if (!window.confirm("Eliminare definitivamente questa clip?")) return;
    await http.delete(`/clips/${c.id}`);
    setOpen(null);
    qc.invalidateQueries({ queryKey: ["clips"] });
    qc.invalidateQueries({ queryKey: ["clip-days"] });
    toast.success("Clip eliminata");
  };

  return (
    <div className="space-y-4" data-testid="clip-archive">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="mr-auto font-heading text-2xl font-semibold text-gray-100">Archivio clip <span className="font-mono text-sm text-gray-500">({clips.length})</span></h2>
        <Filter testid="clips-filter-camera" value={camera} onChange={(v) => { setCamera(v); setDay("all"); }} options={[["all", "Tutte le telecamere"], ...cameras.map((c) => [c.id, c.name])]} />
        <Filter testid="clips-filter-day" value={day} onChange={setDay} options={[["all", "Tutti i giorni"], ...days.map((d) => [d.day, `${dayLabel(d.day)} (${d.count})`])]} />
      </div>
      {!isLoading && clips.length === 0 && (
        <div className="panel flex flex-col items-center gap-3 py-20 text-gray-500" data-testid="clips-empty"><Clapperboard className="h-8 w-8" />Nessuna clip per i filtri selezionati</div>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4" data-testid="clips-grid">
        {clips.map((c) => <ClipCard key={c.id} clip={c} onOpen={setOpen} />)}
      </div>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent data-testid="clip-archive-dialog" className="max-w-3xl border-white/10 bg-raised text-gray-100">
          {open && (
            <>
              <DialogHeader><DialogTitle className="font-heading">{open.event?.alert_rule || "Clip allarme"}</DialogTitle></DialogHeader>
              <ClipPlayer clipId={open.id} testid="archive-clip" />
              <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-gray-400">
                <span>{open.camera_name} · {fmtDate(open.timestamp)} {fmtTime(open.timestamp)} · {open.event_ids?.length || 0} allarmi nella clip</span>
                {open.event && <button data-testid="clip-archive-event" onClick={() => { onOpenEvent(open.event); setOpen(null); }} className="ml-auto rounded border border-white/10 px-2.5 py-1 uppercase text-gray-300 hover:text-gray-100">Dettagli evento</button>}
                <button data-testid="clip-archive-delete" onClick={() => remove(open)} className={`flex items-center gap-1 rounded px-2.5 py-1 uppercase text-red-400 hover:bg-red-500/10 ${open.event ? "" : "ml-auto"}`}><Trash2 className="h-3.5 w-3.5" /> Elimina</button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
