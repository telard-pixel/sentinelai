/* Service worker di SentinelAI: rende l'app installabile e la apre anche se il server riparte.
   Le chiamate /api (video, eventi, clip) passano SEMPRE dalla rete: niente dati vecchi in cache. */
const CACHE = "sentinelai-v2";
const SHELL = ["/", "/manifest.json", "/icon-192.png", "/icon-512.png", "/favicon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api")) return;
  if (e.request.mode === "navigate") {
    // Pagina: prima la rete (versione aggiornata), se il server non risponde la copia salvata.
    e.respondWith(fetch(e.request).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put("/", copy)); }   // mai salvare una pagina di errore
      return r;
    }).catch(() => caches.match("/")));
    return;
  }
  if (url.pathname.startsWith("/static/") || SHELL.includes(url.pathname)) {
    // File con nome che cambia a ogni versione: cache, poi rete.
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return r;
    })));
  }
});
