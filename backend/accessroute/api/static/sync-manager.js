/**
 * AccessRoute AI — Sync Manager
 * Stage 14 Architecture
 * 
 * Orchestrates idempotent synchronization of locally queued offline reports:
 * - Reads pending mutations from IndexedDB communityQueue
 * - Sends batch to POST /api/v1/offline/sync
 * - Handles Background Sync API or fallback on reconnect/focus
 * - Prevents duplicates using client-generated UUIDs (local_id)
 */

(function (window) {
  "use strict";

  class SyncManager {
    constructor() {
      this.isSyncing = false;
      this.listeners = [];
      this.init();
    }

    init() {
      // 1. Sync when connectivity is restored
      if (window.AccessRouteConnectivity) {
        window.AccessRouteConnectivity.onStateChange((state) => {
          if (state === "ONLINE") {
            this.syncNow();
          }
        });
      }

      // 2. Sync on window focus / visibility change
      window.addEventListener("focus", () => {
        if (window.AccessRouteConnectivity && window.AccessRouteConnectivity.isOnline()) {
          this.syncNow();
        }
      });

      // 3. Listen for Service Worker messages (e.g. background sync)
      if (navigator.serviceWorker) {
        navigator.serviceWorker.addEventListener("message", (event) => {
          if (event.data && event.data.type === "TRIGGER_SYNC") {
            console.log("[SyncManager] Service Worker triggered sync");
            this.syncNow();
          }
        });
      }
    }

    onSyncComplete(callback) {
      if (typeof callback === "function") {
        this.listeners.push(callback);
      }
    }

    async registerBackgroundSync() {
      if ("serviceWorker" in navigator && "SyncManager" in window) {
        try {
          const reg = await navigator.serviceWorker.ready;
          await reg.sync.register("sync-accessibility-reports");
          console.log("[SyncManager] Registered background sync tag: sync-accessibility-reports");
          return true;
        } catch (e) {
          console.warn("[SyncManager] Background sync registration failed:", e);
        }
      }
      return false;
    }

    async syncNow() {
      if (this.isSyncing) return;
      if (!window.AccessRouteOfflineStore) return;
      if (window.AccessRouteConnectivity && !window.AccessRouteConnectivity.isOnline()) {
        console.log("[SyncManager] Offline: Sync postponed.");
        return;
      }

      const pendingItems = await window.AccessRouteOfflineStore.getPendingMutations();
      if (!pendingItems || pendingItems.length === 0) {
        return;
      }

      this.isSyncing = true;
      if (window.AccessRouteConnectivity) {
        window.AccessRouteConnectivity.setSyncing(true);
      }

      console.log(`[SyncManager] Syncing ${pendingItems.length} queued mutations...`);
      if (typeof window.showConsumerToast === "function") {
        window.showConsumerToast(`Syncing ${pendingItems.length} accessibility report${pendingItems.length === 1 ? "" : "s"}…`, "📡");
      }

      try {
        const payload = {
          items: pendingItems.map((item) => ({
            local_id: item.local_id,
            operation_type: item.operation_type,
            payload: item.payload,
            created_at: item.created_at,
            attempt_count: item.attempt_count || 0,
            last_attempt_at: item.last_attempt_at,
            status: item.status
          }))
        };

        const res = await fetch("/api/v1/offline/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          const data = await res.json();
          console.log(`[SyncManager] Sync response: ${data.synced_count} synced, ${data.failed_count} failed`);

          // Update each item in IndexedDB
          for (const itemResult of data.items) {
            await window.AccessRouteOfflineStore.updateMutationStatus(
              itemResult.local_id,
              itemResult.status,
              itemResult.server_id,
              itemResult.error
            );
          }

          if (typeof window.showConsumerToast === "function" && data.synced_count > 0) {
            window.showConsumerToast(data.synced_count === 1 ? "Report synced" : `${data.synced_count} reports synced`, "✓");
          }

          this.notifyListeners(data);
        } else {
          console.warn("[SyncManager] Sync endpoint returned non-200:", res.status);
          for (const item of pendingItems) {
            await window.AccessRouteOfflineStore.updateMutationStatus(
              item.local_id,
              "FAILED_RETRYABLE",
              null,
              `Server returned status ${res.status}`
            );
          }
        }
      } catch (err) {
        console.error("[SyncManager] Network error during sync:", err);
        for (const item of pendingItems) {
          await window.AccessRouteOfflineStore.updateMutationStatus(
            item.local_id,
            "FAILED_RETRYABLE",
            null,
            err.message
          );
        }
      } finally {
        this.isSyncing = false;
        if (window.AccessRouteConnectivity) {
          window.AccessRouteConnectivity.setSyncing(false);
        }
      }
    }

    notifyListeners(result) {
      for (const cb of this.listeners) {
        try {
          cb(result);
        } catch (e) {
          console.error("[SyncManager] Listener error:", e);
        }
      }
    }
  }

  window.AccessRouteSync = new SyncManager();
})(window);
