import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clapperboard, Download, Maximize2, X } from "lucide-react";
import { API, CATEGORY, fmtDate, fmtTime, http } from "@/lib/api";
import ClipPlayer from "@/components/ClipPlayer";
import { DirectionBadge } from "@/components/LiveEvents";

export default function LatestClipPanel({ liveEvents, onOpenEvent }) {
  const [dismissed, setDismissed] = useState(() => localStorage.getItem("dismissedClip") || null);
  const { data: recent = [] } = useQuery({
    queryKey: ["events", "latest-alerts"],
    queryFn: () => http.get("/events", { params: { alert_only: true, limit: 30 } }).then((r) => r.data),
    refetchInterval: 15000,
  });
  const ev = liveEvents.find((e) => e.clip_id) || recent.find((e) => e.clip_id);
  const [pulse, setPulse] = useState(false);

  useEffect(() => {
    if (!ev?.clip_id) return undefined;
    setPulse(true);
    const t = setTimeout(() => setPulse(false), 2500);
    return () => clearTimeout(t);
  }, [ev?.clip_id]);

  if (!ev || dismissed === ev.clip_id) return null;
  const dismiss = () => { localStorage.setItem("dismissedClip", ev.clip_id); setDismissed(ev.clip_id); };

  return (
    <div data-testid="latest-clip-panel" className={`panel flex flex-col gap-4 p-3 transition-shadow md:flex-row ${pulse ? "shadow-[0_0_0_2px_rgba(239,68,68,0.6)]" : ""}`}>
      <div className="w-full shrink-0 md:w-[360px]">
        <ClipPlayer key={ev.clip_id} clipId={ev.clip_id} compact testid="latest-clip" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center gap-2">
          <Clapperboard className="h-4 w-4 text-red-400" />
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-gray-500">Ultima clip d'allarme</span>
          <button data-testid="latest-clip-dismiss" onClick={dismiss} title="Nascondi fino al prossimo allarme" className="ml-auto rounded p-1 text-gray-500 hover:bg-white/5 hover:text-gray-200"><X className="h-4 w-4" /></button>
        </div>
        <p className="font-heading text-lg font-semibold text-gray-100" data-testid="latest-clip-title">{ev.alert_rule}</p>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="inline-flex items-center gap-1.5 capitalize text-gray-200"><span className="h-2 w-2 rounded-full" style={{ background: CATEGORY[ev.category]?.color }} />{ev.class_name}</span>
          <DirectionBadge ev={ev} />
          <span className="font-mono text-xs text-cyan-300">{ev.arrow} {ev.heading}</span>
        </div>
        <p className="font-mono text-xs text-gray-500" data-testid="latest-clip-meta">
          {ev.camera_name || "—"}{ev.zone_name ? ` · ${ev.zone_name}` : ""} · {fmtDate(ev.timestamp)} {fmtTime(ev.timestamp)}
        </p>
        <div className="mt-auto flex gap-2 pt-1">
          <button data-testid="latest-clip-open" onClick={() => onOpenEvent(ev)} className="flex items-center gap-1.5 rounded border border-white/10 px-2.5 py-1.5 font-mono text-[11px] uppercase text-gray-300 hover:text-gray-100">
            <Maximize2 className="h-3.5 w-3.5" /> Dettagli
          </button>
          <a data-testid="latest-clip-download" href={`${API}/clips/${ev.clip_id}/video?download=true`} className="flex items-center gap-1.5 rounded border border-white/10 px-2.5 py-1.5 font-mono text-[11px] uppercase text-emerald-400 hover:bg-emerald-500/10">
            <Download className="h-3.5 w-3.5" /> Scarica MP4
          </a>
        </div>
      </div>
    </div>
  );
}
