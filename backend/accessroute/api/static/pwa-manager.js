/**
 * AccessRoute AI — PWA Manager
 * Stage 14 Architecture
 * 
 * Handles:
 * - Service Worker registration & updates
 * - Deferred updates during active navigation
 * - PWA Install prompt handling & iOS home screen instructions
 * - Screen Wake Lock API during navigation
 * - Offline Map Provider abstraction & canvas fallback
 * - Storage quota monitoring & management dialog
 */

(function (window) {
  "use strict";

  class PWAManager {
    constructor() {
      this.deferredInstallPrompt = null;
      this.wakeLockSentinel = null;
      this.waitingWorker = null;
      this.isNavigating = false;
      this.updateDeferred = false;
      this.init();
    }

    async init() {
      // 1. Register Service Worker
      this.registerServiceWorker();

      // 2. Install Prompt Listener (Chromium/Android)
      window.addEventListener("beforeinstallprompt", (e) => {
        e.preventDefault();
        this.deferredInstallPrompt = e;
        this.showInstallBannerIfNeeded();
      });

      // 3. Track App Installed
      window.addEventListener("appinstalled", () => {
        console.log("[PWA] AccessRoute installed to home screen.");
        this.deferredInstallPrompt = null;
        this.hideInstallBanner();
      });

      // 4. Handle Visibility Change for Wake Lock
      document.addEventListener("visibilitychange", async () => {
        if (this.wakeLockSentinel !== null && document.visibilityState === "visible" && this.isNavigating) {
          await this.requestWakeLock();
        }
      });
    }

    async registerServiceWorker() {
      if (!("serviceWorker" in navigator)) return;

      try {
        const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
        console.log("[PWA] Service Worker registered with scope:", reg.scope);

        // Check for updates
        reg.addEventListener("updatefound", () => {
          const newWorker = reg.installing;
          newWorker.addEventListener("statechange", () => {
            if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
              console.log("[PWA] New service worker version waiting.");
              this.waitingWorker = newWorker;
              this.handleAppUpdateAvailable();
            }
          });
        });

        // Controller change listener
        navigator.serviceWorker.addEventListener("controllerchange", () => {
          window.location.reload();
        });
      } catch (err) {
        console.warn("[PWA] Service Worker registration failed:", err);
      }
    }

    handleAppUpdateAvailable() {
      if (this.isNavigating) {
        console.log("[PWA] Active navigation in progress: Deferring app update prompt.");
        this.updateDeferred = true;
        return;
      }
      this.showUpdateBanner();
    }

    showUpdateBanner() {
      const banner = document.getElementById("pwa-update-banner");
      if (banner) {
        banner.hidden = false;
      }
    }

    applyAppUpdate() {
      if (this.waitingWorker) {
        this.waitingWorker.postMessage({ type: "SKIP_WAITING" });
      } else {
        window.location.reload();
      }
    }

    dismissAppUpdate() {
      const banner = document.getElementById("pwa-update-banner");
      if (banner) banner.hidden = true;
    }

    // --- Active Navigation Hooks ---
    setNavigating(isNavigating) {
      this.isNavigating = isNavigating;
      if (isNavigating) {
        this.requestWakeLock();
      } else {
        this.releaseWakeLock();
        // If an update was deferred during navigation, show it now
        if (this.updateDeferred) {
          this.updateDeferred = false;
          this.showUpdateBanner();
        }
      }
    }

    // --- Screen Wake Lock API ---
    async requestWakeLock() {
      if ("wakeLock" in navigator && !this.wakeLockSentinel) {
        try {
          this.wakeLockSentinel = await navigator.wakeLock.request("screen");
          this.wakeLockSentinel.addEventListener("release", () => {
            this.wakeLockSentinel = null;
          });
          console.log("[PWA] Screen Wake Lock active.");
        } catch (err) {
          console.warn("[PWA] Wake Lock request failed:", err);
        }
      }
    }

    async releaseWakeLock() {
      if (this.wakeLockSentinel) {
        try {
          await this.wakeLockSentinel.release();
          this.wakeLockSentinel = null;
          console.log("[PWA] Screen Wake Lock released.");
        } catch (err) {
          console.warn("[PWA] Wake Lock release failed:", err);
        }
      }
    }

    // --- Install Banner & Modal ---
    showInstallBannerIfNeeded() {
      // Don't nag if dismissed within last 7 days
      const lastDismissed = localStorage.getItem("accessroute_pwa_dismissed");
      if (lastDismissed) {
        const diffDays = (Date.now() - parseInt(lastDismissed, 10)) / (1000 * 60 * 60 * 24);
        if (diffDays < 7) return;
      }

      // Check if already in standalone mode
      if (window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone) {
        return;
      }

      const banner = document.getElementById("pwa-install-banner");
      if (banner) banner.hidden = false;
    }

    hideInstallBanner() {
      const banner = document.getElementById("pwa-install-banner");
      if (banner) banner.hidden = true;
    }

    dismissInstallBanner() {
      localStorage.setItem("accessroute_pwa_dismissed", Date.now().toString());
      this.hideInstallBanner();
    }

    async triggerInstallPrompt() {
      if (this.deferredInstallPrompt) {
        this.deferredInstallPrompt.prompt();
        const choice = await this.deferredInstallPrompt.userChoice;
        console.log("[PWA] User install choice:", choice.outcome);
        this.deferredInstallPrompt = null;
        this.hideInstallBanner();
      } else {
        // Check for iOS
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
        if (isIOS) {
          this.showIOSInstallModal();
        } else {
          alert("To install AccessRoute, tap your browser's menu (⋮ or Share) and select 'Add to Home Screen' or 'Install App'.");
        }
      }
    }

    showIOSInstallModal() {
      const modal = document.getElementById("ios-install-modal");
      if (modal && typeof modal.showModal === "function") {
        modal.showModal();
      } else if (modal) {
        modal.hidden = false;
      }
    }

    closeIOSInstallModal() {
      const modal = document.getElementById("ios-install-modal");
      if (modal && typeof modal.close === "function") {
        modal.close();
      } else if (modal) {
        modal.hidden = true;
      }
    }

    // --- Storage Management UI ---
    async openStorageModal() {
      const modal = document.getElementById("storage-manager-modal");
      if (!modal) return;

      if (window.AccessRouteOfflineStore) {
        const stats = await window.AccessRouteOfflineStore.getStats();
        const routesCountEl = document.getElementById("storage-routes-count");
        const missionsCountEl = document.getElementById("storage-missions-count");
        const queueCountEl = document.getElementById("storage-queue-count");
        const usageMbEl = document.getElementById("storage-usage-mb");

        if (routesCountEl) routesCountEl.textContent = stats.routesCount;
        if (missionsCountEl) missionsCountEl.textContent = stats.missionsCount;
        if (queueCountEl) queueCountEl.textContent = stats.pendingQueueCount;
        if (usageMbEl) usageMbEl.textContent = `${stats.storageEstimate.usageMB} MB / ${stats.storageEstimate.quotaMB} MB (${stats.storageEstimate.percentUsed}% used)`;

        // Render downloaded routes list
        const routesListEl = document.getElementById("storage-routes-list");
        if (routesListEl) {
          const routes = await window.AccessRouteOfflineStore.listRoutes();
          if (routes.length === 0) {
            routesListEl.innerHTML = `<li class="storage-item-empty">No downloaded offline routes.</li>`;
          } else {
            routesListEl.innerHTML = routes.map(r => `
              <li class="storage-route-row">
                <div class="storage-route-info">
                  <strong>${r.destination_name || 'Route'}</strong>
                  <span>${r.distance_m}m • Downloaded: ${new Date(r.downloaded_at).toLocaleDateString()}</span>
                </div>
                <button type="button" class="btn btn-outline btn-sm btn-danger" onclick="deleteOfflineRoute('${r.route_id}')">Delete</button>
              </li>
            `).join("");
          }
        }
      }

      if (typeof modal.showModal === "function") {
        modal.showModal();
      } else {
        modal.hidden = false;
      }
    }

    closeStorageModal() {
      const modal = document.getElementById("storage-manager-modal");
      if (modal && typeof modal.close === "function") {
        modal.close();
      } else if (modal) {
        modal.hidden = true;
      }
    }

    async clearDownloadedData() {
      const confirmed = confirm("Are you sure you want to clear all downloaded routes and missions? (Unsynced community reports will be preserved)");
      if (!confirmed) return;

      if (window.AccessRouteOfflineStore) {
        await window.AccessRouteOfflineStore.clearAllData(true);
        alert("Downloaded routes and missions cleared.");
        this.openStorageModal();
      }
    }

    // --- Offline Canvas Fallback (Mode C) ---
    renderOfflineNavigationCanvas(canvas, userLat, userLon, routeCoords, currentStep) {
      if (!canvas || !routeCoords || routeCoords.length < 2) return;
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;

      ctx.fillStyle = "#0f172a";
      ctx.fillRect(0, 0, w, h);

      // Compute bounding box
      const lats = routeCoords.map(p => p[0]);
      const lons = routeCoords.map(p => p[1]);
      if (userLat) lats.push(userLat);
      if (userLon) lons.push(userLon);

      const minLat = Math.min(...lats);
      const maxLat = Math.max(...lats);
      const minLon = Math.min(...lons);
      const maxLon = Math.max(...lons);

      const pad = 40;
      const scaleX = (w - pad * 2) / Math.max(0.0001, (maxLon - minLon));
      const scaleY = (h - pad * 2) / Math.max(0.0001, (maxLat - minLat));

      const toScreen = (lat, lon) => {
        const x = pad + (lon - minLon) * scaleX;
        const y = h - (pad + (lat - minLat) * scaleY);
        return [x, y];
      };

      // Draw route path
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 6;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      for (let i = 0; i < routeCoords.length; i++) {
        const [x, y] = toScreen(routeCoords[i][0], routeCoords[i][1]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Destination Marker
      const destPt = routeCoords[routeCoords.length - 1];
      const [destX, destY] = toScreen(destPt[0], destPt[1]);
      ctx.fillStyle = "#ef4444";
      ctx.beginPath();
      ctx.arc(destX, destY, 10, 0, 2 * Math.PI);
      ctx.fill();

      // Current GPS Marker
      if (userLat && userLon) {
        const [ux, uy] = toScreen(userLat, userLon);
        ctx.fillStyle = "#10b981";
        ctx.beginPath();
        ctx.arc(ux, uy, 8, 0, 2 * Math.PI);
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // HUD Overlay banner
      ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
      ctx.fillRect(10, 10, w - 20, 60);
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 14px Inter, sans-serif";
      ctx.fillText("Offline Canvas Mode — Map Tiles Unavailable", 20, 32);
      ctx.font = "12px Inter, sans-serif";
      ctx.fillStyle = "#94a3b8";
      ctx.fillText(currentStep ? currentStep.instruction : "Follow route line to destination", 20, 52);
    }
  }

  window.AccessRoutePWA = new PWAManager();
})(window);
