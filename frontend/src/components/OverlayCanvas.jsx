import { useEffect, useRef, useState } from "react";
import { CATEGORY } from "@/lib/api";

function drawLine(ctx, line, W, H, editing) {
  const x1 = line.x1 * W, y1 = line.y1 * H, x2 = line.x2 * W, y2 = line.y2 * H;
  ctx.save();
  ctx.strokeStyle = "#F59E0B";
  ctx.lineWidth = 3;
  ctx.setLineDash(editing ? [] : [12, 8]);
  ctx.shadowColor = "#F59E0B";
  ctx.shadowBlur = 10;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.restore();
  const lx = x2 - x1, ly = y2 - y1, len = Math.hypot(lx, ly) || 1;
  const nx = -ly / len, ny = lx / len, mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  const sign = line.invert ? -1 : 1;
  ctx.font = "600 12px 'JetBrains Mono', monospace";
  [["IN", "#10B981", sign], ["OUT", "#EF4444", -sign]].forEach(([t, c, s]) => {
    const px = mx + nx * 26 * s, py = my + ny * 26 * s;
    ctx.fillStyle = "rgba(9,13,20,0.85)";
    ctx.fillRect(px - 20, py - 10, 40, 20);
    ctx.strokeStyle = c;
    ctx.lineWidth = 1;
    ctx.strokeRect(px - 20, py - 10, 40, 20);
    ctx.fillStyle = c;
    ctx.textAlign = "center";
    ctx.fillText(t, px, py + 4);
  });
  if (editing) {
    [[x1, y1, "A"], [x2, y2, "B"]].forEach(([x, y, t]) => {
      ctx.fillStyle = "#F59E0B";
      ctx.beginPath();
      ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#090D14";
      ctx.textAlign = "center";
      ctx.fillText(t, x, y + 4);
    });
  }
}

function drawZone(ctx, z, W, H, active, draft) {
  if (!z.points.length) return;
  const c = active ? "#EF4444" : z.color || "#F472B6";
  ctx.save();
  ctx.beginPath();
  z.points.forEach(([x, y], i) => (i ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H)));
  if (!draft) ctx.closePath();
  ctx.fillStyle = active ? "rgba(239,68,68,0.22)" : "rgba(244,114,182,0.08)";
  if (!draft) ctx.fill();
  ctx.strokeStyle = c;
  ctx.lineWidth = active ? 3 : 2;
  ctx.setLineDash(draft ? [6, 5] : []);
  ctx.stroke();
  ctx.setLineDash([]);
  if (draft) {
    z.points.forEach(([x, y]) => {
      ctx.fillStyle = c;
      ctx.beginPath();
      ctx.arc(x * W, y * H, 5, 0, Math.PI * 2);
      ctx.fill();
    });
  } else {
    const [x0, y0] = z.points.reduce(([a, b], [x, y]) => [Math.min(a, x), Math.min(b, y)], [1, 1]);
    const label = `${active ? "● " : ""}${z.name.toUpperCase()}${z.dwell_seconds ? ` · ${z.dwell_seconds}s` : ""}`;
    ctx.font = "600 10px 'JetBrains Mono', monospace";
    const w = ctx.measureText(label).width + 10;
    ctx.fillStyle = c;
    ctx.fillRect(x0 * W, y0 * H, w, 16);
    ctx.fillStyle = "#090D14";
    ctx.textAlign = "left";
    ctx.fillText(label, x0 * W + 5, y0 * H + 11.5);
  }
  ctx.restore();
}

function drawTrack(ctx, t, W, H) {
  const c = CATEGORY[t.category]?.color || "#fff";
  const [x1, y1, x2, y2] = [t.box[0] * W, t.box[1] * H, t.box[2] * W, t.box[3] * H];
  ctx.strokeStyle = c;
  ctx.lineWidth = 2;
  ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  const cl = Math.min(14, (x2 - x1) / 3);
  ctx.lineWidth = 4;
  [[x1, y1, 1, 1], [x2, y1, -1, 1], [x1, y2, 1, -1], [x2, y2, -1, -1]].forEach(([x, y, sx, sy]) => {
    ctx.beginPath();
    ctx.moveTo(x + cl * sx, y);
    ctx.lineTo(x, y);
    ctx.lineTo(x, y + cl * sy);
    ctx.stroke();
  });
  const label = `#${t.id} ${t.label.toUpperCase()} ${Math.round(t.conf * 100)}% ${t.arrow}`;
  ctx.font = "600 11px 'JetBrains Mono', monospace";
  const w = ctx.measureText(label).width + 10;
  ctx.fillStyle = c;
  ctx.fillRect(x1, Math.max(0, y1 - 18), w, 18);
  ctx.fillStyle = "#090D14";
  ctx.textAlign = "left";
  ctx.fillText(label, x1 + 5, Math.max(13, y1 - 5));
  if (t.angle !== null) {
    const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
    const mag = Math.hypot(t.dx * W, t.dy * H) || 1;
    const L = Math.min(70, Math.max(30, mag));
    const ux = (t.dx * W) / mag, uy = (t.dy * H) / mag;
    const ex = cx + ux * L, ey = cy + uy * L;
    ctx.strokeStyle = "#06B6D4";
    ctx.fillStyle = "#06B6D4";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    const a = Math.atan2(uy, ux);
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - 11 * Math.cos(a - 0.45), ey - 11 * Math.sin(a - 0.45));
    ctx.lineTo(ex - 11 * Math.cos(a + 0.45), ey - 11 * Math.sin(a + 0.45));
    ctx.fill();
  }
}

export default function OverlayCanvas({ tracks, line, showLine, mode, onLineChange, zones = [], zonesActive = [], zoneDraft, onZonePoint }) {
  const editing = mode === "line";
  const ref = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [draft, setDraft] = useState(line);
  const drag = useRef(null);

  useEffect(() => setDraft(line), [line]);

  useEffect(() => {
    const el = ref.current;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cv = ref.current;
    const dpr = window.devicePixelRatio || 1;
    cv.width = size.w * dpr;
    cv.height = size.h * dpr;
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    zones.filter((z) => z.enabled).forEach((z) => drawZone(ctx, z, size.w, size.h, zonesActive.includes(z.id)));
    if (zoneDraft?.length) drawZone(ctx, { points: zoneDraft, color: "#F59E0B" }, size.w, size.h, false, true);
    tracks.forEach((t) => drawTrack(ctx, t, size.w, size.h));
    if (showLine && (draft?.enabled || editing)) drawLine(ctx, draft, size.w, size.h, editing);
  }, [tracks, draft, editing, size, showLine, zones, zonesActive, zoneDraft]);

  const pos = (e) => {
    const r = ref.current.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  const onDown = (e) => {
    if (mode === "zone") {
      const p = pos(e);
      onZonePoint([Math.round(p.x * 1000) / 1000, Math.round(p.y * 1000) / 1000]);
      return;
    }
    if (!editing) return;
    const p = pos(e);
    const d1 = Math.hypot((p.x - draft.x1) * size.w, (p.y - draft.y1) * size.h);
    const d2 = Math.hypot((p.x - draft.x2) * size.w, (p.y - draft.y2) * size.h);
    drag.current = d1 < d2 ? "1" : "2";
    ref.current.setPointerCapture(e.pointerId);
    setDraft((l) => ({ ...l, [`x${drag.current}`]: p.x, [`y${drag.current}`]: p.y }));
  };
  const onMove = (e) => {
    if (!drag.current) return;
    const p = pos(e);
    setDraft((l) => ({ ...l, [`x${drag.current}`]: p.x, [`y${drag.current}`]: p.y }));
  };
  const onUp = () => {
    if (!drag.current) return;
    drag.current = null;
    onLineChange(draft);
  };

  return (
    <canvas
      ref={ref}
      data-testid="live-stream-canvas"
      className={`absolute inset-0 h-full w-full ${mode ? "cursor-crosshair touch-none" : "pointer-events-none"}`}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
    />
  );
}
