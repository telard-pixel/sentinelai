let ctx;

export function beep() {
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "square";
    o.frequency.value = 880;
    g.gain.value = 0.06;
    o.connect(g).connect(ctx.destination);
    o.start();
    o.frequency.setValueAtTime(620, ctx.currentTime + 0.15);
    o.stop(ctx.currentTime + 0.4);
  } catch (e) {
    /* audio unavailable */
  }
}

export function desktopNotify(title, body) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    new Notification(title, { body, icon: "/icon-192.png", tag: "sentinel-alert" });
  } catch (e) {
    navigator.serviceWorker?.ready.then((r) => r.showNotification(title, { body, icon: "/icon-192.png" }));
  }
}

export async function askNotifyPermission() {
  if (!("Notification" in window)) return "unsupported";
  return Notification.requestPermission();
}
