import { ArrowDownToLine, ArrowUpFromLine, Users, Activity, Siren } from "lucide-react";
import { CATEGORY } from "@/lib/api";

function Metric({ testid, label, value, icon: Icon, color, sub }) {
  return (
    <div data-testid={testid} className="panel relative overflow-hidden p-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-gray-500">{label}</span>
        <Icon className="h-4 w-4" style={{ color }} />
      </div>
      <div className="mt-2 font-mono text-3xl font-semibold tabular-nums" style={{ color }} data-testid={`${testid}-value`}>{value}</div>
      {sub && <div className="mt-1 font-mono text-[10px] text-gray-500">{sub}</div>}
      <div className="absolute bottom-0 left-0 h-[2px] w-full" style={{ background: `linear-gradient(90deg, ${color}, transparent)` }} />
    </div>
  );
}

export default function CounterGrid({ result, totals }) {
  const live = result.tracks.filter((t) => !t.fixed);   // le cose ferme non sono "in scena"
  const byCat = live.reduce((a, t) => ({ ...a, [t.category]: (a[t.category] || 0) + 1 }), {});
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Metric testid="counter-in" label="Ingressi" value={result.counts.in} icon={ArrowDownToLine} color="#10B981" sub={`24h: ${totals?.in ?? 0}`} />
        <Metric testid="counter-out" label="Uscite" value={result.counts.out} icon={ArrowUpFromLine} color="#EF4444" sub={`24h: ${totals?.out ?? 0}`} />
        <Metric testid="counter-present" label="In scena ora" value={live.length} icon={Users} color="#06B6D4" sub="oggetti tracciati" />
        <Metric testid="counter-total" label="Eventi 24h" value={totals?.total ?? 0} icon={Activity} color="rgb(var(--g100))" sub={<span className="inline-flex items-center gap-1"><Siren className="h-3 w-3 text-red-400" />{totals?.alerts ?? 0} allarmi</span>} />
      </div>
      <div className="panel grid grid-cols-4 divide-x divide-white/5" data-testid="category-breakdown">
        {Object.entries(CATEGORY).map(([k, c]) => (
          <div key={k} className="px-3 py-2.5" data-testid={`category-count-${k}`}>
            <div className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider text-gray-500">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: c.color }} /> {c.label}
            </div>
            <div className="mt-1 font-mono text-lg tabular-nums" style={{ color: c.color }}>{byCat[k] || 0}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
