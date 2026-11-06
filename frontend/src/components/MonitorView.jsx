import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Square, Columns2, Columns3, RectangleHorizontal } from "lucide-react";
import { toast } from "sonner";
import { http } from "@/lib/api";
import CameraTile from "@/components/CameraTile";
import CameraDialog from "@/components/CameraDialog";
import CounterGrid from "@/components/CounterGrid";
import LiveEvents from "@/components/LiveEvents";
import LatestClipPanel from "@/components/LatestClipPanel";

const LAYOUTS = [
  [1, RectangleHorizontal, "lg:grid-cols-1"],
  [2, Columns2, "lg:grid-cols-2"],
  [3, Columns3, "lg:grid-cols-3"],
];
const toBody = ({ id, created_at, has_nvr_password, disabled, ...rest }) => ({ ...rest, url: rest.type === "nvr" ? "" : rest.url });

export default function MonitorView({ onEvents, liveEvents, totals, onOpenEvent }) {
  const qc = useQueryClient();
  const [cols, setCols] = useState(() => Number(localStorage.getItem("gridCols")) || 2);
  const [expanded, setExpanded] = useState(null);
  const [editing, setEditing] = useState(null);
  const [results, setResults] = useState({});
  const { data: cameras = [] } = useQuery({ queryKey: ["cameras"], queryFn: () => http.get("/cameras").then((r) => r.data) });
  useEffect(() => {
    const refresh = () => qc.invalidateQueries({ queryKey: ["cameras"] });
    window.addEventListener("sentinel-cameras", refresh);
    return () => window.removeEventListener("sentinel-cameras", refresh);
  }, [qc]);

  const onResult = useCallback((id, r) => setResults((prev) => {
    const next = { ...prev };
    if (r) next[id] = r;
    else delete next[id];
    return next;
  }), []);

  const onErr = (e) => toast.error("Salvataggio non riuscito", { description: e.response?.data?.detail?.[0]?.msg || e.message });
  const update = useMutation({
    mutationFn: (c) => http.put(`/cameras/${c.id}`, toBody(c)).then((r) => r.data),
    onSuccess: (c) => qc.setQueryData(["cameras"], (list = []) => list.map((x) => (x.id === c.id ? c : x))),
    onError: onErr,
  });
  const create = useMutation({
    mutationFn: (c) => http.post("/cameras", toBody(c)).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["cameras"] }); toast.success("Telecamera aggiunta"); },
    onError: onErr,
  });
  const remove = useMutation({
    mutationFn: (c) => http.delete(`/cameras/${c.id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["cameras"] }); toast.success("Telecamera eliminata"); },
  });

  const agg = Object.values(results).reduce(
    (a, r) => ({ tracks: [...a.tracks, ...r.tracks], counts: { in: a.counts.in + r.counts.in, out: a.counts.out + r.counts.out } }),
    { tracks: [], counts: { in: 0, out: 0 } },
  );
  const saveDialog = (d) => {
    const close = () => setEditing(null);
    if (editing === "new") create.mutate(d, { onSuccess: close });
    else update.mutate({ ...d, id: editing.id }, { onSuccess: () => { toast.success("Telecamera aggiornata"); close(); } });
  };

  return (
    <section className="grid grid-cols-1 gap-4 xl:grid-cols-12" data-testid="monitor-view">
      <div className="space-y-3 xl:col-span-9">
        <div className="flex items-center gap-3">
          <h2 className="font-heading text-lg font-semibold text-gray-100">Telecamere <span className="font-mono text-sm text-gray-500">({cameras.length})</span></h2>
          <div className="ml-auto hidden rounded-md border border-white/10 bg-black/30 p-0.5 lg:flex">
            {LAYOUTS.map(([n, Icon]) => (
              <button key={n} data-testid={`grid-layout-${n}`} title={`${n} colonne`} onClick={() => { setCols(n); localStorage.setItem("gridCols", n); }}
                className={`rounded px-2 py-1 ${cols === n ? "bg-emerald-500/15 text-emerald-400" : "text-gray-500 hover:text-gray-200"}`}><Icon className="h-4 w-4" /></button>
            ))}
          </div>
          <button data-testid="camera-add-button" onClick={() => setEditing("new")}
            className="flex items-center gap-1.5 rounded bg-emerald-500 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-[#04130D] hover:bg-emerald-400">
            <Plus className="h-3.5 w-3.5" /> Aggiungi telecamera
          </button>
        </div>
        <LatestClipPanel liveEvents={liveEvents} onOpenEvent={onOpenEvent} />
        {cameras.length === 0 && (
          <div className="panel flex flex-col items-center gap-3 py-20 text-gray-500"><Square className="h-8 w-8" />Nessuna telecamera configurata</div>
        )}
        <div className={`grid grid-cols-1 gap-3 ${LAYOUTS.find((l) => l[0] === cols)[2]}`} data-testid="camera-grid">
          {cameras.map((c) => (
            <CameraTile key={c.id} camera={c} onEvents={onEvents} onResult={onResult} compact={cols > 1}
              onCameraChange={(nc) => update.mutateAsync(nc)} onEdit={setEditing}
              expanded={expanded === c.id} onToggleExpand={() => setExpanded(expanded === c.id ? null : c.id)} />
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-4 xl:col-span-3">
        <CounterGrid result={agg} totals={totals} />
        <LiveEvents events={liveEvents} onOpen={onOpenEvent} />
      </div>
      <CameraDialog camera={editing} onClose={() => setEditing(null)} onSave={saveDialog}
        onDelete={(c) => { remove.mutate(c); setEditing(null); }} />
    </section>
  );
}
