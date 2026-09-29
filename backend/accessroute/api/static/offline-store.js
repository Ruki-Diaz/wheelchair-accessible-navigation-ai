/**
 * AccessRoute AI — Offline Store (IndexedDB abstraction)
 * Stage 14 Architecture
 * 
 * Manages client-side storage for:
 * - routes: Downloaded OfflineRoutePackage objects
 * - routeEvidence: Correlated evidence snapshots
 * - communityQueue: Queued observations awaiting sync
 * - verificationMissions: Offline survey missions
 * - mapRegions: Cached region metadata
 * - syncMetadata: Telemetry and last-synced timestamps
 */

(function (window) {
  "use strict";

  const DB_NAME = "accessroute_offline_db";
  const DB_VERSION = 1;

  const STORES = {
    ROUTES: "routes",
    EVIDENCE: "routeEvidence",
    QUEUE: "communityQueue",
    MISSIONS: "verificationMissions",
    MAP_REGIONS: "mapRegions",
    METADATA: "syncMetadata"
  };

  class OfflineStore {
    constructor() {
      this.db = null;
      this._initPromise = null;
    }

    async init() {
      if (this.db) return this.db;
      if (this._initPromise) return this._initPromise;

      this._initPromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);

        request.onupgradeneeded = (event) => {
          const db = event.target.result;

          if (!db.objectStoreNames.contains(STORES.ROUTES)) {
            db.createObjectStore(STORES.ROUTES, { keyPath: "route_id" });
          }
          if (!db.objectStoreNames.contains(STORES.EVIDENCE)) {
            db.createObjectStore(STORES.EVIDENCE, { keyPath: "route_id" });
          }
          if (!db.objectStoreNames.contains(STORES.QUEUE)) {
            const queueStore = db.createObjectStore(STORES.QUEUE, { keyPath: "local_id" });
            queueStore.createIndex("status", "status", { unique: false });
            queueStore.createIndex("created_at", "created_at", { unique: false });
          }
          if (!db.objectStoreNames.contains(STORES.MISSIONS)) {
            db.createObjectStore(STORES.MISSIONS, { keyPath: "mission_id" });
          }
          if (!db.objectStoreNames.contains(STORES.MAP_REGIONS)) {
            db.createObjectStore(STORES.MAP_REGIONS, { keyPath: "region_id" });
          }
          if (!db.objectStoreNames.contains(STORES.METADATA)) {
            db.createObjectStore(STORES.METADATA, { keyPath: "key" });
          }
        };

        request.onsuccess = (event) => {
          this.db = event.target.result;
          resolve(this.db);
        };

        request.onerror = (event) => {
          console.error("[OfflineStore] IndexedDB open error:", event.target.error);
          reject(event.target.error);
        };
      });

      return this._initPromise;
    }

    // --- Route Operations ---
    async saveRoute(routePackage) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.ROUTES], "readwrite");
        const store = tx.objectStore(STORES.ROUTES);
        const req = store.put(routePackage);
        req.onsuccess = () => resolve(true);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    async getRoute(routeId) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.ROUTES], "readonly");
        const store = tx.objectStore(STORES.ROUTES);
        const req = store.get(routeId);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    async listRoutes() {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.ROUTES], "readonly");
        const store = tx.objectStore(STORES.ROUTES);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    async getAllRoutes() {
      return this.listRoutes();
    }

    async deleteRoute(routeId) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.ROUTES], "readwrite");
        const store = tx.objectStore(STORES.ROUTES);
        const req = store.delete(routeId);
        req.onsuccess = () => resolve(true);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    // --- Offline Community Queue Operations ---
    async queueMutation(mutationItem) {
      await this.init();
      if (!mutationItem.local_id) {
        mutationItem.local_id = (crypto.randomUUID ? crypto.randomUUID() : "q_" + Date.now() + "_" + Math.random().toString(36).substring(2, 9));
      }
      if (!mutationItem.created_at) {
        mutationItem.created_at = new Date().toISOString();
      }
      if (!mutationItem.status) {
        mutationItem.status = "PENDING";
      }

      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.QUEUE], "readwrite");
        const store = tx.objectStore(STORES.QUEUE);
        const req = store.put(mutationItem);
        req.onsuccess = () => resolve(mutationItem);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    async getPendingMutations() {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.QUEUE], "readonly");
        const store = tx.objectStore(STORES.QUEUE);
        const req = store.getAll();
        req.onsuccess = () => {
          const all = req.result || [];
          const pending = all.filter(item => item.status === "PENDING" || item.status === "FAILED_RETRYABLE");
          resolve(pending);
        };
        req.onerror = (e) => reject(e.target.error);
      });
    }

    async updateMutationStatus(localId, status, serverId = null, error = null) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.QUEUE], "readwrite");
        const store = tx.objectStore(STORES.QUEUE);
        const getReq = store.get(localId);

        getReq.onsuccess = () => {
          const item = getReq.result;
          if (!item) {
            resolve(false);
            return;
          }
          item.status = status;
          item.last_attempt_at = new Date().toISOString();
          item.attempt_count = (item.attempt_count || 0) + 1;
          if (serverId) item.server_id = serverId;
          if (error) item.error = error;

          const putReq = store.put(item);
          putReq.onsuccess = () => resolve(true);
          putReq.onerror = (e) => reject(e.target.error);
        };
        getReq.onerror = (e) => reject(e.target.error);
      });
    }

    async listQueueItems() {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.QUEUE], "readonly");
        const store = tx.objectStore(STORES.QUEUE);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    async removeQueueItem(localId) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.QUEUE], "readwrite");
        const store = tx.objectStore(STORES.QUEUE);
        const req = store.delete(localId);
        req.onsuccess = () => resolve(true);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    // --- Verification Missions Operations ---
    async saveMissions(missions) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.MISSIONS], "readwrite");
        const store = tx.objectStore(STORES.MISSIONS);
        for (const m of missions) {
          store.put(m);
        }
        tx.oncomplete = () => resolve(true);
        tx.onerror = (e) => reject(e.target.error);
      });
    }

    async getMissions() {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.MISSIONS], "readonly");
        const store = tx.objectStore(STORES.MISSIONS);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    async deleteMission(missionId) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.MISSIONS], "readwrite");
        const store = tx.objectStore(STORES.MISSIONS);
        const req = store.delete(missionId);
        req.onsuccess = () => resolve(true);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    // --- Key-Value Metadata Operations ---
    async setMetadata(key, value) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.METADATA], "readwrite");
        const store = tx.objectStore(STORES.METADATA);
        const req = store.put({ key, value, updated_at: new Date().toISOString() });
        req.onsuccess = () => resolve(true);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    async getMetadata(key) {
      await this.init();
      return new Promise((resolve, reject) => {
        const tx = this.db.transaction([STORES.METADATA], "readonly");
        const store = tx.objectStore(STORES.METADATA);
        const req = store.get(key);
        req.onsuccess = () => resolve(req.result ? req.result.value : null);
        req.onerror = (e) => reject(e.target.error);
      });
    }

    // --- Local Saved Places (Beta Device Storage) ---
    async saveLocalPlace(place) {
      const places = await this.getLocalPlaces();
      const updated = [place, ...places.filter(p => p.id !== place.id)];
      return this.setMetadata("local_saved_places", updated);
    }

    async getLocalPlaces() {
      const data = await this.getMetadata("local_saved_places");
      return Array.isArray(data) ? data : [];
    }

    async deleteLocalPlace(id) {
      const places = await this.getLocalPlaces();
      return this.setMetadata("local_saved_places", places.filter(p => p.id !== id));
    }

    // --- Local Saved Routes (Beta Device Storage) ---
    async saveLocalRoute(route) {
      const routes = await this.getLocalRoutes();
      const updated = [route, ...routes.filter(r => r.id !== route.id)];
      return this.setMetadata("local_saved_routes", updated);
    }

    async getLocalRoutes() {
      const data = await this.getMetadata("local_saved_routes");
      return Array.isArray(data) ? data : [];
    }

    async deleteLocalRoute(id) {
      const routes = await this.getLocalRoutes();
      return this.setMetadata("local_saved_routes", routes.filter(r => r.id !== id));
    }

    // --- Storage Usage Estimation ---
    async estimateStorage() {
      if (navigator.storage && navigator.storage.estimate) {
        try {
          const est = await navigator.storage.estimate();
          return {
            usageBytes: est.usage || 0,
            quotaBytes: est.quota || 0,
            usageMB: ((est.usage || 0) / (1024 * 1024)).toFixed(1),
            quotaMB: ((est.quota || 0) / (1024 * 1024)).toFixed(1),
            percentUsed: est.quota ? ((est.usage / est.quota) * 100).toFixed(1) : "0"
          };
        } catch (e) {
          console.warn("[OfflineStore] storage.estimate error:", e);
        }
      }
      return { usageBytes: 0, quotaBytes: 0, usageMB: "0.0", quotaMB: "0.0", percentUsed: "0" };
    }

    async getStats() {
      const routes = await this.listRoutes();
      const missions = await this.getMissions();
      const queue = await this.listQueueItems();
      const pendingQueue = queue.filter(q => q.status === "PENDING" || q.status === "FAILED_RETRYABLE");
      const storage = await this.estimateStorage();

      return {
        routesCount: routes.length,
        missionsCount: missions.length,
        totalQueueCount: queue.length,
        pendingQueueCount: pendingQueue.length,
        storageEstimate: storage
      };
    }

    async clearAllData(preservePendingQueue = true) {
      await this.init();
      return new Promise((resolve, reject) => {
        const storesToClear = [STORES.ROUTES, STORES.EVIDENCE, STORES.MISSIONS, STORES.MAP_REGIONS];
        if (!preservePendingQueue) {
          storesToClear.push(STORES.QUEUE);
        }
        const tx = this.db.transaction(storesToClear, "readwrite");
        for (const s of storesToClear) {
          tx.objectStore(s).clear();
        }
        tx.oncomplete = () => resolve(true);
        tx.onerror = (e) => reject(e.target.error);
      });
    }
  }

  window.AccessRouteOfflineStore = new OfflineStore();
  window.offlineStore = window.AccessRouteOfflineStore;
})(window);
