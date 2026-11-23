/* WeildBuild update service worker.
   Serves the activated update cache (wb-update-<version>) for
   same-origin GETs after the updater commits an update. Without an
   active update marker it does nothing - every request goes straight
   to the network. Cross-origin traffic (Main Server, Realtime,
   GitHub) is never touched. */

const META_CACHE = "wb-meta";
const META_KEY = "wb-active-update";

let activeCacheName = null;

async function readActiveCacheName() {
  if (activeCacheName) return activeCacheName;
  try {
    const meta = await caches.open(META_CACHE);
    const res = await meta.match(META_KEY);
    if (res) {
      const data = await res.json();
      if (data && data.cacheName) {
        activeCacheName = data.cacheName;
        return activeCacheName;
      }
    }
  } catch (e) {
    /* no marker yet - stay network-only */
  }
  return null;
}

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await readActiveCacheName();
      await self.clients.claim();
    })()
  );
});

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "wb-sw-activate" && data.cacheName) {
    activeCacheName = data.cacheName;
    self.clients.claim();
  }
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith(
    (async () => {
      const cacheName = await readActiveCacheName();
      if (cacheName) {
        try {
          const cache = await caches.open(cacheName);
          const hit = await cache.match(req, { ignoreSearch: true });
          if (hit) return hit;
          if (req.mode === "navigate") {
            const index = await cache.match("/index.html");
            if (index) return index;
          }
        } catch (e) {
          /* fall through to network */
        }
      }
      return fetch(req);
    })()
  );
});
