import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { Show, SignIn, SignUp, SignOutButton, UserButton, useAuth } from "@clerk/react";
import { useQuery } from "@tanstack/react-query";
import { ShieldHalf, Hourglass } from "lucide-react";
import { http, setTokenGetter } from "@/lib/api";

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
          <p className="text-gray-400">Persone, veicoli e animali, la loro direzione, zone e allarmi con clip video. Accesso riservato agli utenti autorizzati.</p>
        </div>
        <p className="relative font-mono text-[10px] uppercase tracking-[0.25em] text-gray-500">Vision Guard · YOLOv8</p>
      </div>
      <div className="flex flex-1 items-center justify-center p-6">{children}</div>
    </div>
  );
}

export const SignInPage = () => <AuthShell><SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" withSignUp /></AuthShell>;
export const SignUpPage = () => <AuthShell><SignUp routing="path" path="/sign-up" signInUrl="/sign-in" /></AuthShell>;

function Pending({ me }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-app p-6 text-center" data-testid="pending-approval">
      <Hourglass className="h-10 w-10 text-amber-400" />
      <h1 className="font-heading text-2xl font-semibold text-gray-100">In attesa di approvazione</h1>
      <p className="max-w-md text-sm text-gray-400">Il tuo account <b>{me.email}</b> è stato registrato. Un amministratore deve approvarlo prima che tu possa vedere le telecamere.</p>
      <div className="flex items-center gap-3">
        <UserButton />
        <SignOutButton><button data-testid="pending-signout-button" className="rounded border border-white/10 px-3 py-1.5 font-mono text-[11px] uppercase text-gray-300 hover:text-gray-100">Esci</button></SignOutButton>
      </div>
    </div>
  );
}

function Gate({ children }) {
  const { getToken } = useAuth();
  const [ready, setReady] = useState(false);
  useEffect(() => { setTokenGetter(() => getToken()); setReady(true); }, [getToken]);
  const { data: me, error } = useQuery({ queryKey: ["me"], queryFn: () => http.get("/me").then((r) => r.data), enabled: ready, refetchInterval: (q) => (q.state.data?.role === "in_attesa" ? 10000 : false) });
  if (error) return <p className="p-6 text-sm text-red-400">Impossibile verificare l'accesso: {error.message}</p>;
  if (!me) return null;
  if (me.role === "in_attesa") return <Pending me={me} />;
  return children;
}

export function Protected({ children }) {
  return (
    <>
      <Show when="signed-in"><Gate>{children}</Gate></Show>
      <Show when="signed-out"><Navigate to="/sign-in" replace /></Show>
    </>
  );
}
