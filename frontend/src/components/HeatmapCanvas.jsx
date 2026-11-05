import { useEffect, useRef, useState } from "react";
import { http } from "@/lib/api";

const STOPS = [
  [0, [6, 182, 212]],
  [0.35, [16, 185, 129]],
  [0.65, [245, 158, 11]],
  [1, [239, 68, 68]],
];

function colorAt(t) {
  for (let i = 1; i < STOPS.length; i++) {
    const [p1, c1] = STOPS[i - 1];
    const [p2, c2] = STOPS[i];
    if (t <= p2) {
      const k = (t - p1) / (p2 - p1);
      return c1.map((v, j) => Math.round(v + (c2[j] - v) * k));
    }
  }
  return STOPS[STOPS.length - 1][1];
}

export function useHeatmap(cameraId, category, enabled, refreshMs = 10000) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!enabled || !cameraId) return undefined;
    let alive = true;
    const load = () =>
      http.get(`/cameras/${cameraId}/heatmap`, { params: category ? { category } : {} }).then((r) => alive && setData(r.data)).catch(() => {});
    load();
    const t = setInterval(load, refreshMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [cameraId, category, enabled, refreshMs]);
  return [data, setData];
}

export default function HeatmapCanvas({ data, opacity = 0.75, testid = "heatmap-canvas" }) {
  const ref = useRef(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv || !data) return;
    const small = document.createElement("canvas");
    small.width = data.w;
    small.height = data.h;
    const sctx = small.getContext("2d");
    const img = sctx.createImageData(data.w, data.h);
    const max = Math.max(1, data.max);
    data.grid.forEach((v, i) => {
      if (!v) return;
      const t = Math.sqrt(v / max);
      const [r, g, b] = colorAt(t);
      img.data.set([r, g, b, Math.round(90 + 165 * t)], i * 4);
    });
    sctx.putImageData(img, 0, 0);
    const rect = cv.getBoundingClientRect();
    cv.width = rect.width;
    cv.height = rect.height;
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.filter = "blur(6px)";
    ctx.drawImage(small, 0, 0, cv.width, cv.height);
  }, [data]);
  return <canvas ref={ref} data-testid={testid} className="pointer-events-none absolute inset-0 h-full w-full mix-blend-screen" style={{ opacity }} />;
}
