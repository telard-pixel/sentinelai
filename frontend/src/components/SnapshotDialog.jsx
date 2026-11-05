import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CATEGORY, fmtDate, fmtTime, snapshotUrl } from "@/lib/api";
import { DirectionBadge } from "@/components/LiveEvents";
import ClipPlayer from "@/components/ClipPlayer";

export default function SnapshotDialog({ event, onClose }) {
  const [view, setView] = useState("clip");
  useEffect(() => setView("clip"), [event?.id]);
  return (
    <Dialog open={!!event} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="snapshot-dialog" className="max-w-2xl border-white/10 bg-raised text-gray-100">
        {event && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-3 font-heading capitalize">
                {event.class_name} <DirectionBadge ev={event} />
              </DialogTitle>
            </DialogHeader>
            {event.clip_id && (
              <div className="flex gap-1" data-testid="media-toggle">
                {[["clip", "Clip video"], ["photo", "Screenshot"]].map(([k, l]) => (
                  <button key={k} data-testid={`media-${k}-button`} onClick={() => setView(k)}
                    className={`rounded border px-2.5 py-1 font-mono text-[11px] uppercase ${view === k ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400" : "border-white/10 text-gray-400"}`}>{l}</button>
                ))}
              </div>
            )}
            {event.clip_id && view === "clip" ? <ClipPlayer clipId={event.clip_id} /> : (
            <div className="force-dark overflow-hidden rounded-md border border-white/10 bg-black">
              {event.has_snapshot ? (
                <img data-testid="snapshot-image" src={snapshotUrl(event.id)} alt="Screenshot evento" className="w-full" />
              ) : (
                <p className="p-10 text-center text-sm text-gray-500">Nessuno screenshot disponibile</p>
              )}
            </div>
            )}
            <dl className="grid grid-cols-3 gap-3 font-mono text-xs">
              {[
                ["Data", `${fmtDate(event.timestamp)} ${fmtTime(event.timestamp)}`],
                ["Telecamera", event.camera_name || "—"],
                ["Zona", event.zone_name || "—"],
                ["Categoria", CATEGORY[event.category]?.label],
                ["Direzione", `${event.arrow} ${event.heading}${event.angle != null ? ` (${Math.round(event.angle)}°)` : ""}`],
                ["Confidenza", `${Math.round(event.confidence * 100)}%`],
                ["Traccia", `#${event.track_id}`],
                ["Allarme", event.alert_rule || "—"],
              ].map(([k, v]) => (
                <div key={k} className="rounded border border-white/5 bg-black/30 p-2">
                  <dt className="text-[9px] uppercase tracking-widest text-gray-500">{k}</dt>
                  <dd className="mt-1 text-gray-200">{v}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
