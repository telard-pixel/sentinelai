import axios from "axios";

// Vuoto = stesso indirizzo da cui è aperta l'app (nginx passa /api al backend): così funziona
// uguale da LAN, da Tailscale e installata come app, senza ricompilare.
export const BACKEND = (process.env.REACT_APP_BACKEND_URL || window.location.origin).replace(/\/$/, "");
export const API = `${BACKEND}/api`;
export const WS_URL = `${BACKEND.replace(/^http/, "ws")}/api/ws/stream`;
export const http = axios.create({ baseURL: API });
// 06/11/2026 (agente di prova): con il gettone scaduto a finestra aperta le API davano 401 senza tornare al login.
http.interceptors.response.use((r) => r, (err) => {
  if (err.response?.status === 401 && !String(err.config?.url || "").startsWith("/auth/")) window.dispatchEvent(new Event("sentinel-401"));
  return Promise.reject(err);
});
export const TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { return ""; } })();
export const snapshotUrl = (id) => `${API}/events/${id}/snapshot`;

export const CATEGORY = {
  persona: { label: "Persone", color: "#10B981" },
  veicolo: { label: "Veicoli", color: "#06B6D4" },
  animale: { label: "Animali", color: "#F59E0B" },
  oggetto: { label: "Oggetti", color: "#F472B6" },
};

export const fmtTime = (iso) =>
  new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const fmtDate = (iso) => new Date(iso).toLocaleDateString("it-IT");

let tokenGetter = null;
export const setTokenGetter = (fn) => { tokenGetter = fn; };
export const getAuthToken = async () => (tokenGetter ? tokenGetter() : null);
http.interceptors.request.use(async (cfg) => {
  const t = await getAuthToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});
