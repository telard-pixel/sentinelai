import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Square, Columns2, Columns3, RectangleHorizontal } from "lucide-react";
import { toast } from "sonner";
import { http, errorText } from "@/lib/api";
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

  // 1.0.20: ordine delle telecamere trascinandole per la maniglia (mouse e dito: pointer events, non il
  // drag&drop HTML5 che sul telefono non va). Durante il trascinamento l'ordine vive qui; al rilascio si salva
  // sul server (PUT /camera-order), uguale per tutti i dispositivi.
  const [order, setOrder] = useState(null);
  const [dragId, setDragId] = useState(null);
  const drag = useRef(null);
  const shown = useMemo(() => {
    if (!order) return cameras;
    const byId = new Map(cameras.map((c) => [c.id, c]));
    return [...order.map((id) => byId.get(id)).filter(Boolean), ...cameras.filter((c) => !order.includes(c.id))];
  }, [order, cameras]);
  const saveOrder = useMutation({
    mutationFn: (ids) => http.put("/camera-order", { ids }).then((r) => r.data),
    onSuccess: ({ ids }) => {
      qc.setQueryData(["cameras"], (list = []) => {
        const pos = new Map(ids.map((id, n) => [id, n]));
        return [...list].sort((a, b) => (pos.get(a.id) ?? ids.length) - (pos.get(b.id) ?? ids.length));
      });
      setOrder(null);
    },
    onError: (e) => { setOrder(null); qc.invalidateQueries({ queryKey: ["cameras"] }); toast.error("Ordine non salvato", { description: errorText(e) }); },
  });
  // Trascinamento (agente di prova 1.0.20): ascoltatori su window e niente cattura del puntatore sulla maniglia,
  // perché quando React sposta la scheda trascinata il browser toglieva la cattura e il trascinamento finiva dopo
  // un posto. Dopo uno scambio non si riscambia con la stessa scheda finché il puntatore non la lascia (con una
  // scheda espansa l'ordine oscillava).
  const endDrag = useRef(null);
  useEffect(() => () => endDrag.current?.(false), []);
  const startDrag = (id, e) => {
    if (e.button > 0 || drag.current) return;
    e.preventDefault();
    const ids = shown.map((c) => c.id);
    const d = { id, start: ids, order: ids, last: null };
    drag.current = d;
    setOrder(ids);
    setDragId(id);
    const move = (ev) => {
      const over = document.elementFromPoint(ev.clientX, ev.clientY)?.closest("[data-camera-id]")?.dataset.cameraId;
      if (over !== d.last) d.last = null;      // lasciata la scheda appena scambiata: si può di nuovo
      if (!over || over === id || over === d.last) return;
      const to = d.order.indexOf(over);
      if (to < 0) return;
      const next = d.order.filter((x) => x !== id);
      next.splice(to, 0, id);
      d.order = next;
      d.last = over;
      setOrder(next);
    };
    const stop = (save) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      endDrag.current = null;
      drag.current = null;
      setDragId(null);
      if (save && d.order.join() !== d.start.join()) saveOrder.mutate(d.order);
      else setOrder(null);
    };
    const up = () => stop(true);
    const cancel = () => stop(false);
    endDrag.current = stop;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
  };
  // Da tastiera: frecce per spostare di un posto; si salva poco dopo l'ultima freccia (più frecce di fila contano tutte).
  const keyTimer = useRef(null);
  useEffect(() => () => clearTimeout(keyTimer.current), []);
  const handleFor = (id) => ({
    onPointerDown: (e) => startDrag(id, e),
    onKeyDown: (e) => {
      const step = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[e.key];
      if (!step || drag.current) return;
      e.preventDefault();
      const ids = shown.map((c) => c.id);
      const i = ids.indexOf(id), j = i + step;
      if (j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      setOrder(ids);
      clearTimeout(keyTimer.current);
      keyTimer.current = setTimeout(() => saveOrder.mutate(ids), 600);
    },
  });

  // 1.0.20: 409 = la telecamera è stata cambiata da un'altra finestra; si ricaricano i dati veri
  const onErr = (e) => {
    if (e?.response?.status === 409) {
      qc.invalidateQueries({ queryKey: ["cameras"] });
      toast.warning("Telecamera cambiata da un'altra finestra", { description: "Ho ricaricato i dati: riprova la modifica." });
      return;
    }
    toast.error("Salvataggio non riuscito", { description: errorText(e) });
  };
  const setMonitor = (c, on) => http.post(`/cameras/${c.id}/monitor`, { on }).then((r) => {
    qc.setQueryData(["cameras"], (list = []) => list.map((x) => (x.id === c.id ? { ...x, monitor: r.data.monitor, rev: r.data.rev } : x)));
    return r.data;
  }).catch((e) => { onErr(e); throw e; });
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
          {shown.map((c) => (
            <CameraTile key={c.id} camera={c} onEvents={onEvents} onResult={onResult} compact={cols > 1}
              dragHandle={shown.length > 1 ? handleFor(c.id) : undefined} dragging={dragId === c.id}
              onCameraChange={(nc) => update.mutateAsync(nc)} onMonitor={(on) => setMonitor(c, on)} onEdit={setEditing}
              expanded={expanded === c.id} onToggleExpand={() => setExpanded(expanded === c.id ? null : c.id)} />
          ))}
        </div>
      </div>
      {/* 1.0.20: la colonna di destra arriva fino in fondo alle telecamere (su schermo largo la sua altezza la
          decide la colonna delle telecamere, gli eventi scorrono dentro); su schermo stretto resta com'era */}
      <div className="monitor-side-wrap xl:col-span-3">
        <div className="monitor-side">
          <CounterGrid result={agg} totals={totals} />
          <LiveEvents events={liveEvents} onOpen={onOpenEvent} />
        </div>
      </div>
      <CameraDialog camera={editing} onClose={() => setEditing(null)} onSave={saveDialog}
        onDelete={(c) => { remove.mutate(c); setEditing(null); }} />
    </section>
  );
}
