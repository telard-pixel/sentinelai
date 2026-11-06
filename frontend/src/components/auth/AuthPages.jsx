import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ShieldHalf, LogIn, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { BACKEND, http } from "@/lib/api";
import { useLocalAuth } from "@/components/auth/LocalAuthProvider";

function AuthShell({ children }) {
  return (
    <div className="flex min-h-screen bg-app">
      <div className="force-dark relative hidden flex-1 flex-col justify-between overflow-hidden bg-[#090D14] p-12 lg:flex">
        <div className="hud-grid absolute inset-0 opacity-40" />
        <div className="relative flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded border border-emerald-500/40 bg-emerald-500/10"><ShieldHalf className="h-5 w-5 text-emerald-400" /></div>
          <span className="font-heading text-xl font-bold tracking-[0.12em] text-gray-100">SENTINEL<span className="text-emerald-400">·AI</span></span>
        </div>
        <div className="relative max-w-md space-y-3">
          <h1 className="font-heading text-4xl font-bold text-gray-100">Monitoraggio telecamere con AI locale</h1>
          <p className="text-gray-400">Persone, veicoli e animali, la loro direzione, zone e allarmi con clip video. Accesso riservato.</p>
        </div>
        <p className="relative font-mono text-[10px] uppercase tracking-[0.25em] text-gray-500">Vision Guard · YOLOv8</p>
      </div>
      <div className="flex flex-1 items-center justify-center p-6">{children}</div>
    </div>
  );
}

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.6 13.3l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
    <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.7 6c4.5-4.2 6.9-10.3 6.9-17.7z" />
    <path fill="#FBBC05" d="M10.5 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.9-6.1C.9 16.6 0 20.2 0 24s.9 7.4 2.6 10.7l7.9-6.1z" />
    <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.7-6c-2.2 1.5-5 2.3-8.2 2.3-6.3 0-11.6-4.1-13.5-9.9l-7.9 6.1C6.6 42.6 14.6 48 24 48z" />
  </svg>
);

export function SignInPage() {
  const { required, google, token, setToken } = useLocalAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hasPassword, setHasPassword] = useState(true);
  // Ritorno dal login con Google: il gettone (o l'errore) arriva dopo il #, che non passa mai dal server.
  useEffect(() => {
    const h = new URLSearchParams(window.location.hash.slice(1));
    if (h.get("token") || h.get("errore")) window.history.replaceState(null, "", window.location.pathname);
    if (h.get("token")) { setToken(h.get("token")); navigate("/", { replace: true }); }
    else if (h.get("errore")) setError(h.get("errore"));
    fetch(`${BACKEND}/api/auth/config`).then((r) => r.json()).then((c) => setHasPassword(!!c.password)).catch(() => {});
  }, [setToken, navigate]);
  if (!required || token) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${BACKEND}/api/auth/login`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || `Errore ${r.status}`);
      setToken(data.token);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  return (
    <AuthShell>
      <form onSubmit={submit} className="panel w-full max-w-sm space-y-4 p-6" data-testid="login-form">
        <div className="flex items-center gap-2 lg:hidden">
          <ShieldHalf className="h-5 w-5 text-emerald-400" />
          <span className="font-heading text-lg font-bold tracking-[0.12em] text-gray-100">SENTINEL<span className="text-emerald-400">·AI</span></span>
        </div>
        <h2 className="font-heading text-xl font-semibold text-gray-100">Accedi</h2>
        {google && (
          <a data-testid="login-google" href={`${BACKEND}/api/auth/google/start`} className="google-btn"><GoogleIcon /> Accedi con Google</a>
        )}
        {google && hasPassword && <div className="login-sep">oppure</div>}
        {hasPassword && (
          <>
            <Input data-testid="login-password" type="password" autoFocus={!google} autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} placeholder="Password" className="h-10 border-white/10 bg-black/30" />
            <Button data-testid="login-submit" type="submit" disabled={busy || !password} className="w-full gap-2 bg-emerald-500 font-mono text-xs uppercase tracking-wider text-[#04130D] hover:bg-emerald-400">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />} Entra
            </Button>
          </>
        )}
        {error && <p data-testid="login-error" className="text-sm text-red-400">{error}</p>}
      </form>
    </AuthShell>
  );
}

export const SignUpPage = () => <Navigate to="/sign-in" replace />;

function Gate({ children }) {
  const { setToken } = useLocalAuth();
  const { data: me, error } = useQuery({ queryKey: ["me"], queryFn: () => http.get("/me").then((r) => r.data), retry: false });
  const expired = error?.response?.status === 401;
  useEffect(() => { if (expired) setToken(""); }, [expired, setToken]);
  if (expired) return <Navigate to="/sign-in" replace />;
  if (error) return <p className="p-6 text-sm text-red-400">Impossibile verificare l'accesso: {error.message}</p>;
  if (!me) return null;
  return children;
}

export function Protected({ children }) {
  const { required, token } = useLocalAuth();
  if (required && !token) return <Navigate to="/sign-in" replace />;
  return <Gate>{children}</Gate>;
}
