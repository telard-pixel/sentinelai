import { useCallback, useEffect, useRef, useState } from "react";
import { WS_URL, getAuthToken } from "@/lib/api";

const EMPTY = { tracks: [], counts: { in: 0, out: 0 }, fps: 0, zones_active: [] };

export function useStream(onEvents) {
  const videoRef = useRef(null);
  const wsRef = useRef(null);
  const mediaRef = useRef(null);
  const urlRef = useRef(null);
  const capRef = useRef(null);
  const pendingRef = useRef(null);
  const [sessionId, setSessionId] = useState(0);
  const onEventsRef = useRef(onEvents);
  onEventsRef.current = onEvents;
  const [status, setStatus] = useState({ state: "idle", source: null, error: null });
  const [result, setResult] = useState(EMPTY);
  const [frame, setFrame] = useState(null);
  const [dims, setDims] = useState({ w: 16, h: 9 });
  const startRef = useRef(null);
  const retryRef = useRef(null);

  const sendFrame = useCallback(() => {
    const ws = wsRef.current;
    const v = videoRef.current;
    if (!ws || ws.readyState !== 1 || !v) return;
    if (v.readyState < 2 || v.paused || !v.videoWidth) {
      setTimeout(sendFrame, 150);
      return;
    }
    const c = (capRef.current = capRef.current || document.createElement("canvas"));
    const scale = Math.min(1, 640 / v.videoWidth);
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    c.toBlob((b) => {
      if (!b || ws.readyState !== 1) return setTimeout(sendFrame, 150);
      if (pendingRef.current) URL.revokeObjectURL(pendingRef.current);
      pendingRef.current = URL.createObjectURL(b);
      ws.send(b);
    }, "image/jpeg", 0.72);
  }, []);

  const showPending = () => {
    const url = pendingRef.current;
    pendingRef.current = null;
    if (!url) return;
    setFrame((prev) => {
      if (prev?.startsWith("blob:")) URL.revokeObjectURL(prev);
      return url;
    });
  };

  const stop = useCallback(() => {
    clearTimeout(retryRef.current);
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) ws.close();
    mediaRef.current?.getTracks().forEach((t) => t.stop());
    mediaRef.current = null;
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.srcObject = null;
      v.removeAttribute("src");
      v.load();
    }
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    if (pendingRef.current) URL.revokeObjectURL(pendingRef.current);
    pendingRef.current = null;
    setFrame((prev) => {
      if (prev?.startsWith("blob:")) URL.revokeObjectURL(prev);
      return null;
    });
    setResult(EMPTY);
    setStatus({ state: "idle", source: null, error: null });
  }, []);

  const handleMessage = useCallback(
    (ws, source) => (e) => {
      if (wsRef.current !== ws) return;
      const m = JSON.parse(e.data);
      if (m.type === "ready") {
        setStatus({ state: "live", source, error: null });
        if (!["rtsp", "nvr"].includes(source)) sendFrame();
        return;
      }
      if (m.type === "error") {
        setStatus({ state: "error", source, error: m.message });
        return;
      }
      if (m.type === "frame") {
        setFrame(`data:image/jpeg;base64,${m.image}`);
        setDims({ w: m.width, h: m.height });
      }
      if (m.type === "detections") showPending();
      setResult({ tracks: m.tracks, counts: m.counts, fps: m.fps, zones_active: m.zones_active || [] });
      if (m.events?.length) onEventsRef.current?.(m.events);
      if (m.type === "detections") sendFrame();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sendFrame],
  );

  const start = useCallback(
    async ({ cameraId, source, deviceId, file }) => {
      stop();
      setSessionId((n) => n + 1);
      setStatus({ state: "connecting", source, error: null });
      const v = videoRef.current;
      try {
        if (source === "webcam") {
          const media = await navigator.mediaDevices.getUserMedia({
            video: deviceId ? { deviceId: { exact: deviceId } } : { width: 1280, height: 720 },
          });
          mediaRef.current = media;
          v.srcObject = media;
        } else if (source === "file" || source === "demo") {
          if (file) urlRef.current = URL.createObjectURL(file);
          v.src = file ? urlRef.current : "/demo.mp4";
          v.loop = true;
        }
        if (!["rtsp", "nvr"].includes(source)) {
          v.muted = true;
          await v.play();
          setDims({ w: v.videoWidth || 16, h: v.videoHeight || 9 });
        }
      } catch (err) {
        setStatus({ state: "error", source, error: `Sorgente non disponibile: ${err.message}` });
        return;
      }
      const ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent((await getAuthToken()) || "")}`);
      wsRef.current = ws;
      ws.onopen = () =>
        ws.send(JSON.stringify({ type: "start", camera_id: cameraId, tz_offset: new Date().getTimezoneOffset() }));
      ws.onmessage = handleMessage(ws, source);
      ws.onclose = () => {
        if (wsRef.current !== ws) return;          // chiusa apposta con stop()
        if (["rtsp", "nvr"].includes(source)) {
          // 06/11/2026: le telecamere di rete le controlla il server; la finestra si ricollega da sola.
          setStatus({ state: "error", source, error: "Connessione al motore persa: mi ricollego…" });
          retryRef.current = setTimeout(() => { if (wsRef.current === ws) startRef.current?.({ cameraId, source, deviceId, file }); }, 4000);
        } else {
          setStatus({ state: "error", source, error: "Connessione al motore AI persa." });
        }
      };
    },
    [stop, handleMessage],
  );
  startRef.current = start;

  const send = useCallback((msg) => {
    if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(msg));
  }, []);

  useEffect(() => stop, [stop]);

  return { videoRef, status, result, frame, dims, setDims, start, stop, send, sessionId };
}
