// Logo in apertura (06/11/2026, richiesta di Roberto): si vede mentre il programma si avvia e il motore YOLO si
// carica, poi sfuma. Resta almeno MIN_MS così non "lampeggia" quando il server è già pronto.
import { useEffect, useState } from "react";

const MIN_MS = 1600;

export function Logo({ size = 120 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true">
      <defs>
        <linearGradient id="sl-g" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#34D399" />
          <stop offset="100%" stopColor="#059669" />
        </linearGradient>
      </defs>
      <path className="splash-shield" d="M256 70 L400 122 V244 C400 340 338 404 256 436 C174 404 112 340 112 244 V122 Z"
        fill="#10B981" fillOpacity=".12" stroke="url(#sl-g)" strokeWidth="22" strokeLinejoin="round" />
      <path d="M256 70 V436 C174 404 112 340 112 244 V122 Z" fill="#10B981" fillOpacity=".45" />
      <circle className="splash-eye" cx="256" cy="248" r="44" fill="#06B6D4" />
      <circle cx="256" cy="248" r="18" fill="#050506" />
    </svg>
  );
}

export default function SplashScreen({ ready, message }) {
  const [minDone, setMinDone] = useState(false);
  const [gone, setGone] = useState(false);
  useEffect(() => { const t = setTimeout(() => setMinDone(true), MIN_MS); return () => clearTimeout(t); }, []);
  const leaving = ready && minDone;
  useEffect(() => {
    if (!leaving) return undefined;
    const t = setTimeout(() => setGone(true), 600);
    return () => clearTimeout(t);
  }, [leaving]);
  if (gone) return null;
  return (
    <div className={`splash ${leaving ? "splash-out" : ""}`} data-testid="splash-screen" role="status" aria-live="polite">
      <div className="splash-grid" />
      <div className="splash-center">
        <div className="splash-logo"><Logo size={128} /><span className="splash-scan" /></div>
        <div className="splash-title">SENTINEL<span>·AI</span></div>
        <div className="splash-sub">VISION GUARD</div>
        <div className="splash-bar"><span /></div>
        <div className="splash-msg">{message || "Avvio del motore YOLO11…"}</div>
      </div>
    </div>
  );
}
