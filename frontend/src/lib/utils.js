import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

// 07/11/2026: crypto.randomUUID esiste solo su HTTPS o localhost. Dal CT (http://192.168.0.x) mancava e
// "Completa zona" / "Nuova regola" andavano in errore senza dire niente. getRandomValues invece c'è sempre.
export function newId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// Appunti: navigator.clipboard c'è solo su HTTPS o localhost; altrimenti il vecchio metodo con una casella nascosta.
export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  // Agente 108: una casella aggiunta a document.body perde il fuoco se si è dentro un pannello (Impostazioni) e la
  // copia "riesce" vuota. Il testo si mette direttamente nell'evento copy; la casella resta dentro il pannello.
  let done = false;
  const onCopy = (e) => { e.clipboardData.setData("text/plain", text); e.preventDefault(); done = true; };
  document.addEventListener("copy", onCopy, true);
  const host = document.activeElement?.closest?.("[role=dialog]") || document.body;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  host.appendChild(ta);
  ta.focus();
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } finally {
    host.removeChild(ta);
    document.removeEventListener("copy", onCopy, true);
  }
  if (!ok || !done) throw new Error("il browser non permette di copiare: seleziona il testo del registro e premi Ctrl+C");
}
