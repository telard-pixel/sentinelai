import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CATEGORY, http } from "@/lib/api";
import HeatmapCard from "@/components/HeatmapCard";

const tip = { contentStyle: { background: "rgb(var(--raised))", border: "1px solid rgb(var(--c-white) / 0.1)", color: "rgb(var(--g200))", fontFamily: "JetBrains Mono", fontSize: 11 } };
const axis = { stroke: "#6B7280", fontSize: 10, fontFamily: "JetBrains Mono", tickLine: false, axisLine: false };

function Card({ title, testid, children, className = "" }) {
  return (
    <div className={`panel p-4 ${className}`} data-testid={testid}>
      <h3 className="mb-4 font-mono text-[10px] uppercase tracking-[0.2em] text-gray-500">{title}</h3>
      {children}
    </div>
  );
}

export default function Analytics() {
  const [hours, setHours] = useState(24);
  const { data } = useQuery({ queryKey: ["stats", hours], queryFn: () => http.get("/stats", { params: { hours } }).then((r) => r.data), refetchInterval: 10000 });
  const step = hours > 48 ? 24 : 1;
  const hourly = (data?.hourly || []).filter((_, i) => i % step === 0 || step === 1).map((h) => ({
    ...h,
    label: new Date(h.hour).toLocaleString("it-IT", step === 1 ? { hour: "2-digit", minute: "2-digit" } : { day: "2-digit", month: "2-digit" }),
  }));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h2 className="mr-auto font-heading text-2xl font-semibold text-gray-100">Analisi flussi</h2>
        {[[24, "24 ore"], [168, "7 giorni"]].map(([h, l]) => (
          <button key={h} data-testid={`stats-range-${h}`} onClick={() => setHours(h)}
            className={`rounded border px-3 py-1.5 font-mono text-[11px] uppercase ${hours === h ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400" : "border-white/10 text-gray-400"}`}>{l}</button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[["Totale eventi", data?.totals.total, "rgb(var(--g100))"], ["Entrate", data?.totals.in, "#10B981"], ["Uscite", data?.totals.out, "#EF4444"], ["Allarmi", data?.totals.alerts, "#F59E0B"]].map(([l, v, c]) => (
          <div key={l} className="panel p-4" data-testid={`stats-total-${l.toLowerCase().replace(/ /g, "-")}`}>
            <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-gray-500">{l}</div>
            <div className="mt-1 font-mono text-3xl tabular-nums" style={{ color: c }}>{v ?? 0}</div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Card title="Flusso orario ingressi / uscite / transiti" testid="hourly-chart" className="lg:col-span-8">
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={hourly}>
              <defs>
                {[["in", "#10B981"], ["out", "#EF4444"], ["tr", "#06B6D4"]].map(([k, c]) => (
                  <linearGradient key={k} id={`g-${k}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={c} stopOpacity={0.35} /><stop offset="100%" stopColor={c} stopOpacity={0} /></linearGradient>
                ))}
              </defs>
              <CartesianGrid stroke="rgba(128,128,128,0.15)" vertical={false} />
              <XAxis dataKey="label" {...axis} minTickGap={24} />
              <YAxis {...axis} allowDecimals={false} width={30} />
              <Tooltip {...tip} />
              <Area type="monotone" dataKey="in" name="Entrate" stroke="#10B981" fill="url(#g-in)" strokeWidth={2} />
              <Area type="monotone" dataKey="out" name="Uscite" stroke="#EF4444" fill="url(#g-out)" strokeWidth={2} />
              <Area type="monotone" dataKey="transiti" name="Transiti" stroke="#06B6D4" fill="url(#g-tr)" strokeWidth={2} />
              <Area type="monotone" dataKey="zone" name="Zone" stroke="#F472B6" fill="none" strokeWidth={2} strokeDasharray="4 3" />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Distribuzione categorie" testid="category-pie-chart" className="lg:col-span-4">
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie data={(data?.by_category || []).map((d) => ({ ...d, label: CATEGORY[d.name]?.label }))} dataKey="value" nameKey="label" innerRadius={60} outerRadius={100} paddingAngle={3} stroke="none">
                {(data?.by_category || []).map((d) => <Cell key={d.name} fill={CATEGORY[d.name]?.color} />)}
              </Pie>
              <Tooltip {...tip} />
            </PieChart>
          </ResponsiveContainer>
        </Card>
        <div className="lg:col-span-12"><HeatmapCard /></div>
        <Card title="Oggetti più rilevati" testid="top-classes-chart" className="lg:col-span-12">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data?.by_class || []} layout="vertical" margin={{ left: 30 }}>
              <XAxis type="number" {...axis} allowDecimals={false} />
              <YAxis type="category" dataKey="name" {...axis} width={90} />
              <Tooltip {...tip} cursor={{ fill: "rgba(128,128,128,0.08)" }} />
              <Bar dataKey="value" name="Eventi" fill="#10B981" radius={[0, 3, 3, 0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  );
}
