import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const pad = (n) => String(n).padStart(2, "0");
const HOURS = Array.from({ length: 24 }, (_, i) => pad(i));
const MINUTES = Array.from({ length: 12 }, (_, i) => pad(i * 5));

function Part({ testid, value, options, onChange }) {
  const opts = options.includes(value) ? options : [...options, value].sort();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger data-testid={testid} className="h-8 w-[62px] border-white/10 bg-black/30 px-2 font-mono text-xs"><SelectValue /></SelectTrigger>
      <SelectContent className="max-h-64 border-white/10 bg-slate-900/95 backdrop-blur-md">
        {opts.map((o) => <SelectItem key={o} value={o} className="font-mono text-xs">{o}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

export default function TimeSelect({ value, onChange, testid }) {
  const [h, m] = (value || "00:00").split(":");
  return (
    <div className="flex items-center gap-1" data-testid={testid}>
      <Part testid={`${testid}-hour`} value={h} options={HOURS} onChange={(v) => onChange(`${v}:${m}`)} />
      <span className="font-mono text-xs text-gray-500">:</span>
      <Part testid={`${testid}-minute`} value={m} options={MINUTES} onChange={(v) => onChange(`${h}:${v}`)} />
    </div>
  );
}
