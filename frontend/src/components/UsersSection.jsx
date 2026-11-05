import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { toast } from "sonner";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { http } from "@/lib/api";

const LABEL = { admin: "Amministratore", operatore: "Operatore", in_attesa: "In attesa" };

export default function UsersSection() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => http.get("/me").then((r) => r.data) });
  const { data } = useQuery({ queryKey: ["users"], queryFn: () => http.get("/users").then((r) => r.data), enabled: me?.role === "admin" });
  // Con l'accesso locale (password unica) c'è un solo utente: niente da gestire.
  if (me?.role !== "admin" || me?.env === "locale" || !data) return null;
  const change = async (u, role) => {
    try {
      await http.patch(`/users/${u.user_id}/role`, { role });
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(`${u.email}: ${LABEL[role]}`);
    } catch (e) {
      toast.error("Modifica non riuscita", { description: e.response?.data?.detail || e.message });
    }
  };
  return (
    <div className="space-y-3 rounded-md border border-white/10 bg-black/20 p-4" data-testid="users-section">
      <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-gray-400"><Users className="h-3.5 w-3.5" /> Utenti e accessi</p>
      {data.users.map((u) => (
        <div key={u.user_id} className="flex items-center gap-2" data-testid={`user-row-${u.user_id}`}>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-gray-100">{u.name || u.email}</p>
            <p className="truncate font-mono text-[10px] text-gray-500">{u.email}</p>
          </div>
          <Select value={u.role} onValueChange={(v) => change(u, v)} disabled={u.user_id === me.user_id}>
            <SelectTrigger data-testid={`user-role-${u.user_id}`} className={`h-8 w-40 border-white/10 bg-black/30 text-xs ${u.role === "in_attesa" ? "text-amber-400" : ""}`}><SelectValue /></SelectTrigger>
            <SelectContent className="border-white/10 bg-slate-900/95 backdrop-blur-md">
              {data.roles.map((r) => <SelectItem key={r} value={r}>{LABEL[r] || r}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      ))}
      <p className="text-[11px] text-gray-500">I nuovi utenti che accedono con Google restano "In attesa" finché non li approvi come Operatore.</p>
    </div>
  );
}
