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
        <p className="relative font-mono text-[10px] uppercase tracking-[0.25em] text-gray-500">Vision Guard · YOLO11</p>
      </div>
      <div className="flex flex-1 items-center justify-center p-6">{children}</div>
    </div>
  );
}

export function SignInPage() {
  const { required, token, setToken } = useLocalAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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
        <Input data-testid="login-password" type="password" autoFocus autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} placeholder="Password" className="h-10 border-white/10 bg-black/30" />
        <Button data-testid="login-submit" type="submit" disabled={busy || !password} className="w-full gap-2 bg-emerald-500 font-mono text-xs uppercase tracking-wider text-[#04130D] hover:bg-emerald-400">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />} Entra
        </Button>
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
