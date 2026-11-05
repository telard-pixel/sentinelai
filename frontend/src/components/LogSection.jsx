import { useState } from "react";
import { ClipboardCopy, ScrollText } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { http } from "@/lib/api";

// 05/11/2026: il registro del programma, da copiare e incollare a chi deve aiutare (password e token oscurati).
export default function LogSection() {
  const [text, setText] = useState("");
  const load = async () => {
    const r = await http.get("/log", { params: { lines: 400 } }).then((x) => x.data);
    setText(r.text);
    return r.text;
  };
  const copy = async () => {
    try {
      const t = text || (await load());
      await navigator.clipboard.writeText(t);
      toast.success("Registro copiato", { description: "Incollalo nella chat con Ctrl+V" });
    } catch (e) {
      toast.error("Copia non riuscita", { description: e.message });
    }
  };
  return (
    <div className="space-y-3 rounded-md border border-white/10 bg-black/20 p-4" data-testid="log-section">
      <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-gray-400"><ScrollText className="h-3.5 w-3.5" /> Registro del programma</p>
      <div className="flex items-center gap-2">
        <Button data-testid="log-show-button" size="sm" variant="outline" onClick={load} className="h-8 gap-1 border-white/10 bg-transparent text-xs">Mostra</Button>
        <Button data-testid="log-copy-button" size="sm" onClick={copy} className="h-8 gap-1 bg-emerald-500 text-xs text-[#04130D] hover:bg-emerald-400"><ClipboardCopy className="h-3.5 w-3.5" /> Copia registro</Button>
      </div>
      {text && <pre data-testid="log-text" className="log-box">{text}</pre>}
      <p className="text-[11px] text-gray-500">Password e token non compaiono: si può incollare tranquillamente in chat.</p>
    </div>
  );
}
