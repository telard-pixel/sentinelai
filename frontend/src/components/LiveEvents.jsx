import { Siren, Clapperboard } from "lucide-react";
import { CATEGORY, fmtTime, snapshotUrl } from "@/lib/api";

export function DirectionBadge({ ev }) {
  if (ev.type?.startsWith("zona")) {
    return <span className="rounded bg-pink-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-pink-300">{ev.type === "zona_sosta" ? "SOSTA" : "ZONA"}</span>;
  }
  if (ev.direction) {
    const isIn = ev.direction === "IN";
    return (
      <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${isIn ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"}`}>
        {isIn ? "ENTRATA" : "USCITA"}
      </span>
    );
  }
  return <span className="rounded bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">TRANSITO</span>;
}

export default function LiveEvents({ events, onOpen }) {
  return (
    <div className="panel flex min-h-0 flex-1 flex-col" data-testid="recent-events-timeline">
      <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
        <h3 className="font-heading text-sm font-semibold tracking-wide text-gray-100">Eventi in tempo reale</h3>
        <span className="font-mono text-[10px] uppercase tracking-widest text-gray-500">{events.length} sessione</span>
      </div>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2" style={{ maxHeight: 420 }}>
        {events.length === 0 && (
          <p className="px-3 py-10 text-center text-sm text-gray-500">Gli attraversamenti e i transiti compariranno qui.</p>
        )}
        {events.map((ev) => (
          <button
            key={ev.id}
            data-testid={`live-event-${ev.id}`}
            onClick={() => onOpen(ev)}
            className={`event-in flex w-full items-center gap-3 rounded-md border p-2 text-left transition-colors hover:bg-white/5 ${ev.alert ? "border-red-500/40 bg-red-500/5" : "border-transparent"}`}
          >
            <div className="relative h-11 w-16 shrink-0 overflow-hidden rounded bg-black">
              {ev.has_snapshot && <img src={snapshotUrl(ev.id)} alt="" loading="lazy" className="h-full w-full object-cover" />}
              <span className="absolute left-0 top-0 h-full w-[3px]" style={{ background: CATEGORY[ev.category]?.color }} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium capitalize text-gray-100">{ev.class_name}</span>
                <DirectionBadge ev={ev} />
                {ev.alert && <Siren className="h-3.5 w-3.5 text-red-400" />}
                {ev.clip_id && <Clapperboard data-testid={`live-event-clip-${ev.id}`} className="h-3.5 w-3.5 text-emerald-400" />}
              </div>
              <div className="mt-0.5 font-mono text-[10px] text-gray-500">
                {fmtTime(ev.timestamp)} · {ev.camera_name && <span className="text-gray-400">{ev.camera_name} · </span>}{ev.zone_name && <span className="text-pink-300">{ev.zone_name} · </span>}<span className="text-cyan-300">{ev.arrow} {ev.heading}</span> · {Math.round(ev.confidence * 100)}%
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
