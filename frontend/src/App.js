import { useCallback, useRef, useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import LocalAuthProvider from "@/components/auth/LocalAuthProvider";
import { Protected, SignInPage, SignUpPage } from "@/components/auth/AuthPages";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import { http } from "@/lib/api";
import { beep, desktopNotify } from "@/lib/alarm";
import AppHeader from "@/components/AppHeader";
import MonitorView from "@/components/MonitorView";
import EventLog from "@/components/EventLog";
import Analytics from "@/components/Analytics";
import ClipArchive from "@/components/ClipArchive";
import AlertRules from "@/components/AlertRules";
import SettingsSheet from "@/components/SettingsSheet";
import SnapshotDialog from "@/components/SnapshotDialog";

const describe = (a) => {
  const kind = a.zone_name ? (a.type === "zona_sosta" ? "sosta in zona" : "ingresso in zona") : a.direction ? (a.direction === "IN" ? "entrata" : "uscita") : "transito";
  return `${a.camera_name ? `${a.camera_name} · ` : ""}${a.class_name} · ${kind} ${a.arrow} ${a.heading}`;
};

function Dashboard() {
  const qc = useQueryClient();
  const [tab, setTab] = useState("monitor");
  const tabRef = useRef(tab);
  tabRef.current = tab;
  const [liveEvents, setLiveEvents] = useState([]);
  const [alertCount, setAlertCount] = useState(0);
  const [openEvent, setOpenEvent] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const { data: health } = useQuery({ queryKey: ["health"], queryFn: () => http.get("/health").then((r) => r.data), refetchInterval: 15000 });
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: () => http.get("/settings").then((r) => r.data) });
  const { data: stats } = useQuery({ queryKey: ["stats", 24], queryFn: () => http.get("/stats", { params: { hours: 24 } }).then((r) => r.data), refetchInterval: 5000 });

  const onEvents = useCallback((evs) => {
    setLiveEvents((prev) => [...evs.slice().reverse(), ...prev].slice(0, 80));
    const alerts = evs.filter((e) => e.alert);
    if (!alerts.length) return;
    if (tabRef.current !== "allarmi") setAlertCount((c) => c + alerts.length);
    const s = qc.getQueryData(["settings"]);
    alerts.forEach((a) => {
      toast.error(`ALLERTA: ${a.alert_rule}`, { description: describe(a) });
      if (s?.desktop_notifications) desktopNotify(`ALLERTA · ${a.alert_rule}`, describe(a));
    });
    if (s?.sound) beep();
  }, [qc]);

  const save = useMutation({
    mutationFn: (s) => http.put("/settings", s).then((r) => r.data),
    onSuccess: (s) => {
      qc.setQueryData(["settings"], s);
      qc.invalidateQueries({ queryKey: ["cameras"] });
      toast.success("Impostazioni salvate");
    },
    onError: (e) => toast.error("Salvataggio non riuscito", { description: e.response?.data?.detail?.[0]?.msg || e.message }),
  });

  return (
    <div className="min-h-screen bg-app text-gray-200">
      <AppHeader tab={tab} setTab={(t) => { setTab(t); if (t === "allarmi") setAlertCount(0); }} modelOk={health?.model_loaded} alertCount={alertCount} onSettings={() => setSettingsOpen(true)} />
      <main className="p-4 md:p-6">
        <div className={tab === "monitor" ? "" : "hidden"}>
          <MonitorView onEvents={onEvents} liveEvents={liveEvents} totals={stats?.totals} onOpenEvent={setOpenEvent} />
        </div>
        {tab === "registro" && <EventLog onOpen={setOpenEvent} />}
        {tab === "analisi" && <Analytics />}
        {tab === "clip" && <ClipArchive onOpenEvent={setOpenEvent} />}
        {tab === "allarmi" && <AlertRules settings={settings} onSave={save.mutate} />}
      </main>
      <SettingsSheet open={settingsOpen} onOpenChange={setSettingsOpen} settings={settings} onSave={save.mutate} />
      <SnapshotDialog event={openEvent} onClose={() => setOpenEvent(null)} />
      <Toaster theme="system" position="bottom-right" richColors />
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <LocalAuthProvider>
        <Routes>
          <Route path="/sign-in/*" element={<SignInPage />} />
          <Route path="/sign-up/*" element={<SignUpPage />} />
          <Route path="/*" element={<Protected><Dashboard /></Protected>} />
        </Routes>
      </LocalAuthProvider>
    </BrowserRouter>
  );
}

export default App;
