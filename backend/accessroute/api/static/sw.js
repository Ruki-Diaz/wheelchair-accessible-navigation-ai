/**
 * AccessRoute AI — Production Service Worker (Stage 14)
 * 
 * Versioned Caches:
 * - accessroute-shell-v1: Application HTML, CSS, JavaScript, icons, font assets.
 * - accessroute-routes-v1: Stored offline route packages and API snapshots.
 * - accessroute-map-v1: Cached map tiles.
 * 
 * Strategies:
 * - Application Shell: Cache First -> Network Fallback
 * - API Data: Network First -> Cached Fallback
 * - Offline Route Packages: Offline First (IndexedDB + Cache)
 */

const SHELL_CACHE = "accessroute-shell-v3-consumer-final";
const ROUTES_CACHE = "accessroute-routes-v1";
const MAP_CACHE = "accessroute-map-v1";

const CURRENT_CACHES = [SHELL_CACHE, ROUTES_CACHE, MAP_CACHE];

const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/static/app.css",
  "/static/app.js",
  "/static/connectivity.js",
  "/static/offline-store.js",
  "/static/sync-manager.js",
  "/static/pwa-manager.js",
  "/static/field-mode.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable.png",
  "/static/icons/icon.svg",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
];

// --- Install Lifecycle ---
self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => {
      // Use addAll with error resilience for CDN assets
      return Promise.allSettled(
        SHELL_ASSETS.map((url) =>
          cache.add(url).catch((err) => {
            console.warn(`[SW] Pre-caching asset skipped: ${url}`, err);
          })
        )
      );
    })
  );
});

// --- Activate Lifecycle & Cache Pruning ---
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (!CURRENT_CACHES.includes(key)) {
            console.log(`[SW] Deleting obsolete cache: ${key}`);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// --- Fetch Event & Strategies ---
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // 1. Bypass non-GET requests (e.g. POST, PUT, DELETE go straight to network)
  if (event.request.method !== "GET") {
    return;
  }

  // 2. Map Tiles Caching (Leaflet / Carto / OSM)
  if (url.hostname.includes("tile.") || url.pathname.includes("/tiles/")) {
    event.respondWith(
      caches.open(MAP_CACHE).then((cache) => {
        return cache.match(event.request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          return fetch(event.request)
            .then((networkResponse) => {
              if (networkResponse && networkResponse.status === 200) {
                cache.put(event.request, networkResponse.clone());
              }
              return networkResponse;
            })
            .catch(() => {
              // Graceful offline fallback: return 204 or transparent pixel
              return new Response("", { status: 204, statusText: "Offline Tile Unavailable" });
            });
        });
      })
    );
    return;
  }

  // 3. API Data Strategy (Network First -> Cache Fallback)
  if (url.pathname.startsWith("/api/v1/")) {
    // Avoid caching sensitive auth routes
    if (url.pathname.includes("/auth/") || url.pathname.includes("/login") || url.pathname.includes("/register")) {
      return;
    }

    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const resClone = networkResponse.clone();
            caches.open(ROUTES_CACHE).then((cache) => {
              cache.put(event.request, resClone);
            });
          }
          return networkResponse;
        })
        .catch(() => {
          return caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
              const headers = new Headers(cachedResponse.headers);
              headers.set("X-AccessRoute-Offline-Cache", "true");
              return new Response(cachedResponse.body, {
                status: cachedResponse.status,
                statusText: cachedResponse.statusText,
                headers: headers
              });
            }
            return new Response(
              JSON.stringify({
                error: "Network unavailable",
                offline: true,
                message: "This resource is unavailable offline."
              }),
              { status: 503, headers: { "Content-Type": "application/json" } }
            );
          });
        })
    );
    return;
  }

  // 4. Application Shell Strategy (Network First with Cache Fallback for fresh UI assets)
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const resClone = networkResponse.clone();
          caches.open(SHELL_CACHE).then((cache) => {
            cache.put(event.request, resClone);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        return caches.match(event.request, { ignoreSearch: true }).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          // Offline fallback for navigation requests
          if (event.request.mode === "navigate") {
            return caches.match("/", { ignoreSearch: true });
          }
        });
      })
  );
});

// --- Skip Waiting & Message Listener ---
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    console.log("[SW] Received SKIP_WAITING signal, activating now.");
    self.skipWaiting();
  }
});

// --- Background Sync API (where supported) ---
self.addEventListener("sync", (event) => {
  if (event.tag === "sync-accessibility-reports") {
    console.log("[SW] Background sync triggered for accessibility reports");
    event.waitUntil(notifyClientsToSync());
  }
});

async function notifyClientsToSync() {
  const allClients = await self.clients.matchAll({ includeUncontrolled: true, type: "window" });
  for (const client of allClients) {
    client.postMessage({ type: "TRIGGER_SYNC" });
  }
}
