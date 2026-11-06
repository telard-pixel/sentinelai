import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, FolderInput, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { http } from "@/lib/api";

// 1.0.5: le clip sono file .mp4 in una cartella che si sceglie qui (prima stavano dentro il database).
// Nella finestra del programma per Windows "Scegli…" e "Apri cartella" usano le finestre di Windows
// (window.pywebview.api); nel browser si scrive il percorso a mano.
const desktop = () => window.pywebview?.api;

export default function ClipsFolderSection() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["storage"], queryFn: () => http.get("/storage").then((r) => r.data), refetchInterval: 15000 });
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [hasApi, setHasApi] = useState(!!desktop());

  useEffect(() => { if (data) setFolder(data.clips_folder_chosen || ""); }, [data?.clips_folder_chosen]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const ready = () => setHasApi(!!desktop());
    window.addEventListener("pywebviewready", ready);
    return () => window.removeEventListener("pywebviewready", ready);
  }, []);

  const save = async (value) => {
    setBusy(true);
    try {
      const r = await http.put("/storage/folder", { folder: value }).then((x) => x.data);
      qc.setQueryData(["storage"], r);
      toast.success("Cartella dei video salvata", { description: `Le clip nuove vanno in ${r.clips_folder}` });
    } catch (e) {
      toast.error("Cartella non utilizzabile", { description: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const choose = async () => {
    const picked = await desktop()?.choose_folder(data?.clips_folder || "");
    if (picked) { setFolder(picked); save(picked); }
  };

  const moveHere = async () => {
    const n = (data?.clips_in_db || 0) + (data?.clips_elsewhere || 0);
    if (!window.confirm(`Spostare ${n} video nella cartella ${data?.clips_folder}?`)) return;
    setBusy(true);
    try {
      const r = await http.post("/storage/move-clips").then((x) => x.data);
      qc.setQueryData(["storage"], r);
      qc.invalidateQueries({ queryKey: ["clips"] });
      toast.success(`${r.moved} video spostati`, { description: r.failed ? `${r.failed} non spostati (file mancanti o cartella piena)` : undefined });
    } catch (e) {
      toast.error("Spostamento non riuscito", { description: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const toMove = (data?.clips_in_db || 0) + (data?.clips_elsewhere || 0);
  return (
    <div className="space-y-3 rounded-md border border-white/10 bg-black/20 p-4" data-testid="clips-folder-section">
      <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-gray-400"><FolderOpen className="h-3.5 w-3.5" /> Dove salvo i video</p>
      <p className="text-xs text-gray-300" data-testid="clips-folder-current">
        Cartella in uso: <span className="break-all font-mono text-emerald-400">{data?.clips_folder || "—"}</span>
        {data && <span className="text-gray-500"> · {data.clips_files_mb} MB di video</span>}
      </p>
      {data?.clips_folder_warning && (
        <p className="flex gap-2 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] text-amber-300" data-testid="clips-folder-warning">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{data.clips_folder_warning}
        </p>
      )}
      <div className="flex gap-2">
        <Input data-testid="clips-folder-input" value={folder} onChange={(e) => setFolder(e.target.value)}
               placeholder={data?.clips_folder_default || "Percorso completo, es. D:\\Video\\SentinelAI"}
               className="h-8 border-white/10 bg-black/30 font-mono text-xs" />
        {hasApi && <Button data-testid="clips-folder-choose" size="sm" variant="outline" disabled={busy} onClick={choose} className="h-8 shrink-0 border-white/10 bg-transparent text-xs">Scegli…</Button>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button data-testid="clips-folder-save" size="sm" disabled={busy || folder.trim() === (data?.clips_folder_chosen || "")} onClick={() => save(folder.trim())} className="h-7 text-xs">Usa questa cartella</Button>
        {!!data?.clips_folder_chosen && <Button data-testid="clips-folder-default" size="sm" variant="ghost" disabled={busy} onClick={() => { setFolder(""); save(""); }} className="h-7 text-xs text-gray-400">Torna alla predefinita</Button>}
        {hasApi && <Button data-testid="clips-folder-open" size="sm" variant="ghost" onClick={() => desktop()?.open_folder(data?.clips_folder || "")} className="ml-auto h-7 gap-1 text-xs text-gray-300"><FolderOpen className="h-3.5 w-3.5" /> Apri cartella</Button>}
      </div>
      {toMove > 0 && (
        <div className="flex items-center gap-2 rounded border border-white/5 bg-black/30 p-2 text-[11px] text-gray-400" data-testid="clips-move">
          <span>{data.clips_in_db ? `${data.clips_in_db} video sono ancora dentro il database` : ""}{data.clips_in_db && data.clips_elsewhere ? " e " : ""}{data.clips_elsewhere ? `${data.clips_elsewhere} in un'altra cartella` : ""}.</span>
          <Button data-testid="clips-move-button" size="sm" variant="outline" disabled={busy} onClick={moveHere} className="ml-auto h-7 shrink-0 gap-1 border-white/10 bg-transparent text-xs"><FolderInput className="h-3.5 w-3.5" /> Porta qui tutti i video</Button>
        </div>
      )}
      <p className="text-[11px] text-gray-500">Una sottocartella per giorno, file tipo <span className="font-mono">Garage_213005_ab12cd.mp4</span>. Va bene anche un disco esterno o una cartella di rete: se non è raggiungibile le clip vanno nella cartella predefinita e qui compare un avviso.</p>
    </div>
  );
}
