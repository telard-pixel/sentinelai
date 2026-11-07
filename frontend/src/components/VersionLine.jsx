import { useEffect, useState } from "react";
import { Info } from "lucide-react";
import { http } from "@/lib/api";

// 1.0.10 (richiesta di Roberto): in fondo alle Impostazioni si vede quale versione è installata.
export default function VersionLine() {
  const [v, setV] = useState("");
  useEffect(() => {
    let alive = true;
    http.get("/version").then((r) => alive && setV(r.data?.version || "")).catch(() => {});
    return () => { alive = false; };
  }, []);
  return (
    <p data-testid="app-version" className="flex items-center justify-center gap-2 font-mono text-[11px] uppercase tracking-wider text-gray-500">
      <Info className="h-3.5 w-3.5" /> SentinelAI {v ? `versione ${v}` : "…"}
    </p>
  );
}
