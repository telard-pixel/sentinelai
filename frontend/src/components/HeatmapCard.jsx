import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { API, CATEGORY, http } from "@/lib/api";
import HeatmapCanvas, { useHeatmap } from "@/components/HeatmapCanvas";

export default function HeatmapCard() {
  const { data: cameras = [] } = useQuery({ queryKey: ["cameras"], queryFn: () => http.get("/cameras").then((r) => r.data) });
  const [camId, setCamId] = useState(null);
  const [cat, setCat] = useState(null);
  const id = camId || cameras[0]?.id;
  const [data, setData] = useHeatmap(id, cat, !!id, 10000);
  const [bgKey, setBgKey] = useState(Date.now());

  const reset = async () => {
    if (!window.confirm("Azzerare la mappa di calore di questa telecamera?")) return;
    await http.delete(`/cameras/${id}/heatmap`);
    setData((d) => d && { ...d, grid: d.grid.map(() => 0), max: 0, total: 0 });
    toast.success("Mappa di calore azzerata");
  };

  return (
    <div className="panel p-4" data-testid="heatmap-card">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h3 className="mr-auto font-mono text-[10px] uppercase tracking-[0.2em] text-gray-500">Mappa di calore dei percorsi</h3>
        {cameras.map((c) => (
          <button key={c.id} data-testid={`heatmap-camera-${c.id}`} onClick={() => { setCamId(c.id); setBgKey(Date.now()); }}
            className={`rounded border px-2.5 py-1 font-mono text-[11px] ${id === c.id ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400" : "border-white/10 text-gray-400"}`}>{c.name}</button>
        ))}
        <span className="mx-1 h-5 w-px bg-white/10" />
        {[[null, "Tutti", "rgb(var(--g100))"], ...Object.entries(CATEGORY).map(([k, v]) => [k, v.label, v.color])].map(([k, l, c]) => (
          <button key={l} data-testid={`heatmap-cat-${k || "all"}`} onClick={() => setCat(k)} className="rounded border px-2 py-1 font-mono text-[11px]"
            style={cat === k ? { borderColor: c, color: c, background: `${c}14` } : { borderColor: "rgb(var(--c-white) / 0.1)", color: "rgb(var(--g400))" }}>{l}</button>
        ))}
        <button data-testid="heatmap-reset-button" onClick={reset} title="Azzera" className="rounded p-1.5 text-gray-500 hover:text-red-400"><RotateCcw className="h-4 w-4" /></button>
      </div>
      {id ? (
        <div className="force-dark relative mx-auto aspect-video max-h-[60vh] w-full overflow-hidden rounded-md bg-[#05080D]">
          <img key={`${id}-${bgKey}`} src={`${API}/cameras/${id}/background?t=${bgKey}`} alt="" data-testid="heatmap-background"
            onError={(e) => { e.currentTarget.style.display = "none"; }} className="absolute inset-0 h-full w-full object-fill opacity-60 grayscale" />
          {data && <HeatmapCanvas data={data} opacity={0.85} />}
          <div className="absolute bottom-2 left-2 flex items-center gap-2 rounded bg-black/70 px-2 py-1 font-mono text-[10px] text-gray-300">
            <span>poco</span><span className="h-2 w-24 rounded" style={{ background: "linear-gradient(90deg,#06B6D4,#10B981,#F59E0B,#EF4444)" }} /><span>molto</span>
            <span className="ml-2 text-gray-500" data-testid="heatmap-total">{data?.total ?? 0} passaggi</span>
          </div>
          {data && data.total === 0 && <p className="absolute inset-0 grid place-items-center"><span className="rounded bg-black/70 px-3 py-1.5 text-sm text-gray-200">Nessun percorso registrato: avvia il monitoraggio di questa telecamera.</span></p>}
        </div>
      ) : (
        <p className="py-10 text-center text-sm text-gray-500">Nessuna telecamera configurata</p>
      )}
    </div>
  );
}
