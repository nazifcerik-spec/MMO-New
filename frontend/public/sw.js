/* Service worker: installable PWA + read-only offline mode.
   - Never caches or replays non-GET requests: gameplay results are always produced by the server.
   - Static assets: cache-first. Pages and GET /api/v1: network-first with the last good copy as offline fallback. */
const VERSION = "v1";
const STATIC = `static-${VERSION}`;
const RUNTIME = `runtime-${VERSION}`;
const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC).then((c) => c.addAll([OFFLINE_URL, "/icons/icon-192.png"])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== STATIC && k !== RUNTIME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // mutations always go to the network (or fail offline)
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/v1/auth") || url.pathname.startsWith("/api/v1/admin")) return;
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => cache(STATIC, req, res))));
    return;
  }
  if (req.mode === "navigate" || url.pathname.startsWith("/api/v1/")) {
    event.respondWith(
      fetch(req)
        .then((res) => cache(RUNTIME, req, res))
        .catch(() => caches.match(req).then((hit) => hit || (req.mode === "navigate" ? caches.match(OFFLINE_URL) : Response.error()))),
    );
  }
});

function cache(name, req, res) {
  if (res && res.ok && res.type === "basic") {
    const copy = res.clone();
    caches.open(name).then((c) => c.put(req, copy));
  }
  return res;
}
