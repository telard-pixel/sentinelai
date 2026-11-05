import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, RefreshCw, CheckCircle2, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { http } from "@/lib/api";

const errMsg = (e) => e.response?.data?.detail || e.message;

export default function TelegramPanel({ draft, setDraft }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const { data: st, refetch } = useQuery({ queryKey: ["telegram"], queryFn: () => http.get("/telegram/status").then((r) => r.data) });

  const detect = async () => {
    setBusy(true);
    try {
      const r = await http.post("/telegram/detect-chat").then((x) => x.data);
      setDraft((d) => ({ ...d, telegram_chat_id: r.chat_id, telegram_chat_name: r.chat_name, telegram_enabled: true }));
      qc.invalidateQueries({ queryKey: ["settings"] });
      refetch();
      toast.success("Chat Telegram collegata", { description: r.chat_name });
    } catch (e) {
      toast.error("Collegamento non riuscito", { description: errMsg(e) });
    }
    setBusy(false);
  };
  const test = async () => {
    try {
      await http.post("/telegram/test");
      toast.success("Messaggio di prova inviato su Telegram");
    } catch (e) {
      toast.error("Invio non riuscito", { description: errMsg(e) });
    }
  };

  const ok = st?.token_configured && !st?.error;
  return (
    <div className="panel space-y-4 p-4" data-testid="telegram-panel">
      <div className="flex items-center gap-3">
        <Send className="h-4 w-4 text-cyan-400" />
        <h3 className="font-heading text-base font-semibold text-gray-100">Allarmi su Telegram</h3>
        <Switch data-testid="telegram-enabled-toggle" className="ml-auto" disabled={!draft.telegram_chat_id} checked={draft.telegram_enabled}
          onCheckedChange={(v) => setDraft({ ...draft, telegram_enabled: v })} />
      </div>
      <div className="flex items-center gap-2 text-sm" data-testid="telegram-bot-status">
        {ok ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <AlertCircle className="h-4 w-4 text-amber-400" />}
        <span className="text-gray-300">
          {!st ? "Verifica in corso…" : !st.token_configured ? "Bot non configurato: manca il token del bot" : st.error ? `Token non valido: ${st.error}` : <>Bot <b className="font-mono">@{st.bot_username}</b> pronto</>}
        </span>
      </div>
      {ok && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm text-gray-300">
            Chat: <span data-testid="telegram-chat" className="font-mono text-gray-100">{draft.telegram_chat_id ? `${draft.telegram_chat_name || ""} (${draft.telegram_chat_id})` : "non collegata"}</span>
            <Button data-testid="telegram-detect-button" size="sm" variant="outline" disabled={busy} onClick={detect} className="ml-auto h-8 gap-1 border-white/10 bg-transparent text-xs">
              <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} /> {draft.telegram_chat_id ? "Ricollega" : "Collega chat"}
            </Button>
            <Button data-testid="telegram-test-button" size="sm" variant="outline" disabled={!draft.telegram_chat_id} onClick={test} className="h-8 gap-1 border-white/10 bg-transparent text-xs">
              <Send className="h-3.5 w-3.5" /> Prova
            </Button>
          </div>
          {!draft.telegram_chat_id && (
            <p className="text-xs text-gray-500">Apri <b>@{st.bot_username}</b> su Telegram, premi <b>Avvia</b> (o invia /start), poi torna qui e premi "Collega chat".</p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <label className="flex items-center justify-between rounded border border-white/5 bg-black/20 px-3 py-2 text-xs text-gray-300">Invia foto
              <Switch data-testid="telegram-photo-toggle" checked={draft.telegram_send_photo} onCheckedChange={(v) => setDraft({ ...draft, telegram_send_photo: v })} /></label>
            <label className="flex items-center justify-between rounded border border-white/5 bg-black/20 px-3 py-2 text-xs text-gray-300">Invia clip video
              <Switch data-testid="telegram-clip-toggle" checked={draft.telegram_send_clip} onCheckedChange={(v) => setDraft({ ...draft, telegram_send_clip: v })} /></label>
          </div>
          <p className="text-[11px] text-gray-500">La foto arriva subito (massimo una ogni 15 secondi per telecamera), la clip appena è pronta. Ricordati di premere "Salva regole".</p>
        </div>
      )}
    </div>
  );
}
