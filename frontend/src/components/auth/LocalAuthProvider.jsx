import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { BACKEND, setTokenGetter } from "@/lib/api";

// Accesso locale con password unica (05/11/2026), al posto di Clerk.
const KEY = "sentinelToken";
const AuthContext = createContext(null);
export const useLocalAuth = () => useContext(AuthContext);

const readToken = () => {
  try { return localStorage.getItem(KEY) || ""; } catch { return ""; }
};

export default function LocalAuthProvider({ children }) {
  const [config, setConfig] = useState(null);
  const [failed, setFailed] = useState(false);
  const [token, setTokenState] = useState(readToken);

  const setToken = useCallback((t) => {
    try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch {}
    setTokenState(t || "");
  }, []);

  useEffect(() => { setTokenGetter(() => token || null); }, [token]);
  useEffect(() => {
    const expired = () => { if (config?.password_required) setToken(""); };
    window.addEventListener("sentinel-401", expired);
    return () => window.removeEventListener("sentinel-401", expired);
  }, [config, setToken]);

  // Riprova mentre il backend si avvia (il modello YOLO impiega qualche secondo).
  useEffect(() => {
    let cancelled = false;
    const load = async (attempt = 0) => {
      try {
        const r = await fetch(`${BACKEND}/api/auth/config`);
        if (r.ok) return cancelled || setConfig(await r.json());
      } catch {}
      if (cancelled) return;
      if (attempt >= 40) return setFailed(true);
      setTimeout(() => load(attempt + 1), 1500);
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const logout = useCallback(async () => {
    try { await fetch(`${BACKEND}/api/auth/logout`, { method: "POST", credentials: "include" }); } catch {}
    setToken("");
  }, [setToken]);

  if (failed) return <p style={{ padding: 24 }}>Il server di SentinelAI non risponde. Ricarica la pagina tra qualche secondo.</p>;
  if (!config) return null;
  return (
    <AuthContext.Provider value={{ required: config.password_required, token, setToken, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
