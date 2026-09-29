/**
 * AccessRoute AI — Field Survey Mode
 * Stage 14 Architecture
 * 
 * Enables accessibility volunteers and researchers to verify infrastructure in the field:
 * - Downloads missions for an area into IndexedDB
 * - Displays closest mission with real-time distance countdown
 * - Rapid one-touch observation selection (Lowered, Flush, Raised, No Kerb, etc.)
 * - Optional photo attachment with client-side compression
 * - Offline queueing with automatic background synchronization
 */

(function (window) {
  "use strict";

  class FieldModeManager {
    constructor() {
      this.activeMissions = [];
      this.currentMissionIndex = 0;
      this.photoAttachment = null; // Base64 data URL
      this.userCoords = null;
    }

    async init() {
      if (window.AccessRouteOfflineStore) {
        this.activeMissions = await window.AccessRouteOfflineStore.getMissions();
      }
    }

    updateUserPosition(lat, lon) {
      this.userCoords = { latitude: lat, longitude: lon };
      this.updateDistanceDisplay();
    }

    async downloadMissionsForArea(lat, lon, radiusM = 1200) {
      try {
        const res = await fetch("/api/v1/offline/mission-package", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            center_latitude: lat,
            center_longitude: lon,
            radius_m: radiusM,
            limit: 20
          })
        });

        if (res.ok) {
          const data = await res.json();
          this.activeMissions = data.missions || [];
          if (window.AccessRouteOfflineStore) {
            await window.AccessRouteOfflineStore.saveMissions(this.activeMissions);
          }
          this.currentMissionIndex = 0;
          this.renderCurrentMission();
          return { success: true, count: this.activeMissions.length };
        }
      } catch (err) {
        console.warn("[FieldMode] Online mission download failed, checking local store:", err);
      }

      // Fallback to local store
      if (window.AccessRouteOfflineStore) {
        this.activeMissions = await window.AccessRouteOfflineStore.getMissions();
        this.renderCurrentMission();
        return { success: true, count: this.activeMissions.length, offline: true };
      }

      return { success: false, count: 0 };
    }

    getDistanceM(lat1, lon1, lat2, lon2) {
      const R = 6371000;
      const dLat = ((lat2 - lat1) * Math.PI) / 180;
      const dLon = ((lon2 - lon1) * Math.PI) / 180;
      const a =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos((lat1 * Math.PI) / 180) *
          Math.cos((lat2 * Math.PI) / 180) *
          Math.sin(dLon / 2) *
          Math.sin(dLon / 2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      return Math.round(R * c);
    }

    updateDistanceDisplay() {
      const distEl = document.getElementById("field-mission-distance");
      if (!distEl || !this.userCoords || !this.getCurrentMission()) return;

      const m = this.getCurrentMission();
      const d = this.getDistanceM(
        this.userCoords.latitude,
        this.userCoords.longitude,
        m.coordinates.latitude,
        m.coordinates.longitude
      );
      distEl.textContent = `📍 ${d}m away`;
    }

    getCurrentMission() {
      if (!this.activeMissions || this.activeMissions.length === 0) return null;
      if (this.currentMissionIndex >= this.activeMissions.length) {
        this.currentMissionIndex = 0;
      }
      return this.activeMissions[this.currentMissionIndex];
    }

    renderCurrentMission() {
      const container = document.getElementById("field-mode-content");
      if (!container) return;

      const mission = this.getCurrentMission();
      if (!mission) {
        container.innerHTML = `
          <div class="field-empty-state">
            <span class="field-empty-icon" aria-hidden="true">📋</span>
            <h3>No Active Field Missions</h3>
            <p>Download verification missions for your area while online to survey pedestrian infrastructure offline.</p>
            <button type="button" class="btn btn-primary btn-sm" onclick="handleDownloadMissions()">Download Nearby Missions</button>
          </div>
        `;
        return;
      }

      const total = this.activeMissions.length;
      const idx = this.currentMissionIndex + 1;

      let actionsHtml = "";
      const suggested = mission.suggested_actions || ["lowered", "flush", "raised", "no_kerb", "unable_to_verify"];
      for (const val of suggested) {
        const label = val.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
        actionsHtml += `
          <button type="button" class="field-choice-btn" data-value="${val}" onclick="selectFieldObservation('${val}')">
            ${label}
          </button>
        `;
      }

      container.innerHTML = `
        <div class="field-mission-card">
          <div class="field-mission-header">
            <span class="field-badge priority-${mission.priority.toLowerCase()}">${mission.priority} Priority</span>
            <span class="field-step-counter">Mission ${idx} of ${total}</span>
          </div>
          <h3 class="field-mission-title">${this.formatTitle(mission.missing_attribute, mission.feature_type)}</h3>
          <div class="field-mission-meta">
            <span id="field-mission-distance" class="field-dist-tag">📍 Calculating distance...</span>
            <span class="field-feature-tag">Feature: ${mission.feature_type}</span>
          </div>
          <div class="field-why-box">
            <strong>Why this matters:</strong>
            <p>${mission.why_it_matters}</p>
          </div>
          
          <div class="field-question-section">
            <label class="field-question-label">What do you observe on site?</label>
            <div class="field-choices-grid" id="field-choices-grid" role="radiogroup" aria-label="Observed infrastructure status">
              ${actionsHtml}
            </div>
          </div>

          <div class="field-evidence-inputs">
            <div class="field-input-group">
              <label for="field-notes-input">Field Notes (Optional):</label>
              <input type="text" id="field-notes-input" class="form-input" placeholder="e.g. Ramp slope is gentle, tactile pavers installed." maxlength="140" />
            </div>

            <div class="field-photo-section">
              <div class="photo-controls">
                <label class="btn btn-outline btn-sm photo-upload-btn" for="field-photo-file">
                  📷 Add Photo Evidence
                </label>
                <input type="file" id="field-photo-file" accept="image/*" style="display:none;" onchange="handleFieldPhotoSelected(event)" />
                <span id="photo-size-indicator" class="photo-size-text" hidden></span>
              </div>
              <div id="field-photo-preview-box" class="photo-preview-box" hidden>
                <img id="field-photo-preview-img" src="" alt="Captured field evidence" />
                <button type="button" class="btn-remove-photo" onclick="removeFieldPhoto()" aria-label="Remove photo">✕</button>
              </div>
            </div>
          </div>

          <div class="field-action-bar">
            <button type="button" class="btn btn-secondary btn-sm" onclick="skipFieldMission()">Skip Mission</button>
            <button type="button" class="btn btn-primary" id="btn-save-field-obs" onclick="saveFieldObservation()" disabled>
              Save Observation
            </button>
          </div>
          <div id="field-save-status" class="field-save-status" role="status" aria-live="polite"></div>
        </div>
      `;

      this.updateDistanceDisplay();
    }

    formatTitle(missing, feature) {
      const m = missing.toLowerCase();
      if (m.includes("kerb")) return "Check Kerb Ramp Transition";
      if (m.includes("surface")) return "Check Footpath Surface Material";
      if (m.includes("width")) return "Check Path Clear Width";
      if (m.includes("entrance")) return "Verify Entrance Step-Free Access";
      return `Verify ${feature.toUpperCase()} ${missing.toUpperCase()}`;
    }

    handlePhotoSelected(file) {
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        // Compress image using canvas
        const img = new Image();
        img.onload = () => {
          const maxDim = 800;
          let w = img.width;
          let h = img.height;
          if (w > maxDim || h > maxDim) {
            if (w > h) {
              h = Math.round((h * maxDim) / w);
              w = maxDim;
            } else {
              w = Math.round((w * maxDim) / h);
              h = maxDim;
            }
          }
          const canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0, w, h);

          // Strip EXIF and compress to JPEG 0.75
          const compressedDataUrl = canvas.toDataURL("image/jpeg", 0.75);
          this.photoAttachment = compressedDataUrl;

          const sizeKb = Math.round(compressedDataUrl.length / 1024);
          const sizeIndicator = document.getElementById("photo-size-indicator");
          const previewBox = document.getElementById("field-photo-preview-box");
          const previewImg = document.getElementById("field-photo-preview-img");

          if (sizeIndicator) {
            sizeIndicator.textContent = `Photo attached (${sizeKb} KB, EXIF stripped)`;
            sizeIndicator.hidden = false;
          }
          if (previewBox && previewImg) {
            previewImg.src = compressedDataUrl;
            previewBox.hidden = false;
          }
        };
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);
    }

    removePhoto() {
      this.photoAttachment = null;
      const sizeIndicator = document.getElementById("photo-size-indicator");
      const previewBox = document.getElementById("field-photo-preview-box");
      const fileInput = document.getElementById("field-photo-file");
      if (sizeIndicator) sizeIndicator.hidden = true;
      if (previewBox) previewBox.hidden = true;
      if (fileInput) fileInput.value = "";
    }

    async saveObservation(selectedValue) {
      const mission = this.getCurrentMission();
      if (!mission || !selectedValue) return;

      const notesInput = document.getElementById("field-notes-input");
      const notes = notesInput ? notesInput.value.trim() : "";
      const statusEl = document.getElementById("field-save-status");

      const mutationItem = {
        local_id: (crypto.randomUUID ? crypto.randomUUID() : "msn_obs_" + Date.now()),
        operation_type: "mission_observation",
        payload: {
          category: mission.feature_type === "entrance" ? "entrance_accessibility" : (mission.missing_attribute === "kerb" ? "kerb" : "surface"),
          value: selectedValue,
          latitude: mission.coordinates.latitude,
          longitude: mission.coordinates.longitude,
          notes: notes,
          photo_url: this.photoAttachment,
          osm_element_id: mission.osm_element_id,
          mission_id: mission.mission_id
        },
        created_at: new Date().toISOString(),
        status: "PENDING"
      };

      if (window.AccessRouteOfflineStore) {
        await window.AccessRouteOfflineStore.queueMutation(mutationItem);
      }

      if (statusEl) {
        statusEl.innerHTML = `<span class="badge-success">✓ Saved locally — Pending synchronization</span>`;
      }

      // Trigger sync if online
      if (window.AccessRouteSync) {
        window.AccessRouteSync.syncNow();
      }

      // Auto-advance to next mission after 1.2s
      setTimeout(() => {
        this.currentMissionIndex++;
        this.photoAttachment = null;
        this.renderCurrentMission();
      }, 1200);
    }

    skipMission() {
      this.currentMissionIndex++;
      this.photoAttachment = null;
      this.renderCurrentMission();
    }
  }

  window.AccessRouteFieldMode = new FieldModeManager();
})(window);
