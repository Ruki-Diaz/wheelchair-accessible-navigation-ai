/**
 * AccessRoute AI — Connectivity Manager
 * Stage 14 Architecture
 * 
 * Tracks real-time connection state:
 * - ONLINE: Full internet and API connectivity
 * - DEGRADED: Browser reports online, but API heartbeat is failing/slow
 * - OFFLINE: Browser offline or network unreachable
 * - SYNCING: Background synchronization in progress
 */

(function (window) {
  "use strict";

  const STATES = {
    ONLINE: "ONLINE",
    DEGRADED: "DEGRADED",
    OFFLINE: "OFFLINE",
    SYNCING: "SYNCING"
  };

  class ConnectivityManager {
    constructor() {
      this.state = navigator.onLine ? STATES.ONLINE : STATES.OFFLINE;
      this.listeners = [];
      this.heartbeatTimer = null;
      this.syncActive = false;
      this.init();
    }

    init() {
      window.addEventListener("online", () => this.handleNetworkEvent(true));
      window.addEventListener("offline", () => this.handleNetworkEvent(false));

      // Periodic API Heartbeat when online
      this.startHeartbeat();

      // Initial check
      if (navigator.onLine) {
        this.checkAPIHealth();
      }
    }

    onStateChange(callback) {
      if (typeof callback === "function") {
        this.listeners.push(callback);
        // Call immediately with current state
        callback(this.state);
      }
    }

    setState(newState) {
      if (this.state !== newState) {
        const oldState = this.state;
        this.state = newState;
        console.log(`[Connectivity] State changed: ${oldState} -> ${newState}`);
        this.notifyListeners();
        this.updateUI();
      }
    }

    notifyListeners() {
      for (const cb of this.listeners) {
        try {
          cb(this.state);
        } catch (e) {
          console.error("[Connectivity] Listener error:", e);
        }
      }
    }

    setSyncing(isSyncing) {
      this.syncActive = isSyncing;
      if (isSyncing) {
        this.setState(STATES.SYNCING);
      } else {
        this.setState(navigator.onLine ? STATES.ONLINE : STATES.OFFLINE);
      }
    }

    handleNetworkEvent(isOnline) {
      if (!isOnline) {
        this.setState(STATES.OFFLINE);
      } else {
        this.checkAPIHealth();
      }
    }

    async checkAPIHealth() {
      if (!navigator.onLine) {
        this.setState(STATES.OFFLINE);
        return false;
      }

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 4000);

      try {
        const res = await fetch("/api/v1/health", {
          method: "GET",
          headers: { "Cache-Control": "no-cache" },
          signal: controller.signal
        });
        clearTimeout(timeoutId);

        if (res.ok) {
          if (!this.syncActive) {
            this.setState(STATES.ONLINE);
          }
          return true;
        } else {
          this.setState(STATES.DEGRADED);
          return false;
        }
      } catch (err) {
        clearTimeout(timeoutId);
        // If navigator.onLine is true but fetch failed, state is DEGRADED or OFFLINE
        if (navigator.onLine) {
          this.setState(STATES.DEGRADED);
        } else {
          this.setState(STATES.OFFLINE);
        }
        return false;
      }
    }

    startHeartbeat() {
      if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
      // Run every 25 seconds
      this.heartbeatTimer = setInterval(() => {
        if (navigator.onLine && !this.syncActive) {
          this.checkAPIHealth();
        }
      }, 25000);
    }

    updateUI() {
      const pill = document.getElementById("connectivity-pill");
      const text = document.getElementById("connectivity-text");
      const dot = document.getElementById("connectivity-dot");
      if (!pill || !text) return;

      pill.className = "connectivity-pill " + this.state.toLowerCase();

      switch (this.state) {
        case STATES.ONLINE:
          text.textContent = "Online";
          pill.setAttribute("aria-label", "System connection: Online");
          break;
        case STATES.DEGRADED:
          text.textContent = "Connection unstable";
          pill.setAttribute("aria-label", "Connection unstable: Some live information may take longer");
          break;
        case STATES.OFFLINE:
          text.textContent = "Offline";
          pill.setAttribute("aria-label", "Offline: Downloaded navigation remains available");
          break;
        case STATES.SYNCING:
          text.textContent = "Syncing…";
          pill.setAttribute("aria-label", "Syncing saved accessibility reports");
          break;
      }
    }

    isOnline() {
      if (!navigator.onLine) {
        if (this.state !== STATES.OFFLINE) {
          this.setState(STATES.OFFLINE);
        }
        return false;
      }
      return this.state === STATES.ONLINE;
    }

    isOffline() {
      return this.state === STATES.OFFLINE;
    }
  }

  window.AccessRouteConnectivity = new ConnectivityManager();
})(window);
