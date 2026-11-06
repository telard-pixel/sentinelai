import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { BACKEND, setTokenGetter } from "@/lib/api";
import SplashScreen from "@/components/SplashScreen";

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

  const refreshConfig = useCallback(async () => {
    const r = await fetch(`${BACKEND}/api/auth/config`);
    if (r.ok) setConfig(await r.json());
  }, []);

  useEffect(() => {
    // 4° giro dell'agente: dopo la PRIMA password le altre finestre non sapevano che ora serve: si rilegge la
    // configurazione e poi si toglie il gettone, così compare la pagina di accesso.
    const expired = async () => { try { await refreshConfig(); } catch {} setToken(""); };
    window.addEventListener("sentinel-401", expired);
    return () => window.removeEventListener("sentinel-401", expired);
  }, [refreshConfig, setToken]);

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

  // Un solo logo in apertura per tutto l'avvio (stesso posto nell'albero): non ricomincia quando il server risponde.
  return (
    <>
      {config && (
        <AuthContext.Provider value={{ required: config.password_required, fromEnv: !!config.password_from_env, token, setToken, logout, refreshConfig }}>
          {children}
        </AuthContext.Provider>
      )}
      <SplashScreen ready={!!config} message={failed ? "Il motore non risponde: ricarica la pagina tra qualche secondo." : undefined} />
    </>
  );
}
