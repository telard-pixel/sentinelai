import { useQuery } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";
import { API, http } from "@/lib/api";

export default function ClipPlayer({ clipId, compact = false, testid = "clip" }) {
  const { data } = useQuery({
    queryKey: ["clip", clipId],
    queryFn: () => http.get(`/clips/${clipId}/meta`).then((r) => r.data),
    refetchInterval: (q) => (q.state.data?.status === "recording" ? 2000 : false),
  });
  if (!data || data.status === "recording") {
    return (
      <div data-testid={`${testid}-recording`} className="force-dark flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-md border border-white/10 bg-black text-sm text-gray-400">
        <Loader2 className="h-6 w-6 animate-spin text-red-400" /> Registrazione della clip in corso…
      </div>
    );
  }
  if (data.status !== "ready") return <p data-testid={`${testid}-failed`} className="text-sm text-red-400">Clip non disponibile</p>;
  return (
    <div className="space-y-2" data-testid={`${testid}-player`}>
      <div className="force-dark overflow-hidden rounded-md border border-white/10 bg-black">
        <video data-testid={`${testid}-video`} src={`${API}/clips/${clipId}/video`} controls autoPlay muted playsInline loop={compact} className="w-full" />
      </div>
      {!compact && (
        <div className="flex items-center gap-3 font-mono text-[11px] text-gray-500">
          <span>Clip allarme · {data.duration}s · {data.frames} fotogrammi · {(data.size / 1024).toFixed(0)} KB</span>
          <a data-testid={`${testid}-download`} href={`${API}/clips/${clipId}/video?download=true`} className="ml-auto flex items-center gap-1 text-emerald-400 hover:underline">
            <Download className="h-3.5 w-3.5" /> Scarica MP4
          </a>
        </div>
      )}
    </div>
  );
}
