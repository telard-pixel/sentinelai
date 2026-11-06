import { useState } from "react";
import { KeyRound } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { http } from "@/lib/api";
import { useLocalAuth } from "@/components/auth/LocalAuthProvider";

// 06/11/2026: la password di accesso la scegliete voi, dall'app (niente file da modificare).
export default function PasswordSection() {
  const auth = useLocalAuth();
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [rep, setRep] = useState("");
  const [busy, setBusy] = useState(false);
  if (!auth) return null;
  const has = auth.required;
  const save = async (remove = false) => {
    if (!remove && nw !== rep) return toast.error("Le due password nuove non coincidono");
    if (remove && !window.confirm("Togliere la password? Chiunque apra l'app sul PC entrerà senza password.")) return;
    setBusy(true);
    try {
      const r = await http.put("/auth/password", { current: cur, new: remove ? "" : nw }).then((x) => x.data);
      auth.setToken(r.token || "");
      await auth.refreshConfig();
      setCur(""); setNw(""); setRep("");
      toast.success(remove ? "Password tolta" : has ? "Password cambiata" : "Password impostata",
        { description: remove ? undefined : "Gli altri dispositivi già entrati dovranno rientrare." });
    } catch (e) {
      const d = e.response?.data?.detail;
      toast.error("Non riuscito", { description: Array.isArray(d) ? d[0]?.msg : d || e.message });
    }
    setBusy(false);
  };
  const inp = "h-9 border-white/10 bg-black/30 text-sm";
  return (
    <div className="space-y-3 rounded-md border border-white/10 bg-black/20 p-4" data-testid="password-section">
      <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-gray-400"><KeyRound className="h-3.5 w-3.5" /> Password di accesso</p>
      <p className="text-xs text-gray-400" data-testid="password-state">{has ? "Attiva: per entrare serve la password." : "Nessuna password: l'app si apre senza chiedere niente."}</p>
      {has && <Input data-testid="password-current" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} placeholder="Password attuale" className={inp} />}
      <Input data-testid="password-new" type="password" autoComplete="new-password" value={nw} onChange={(e) => setNw(e.target.value)} placeholder={has ? "Password nuova (almeno 6 caratteri)" : "Password (almeno 6 caratteri)"} className={inp} />
      <Input data-testid="password-repeat" type="password" autoComplete="new-password" value={rep} onChange={(e) => setRep(e.target.value)} placeholder="Ripeti la password" className={inp} />
      <div className="flex items-center gap-2">
        <Button data-testid="password-save" size="sm" disabled={busy || nw.length < 6 || (has && !cur)} onClick={() => save(false)} className="h-8 bg-emerald-500 text-xs text-[#04130D] hover:bg-emerald-400">{has ? "Cambia password" : "Imposta password"}</Button>
        {has && !auth.fromEnv && <Button data-testid="password-remove" size="sm" variant="ghost" disabled={busy || !cur} onClick={() => save(true)} className="h-8 text-xs text-red-400 hover:text-red-300">Togli password</Button>}
      </div>
    </div>
  );
}
