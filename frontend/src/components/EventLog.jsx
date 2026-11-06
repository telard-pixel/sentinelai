import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, Trash2, Siren, Clapperboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { API, CATEGORY, TZ, fmtDate, fmtTime, http, snapshotUrl } from "@/lib/api";
import { DirectionBadge } from "@/components/LiveEvents";
import { toast } from "sonner";

function Filter({ testid, value, onChange, options, placeholder }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger data-testid={testid} className="h-9 w-48 border-white/10 bg-black/30 font-mono text-xs"><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent className="border-white/10 bg-slate-900/95 backdrop-blur-md">
        {options.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

export default function EventLog({ onOpen }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ category: "all", direction: "all", hours: "24", camera: "all" });
  const { data: cameras = [] } = useQuery({ queryKey: ["cameras"], queryFn: () => http.get("/cameras").then((r) => r.data) });
  const params = {
    limit: 300,
    ...(f.camera !== "all" && { camera_id: f.camera }),
    ...(f.direction === "zona" && { type: "zona" }),
    ...(f.category !== "all" && { category: f.category }),
    ...(["IN", "OUT"].includes(f.direction) && { direction: f.direction }),
    ...(f.direction === "transito" && { type: "transito" }),
    ...(f.direction === "alert" && { alert_only: true }),
    ...(f.hours !== "all" && { hours: f.hours }),
  };
  const { data = [] } = useQuery({ queryKey: ["events", params], queryFn: () => http.get("/events", { params }).then((r) => r.data), refetchInterval: 5000 });

  const exportUrl = (format) => {
    const q = new URLSearchParams({ format, tz_offset: new Date().getTimezoneOffset(), ...(TZ && { tz: TZ }) });
    Object.entries(params).forEach(([k, v]) => k !== "limit" && q.set(k, v));
    return `${API}/events/export?${q}`;
  };
  const clear = async () => {
    if (!window.confirm("Eliminare definitivamente tutti gli eventi registrati?")) return;
    await http.delete("/events");
    qc.invalidateQueries();
    toast.success("Registro eventi svuotato");
  };

  return (
    <div className="panel" data-testid="event-log">
      <div className="flex flex-wrap items-center gap-3 border-b border-white/5 px-4 py-3">
        <h2 className="mr-auto font-heading text-lg font-semibold text-gray-100">Registro eventi</h2>
        <Filter testid="filter-camera" value={f.camera} onChange={(v) => setF({ ...f, camera: v })}
          options={[["all", "Tutte le telecamere"], ...cameras.map((c) => [c.id, c.name])]} />
        <Filter testid="filter-category" value={f.category} onChange={(v) => setF({ ...f, category: v })}
          options={[["all", "Tutte le categorie"], ...Object.entries(CATEGORY).map(([k, c]) => [k, c.label])]} />
        <Filter testid="filter-direction" value={f.direction} onChange={(v) => setF({ ...f, direction: v })}
          options={[["all", "Tutti gli eventi"], ["IN", "Solo entrate"], ["OUT", "Solo uscite"], ["transito", "Solo transiti"], ["zona", "Solo zone"], ["alert", "Solo allarmi"]]} />
        <Filter testid="filter-period" value={f.hours} onChange={(v) => setF({ ...f, hours: v })}
          options={[["1", "Ultima ora"], ["24", "Ultime 24 ore"], ["168", "Ultimi 7 giorni"], ["all", "Tutto"]]} />
        <Button asChild variant="outline" className="h-9 gap-2 border-white/10 bg-transparent font-mono text-xs">
          <a data-testid="export-csv-button" href={exportUrl("csv")}><FileText className="h-3.5 w-3.5" /> CSV</a>
        </Button>
        <Button asChild className="h-9 gap-2 bg-emerald-500 font-mono text-xs text-[#04130D] hover:bg-emerald-400">
          <a data-testid="export-excel-button" href={exportUrl("xlsx")}><FileSpreadsheet className="h-3.5 w-3.5" /> Excel</a>
        </Button>
        <Button data-testid="clear-events-button" variant="ghost" onClick={clear} className="h-9 px-2 text-gray-500 hover:text-red-400"><Trash2 className="h-4 w-4" /></Button>
      </div>
      <div className="max-h-[70vh] overflow-auto">
        <table className="w-full text-sm" data-testid="event-log-table">
          <thead className="sticky top-0 bg-raised2 font-mono text-[10px] uppercase tracking-widest text-gray-500">
            <tr>{["Screenshot", "Data / ora", "Telecamera", "Oggetto", "Evento", "Direzione", "Conf.", "Allarme"].map((h) => <th key={h} className="px-4 py-2.5 text-left font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {data.length === 0 && <tr><td colSpan={8} className="py-16 text-center text-gray-500">Nessun evento per i filtri selezionati</td></tr>}
            {data.map((ev) => (
              <tr key={ev.id} data-testid={`event-row-${ev.id}`} onClick={() => onOpen(ev)} className="cursor-pointer border-t border-white/5 transition-colors hover:bg-white/[0.03]">
                <td className="px-4 py-2">
                  <div className="h-10 w-16 overflow-hidden rounded bg-black">{ev.has_snapshot && <img src={snapshotUrl(ev.id)} alt="" loading="lazy" className="h-full w-full object-cover" />}</div>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-gray-300">{fmtDate(ev.timestamp)}<br /><span className="text-gray-500">{fmtTime(ev.timestamp)}</span></td>
                <td className="px-4 py-2 text-xs text-gray-300">{ev.camera_name || "—"}<br /><span className="font-mono text-[10px] uppercase text-gray-500">{ev.source}</span></td>
                <td className="px-4 py-2"><span className="inline-flex items-center gap-2 capitalize text-gray-100"><span className="h-2 w-2 rounded-full" style={{ background: CATEGORY[ev.category]?.color }} />{ev.class_name}</span></td>
                <td className="px-4 py-2"><DirectionBadge ev={ev} />{ev.zone_name && <div className="mt-1 text-[10px] text-pink-300">{ev.zone_name}</div>}</td>
                <td className="px-4 py-2 font-mono text-xs text-cyan-300">{ev.arrow} {ev.heading}</td>
                <td className="px-4 py-2 font-mono text-xs text-gray-300">{Math.round(ev.confidence * 100)}%</td>
                <td className="px-4 py-2">{ev.alert && <span className="inline-flex items-center gap-1 font-mono text-[10px] text-red-400"><Siren className="h-3 w-3" />{ev.alert_rule}</span>}{ev.clip_id && <span data-testid={`event-clip-${ev.id}`} className="mt-1 flex items-center gap-1 font-mono text-[10px] text-emerald-400"><Clapperboard className="h-3 w-3" />Clip video</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
