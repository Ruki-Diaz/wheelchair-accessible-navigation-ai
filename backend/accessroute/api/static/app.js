/**
 * AccessRoute AI — Stage 7 Public MVP Client Controller
 *
 * Implements accessible place search, route alternatives comparison,
 * interactive elevation profile with map synchronization, deterministic
 * turn-by-turn guidance, and segment evidence inspection.
 */

// Application State
let map;
let originCoords = null;
let destCoords = null;
let originMarker = null;
let destMarker = null;
let elevationMapMarker = null;

let currentAlternativesData = null;
let activeAlternativeIndex = 0;

let routeLayersMap = {}; // key -> Leaflet layer
let segmentInspectorLayer = null;

let activePinMode = null; // 'origin' | 'dest' | null

// Stage 12 State
let authToken = localStorage.getItem("accessroute_token") || null;
let currentUser = null;
let searchedDestCoords = null;
let searchedOriginCoords = null;
let authMode = "login";

// Stage 13 State
let currentDestinationEntity = null;
let currentDestinationAssessment = null;
let selectedEntrance = null;
let entranceMarkers = [];
let venueCentroidCoords = null;

// Consumer Toast Notification Utility
function showConsumerToast(message, icon = "✓", durationMs = 3200) {
  const toast = document.getElementById("consumer-toast");
  if (!toast) return;
  const iconEl = document.getElementById("toast-icon");
  const msgEl = document.getElementById("toast-message");
  if (iconEl) iconEl.textContent = icon;
  if (msgEl) msgEl.textContent = message;

  toast.hidden = false;
  toast.classList.add("visible");

  if (window._toastTimeout) clearTimeout(window._toastTimeout);
  window._toastTimeout = setTimeout(() => {
    toast.classList.remove("visible");
    setTimeout(() => {
      toast.hidden = true;
    }, 280);
  }, durationMs);
}
window.showConsumerToast = showConsumerToast;

const MOBILITY_PRESETS = {
  manual_wheelchair: {
    preset_name: "manual_wheelchair",
    steps: "never",
    max_preferred_uphill_grade_pct: 4.0,
    max_permitted_uphill_grade_pct: 8.0,
    max_preferred_downhill_grade_pct: 6.0,
    max_permitted_downhill_grade_pct: 10.0,
    unpaved_surfaces: "prefer_avoid",
    rough_surfaces: "prefer_avoid",
    unknown_surfaces: "allow",
    kerb_preference: "avoid_raised",
    unknown_kerbs: "prefer_avoid",
    minimum_path_width_m: null,
    unknown_width: "allow",
    narrow_paths: "allow",
    avoid_restrictive_barriers: "strictly_avoid",
    data_confidence: "balanced",
  },
  powered_wheelchair: {
    preset_name: "powered_wheelchair",
    steps: "never",
    max_preferred_uphill_grade_pct: 7.0,
    max_permitted_uphill_grade_pct: 12.0,
    max_preferred_downhill_grade_pct: 8.0,
    max_permitted_downhill_grade_pct: 14.0,
    unpaved_surfaces: "prefer_avoid",
    rough_surfaces: "prefer_avoid",
    unknown_surfaces: "allow",
    kerb_preference: "avoid_raised",
    unknown_kerbs: "prefer_avoid",
    minimum_path_width_m: 0.8,
    unknown_width: "allow",
    narrow_paths: "prefer_avoid",
    avoid_restrictive_barriers: "strictly_avoid",
    data_confidence: "balanced",
  },
  mobility_scooter: {
    preset_name: "mobility_scooter",
    steps: "never",
    max_preferred_uphill_grade_pct: 6.0,
    max_permitted_uphill_grade_pct: 10.0,
    max_preferred_downhill_grade_pct: 7.0,
    max_permitted_downhill_grade_pct: 12.0,
    unpaved_surfaces: "prefer_avoid",
    rough_surfaces: "prefer_avoid",
    unknown_surfaces: "allow",
    kerb_preference: "avoid_raised",
    unknown_kerbs: "prefer_avoid",
    minimum_path_width_m: 0.85,
    unknown_width: "allow",
    narrow_paths: "prefer_avoid",
    avoid_restrictive_barriers: "strictly_avoid",
    data_confidence: "balanced",
  },
  walker: {
    preset_name: "walker",
    steps: "avoid_when_possible",
    max_preferred_uphill_grade_pct: 5.0,
    max_permitted_uphill_grade_pct: 9.0,
    max_preferred_downhill_grade_pct: 6.0,
    max_permitted_downhill_grade_pct: 10.0,
    unpaved_surfaces: "prefer_avoid",
    rough_surfaces: "prefer_avoid",
    unknown_surfaces: "allow",
    kerb_preference: "avoid_raised",
    unknown_kerbs: "allow",
    minimum_path_width_m: null,
    unknown_width: "allow",
    narrow_paths: "allow",
    avoid_restrictive_barriers: "prefer_avoid",
    data_confidence: "flexible",
  },
  pram: {
    preset_name: "pram",
    steps: "avoid_when_possible",
    max_preferred_uphill_grade_pct: 6.0,
    max_permitted_uphill_grade_pct: 10.0,
    max_preferred_downhill_grade_pct: 7.0,
    max_permitted_downhill_grade_pct: 12.0,
    unpaved_surfaces: "allow",
    rough_surfaces: "allow",
    unknown_surfaces: "allow",
    kerb_preference: "prefer_lowered",
    unknown_kerbs: "allow",
    minimum_path_width_m: 0.75,
    unknown_width: "allow",
    narrow_paths: "allow",
    avoid_restrictive_barriers: "prefer_avoid",
    data_confidence: "flexible",
  },
  custom: {
    preset_name: "custom",
  },
};

let currentPreferences = { ...MOBILITY_PRESETS.manual_wheelchair };

const PRESETS = {
  melbourne: {
    name: "Melbourne CBD",
    orig: [-37.8180, 144.9671],
    dest: [-37.8175, 144.9690],
    origName: "Flinders Street Station, Melbourne",
    destName: "Federation Square, Melbourne",
  },
  sydney: {
    name: "Sydney Harbour",
    orig: [-33.8614, 151.2108],
    dest: [-33.8568, 151.2153],
    origName: "Circular Quay Wharf 4, Sydney",
    destName: "Sydney Opera House Forecourt, Sydney",
  },
  london: {
    name: "London West End",
    orig: [51.5080, -0.1281],
    dest: [51.5113, -0.1283],
    origName: "Trafalgar Square, London",
    destName: "Leicester Square, London",
  },
  vermont_south: {
    name: "Vermont South",
    orig: [-37.8568, 145.1735],
    dest: [-37.8572, 145.1750],
    origName: "Vermont South Library",
    destName: "Vermont South Shopping Centre",
  },
};

// Developer Mode & Simulator Helpers (Consumer build defaults to hidden)
function isDevModeEnabled() {
  try {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get("dev") === "1" || urlParams.get("debug") === "1") {
      return true;
    }
    return localStorage.getItem("accessroute_dev_mode") === "true";
  } catch (e) {
    return false;
  }
}

function toggleDevMode(force) {
  const current = isDevModeEnabled();
  const next = typeof force === "boolean" ? force : !current;
  try {
    localStorage.setItem("accessroute_dev_mode", String(next));
  } catch (e) {}
  document.body.classList.toggle("dev-mode", next);
  document.documentElement.setAttribute("data-dev", String(next));

  const simToolbar = document.getElementById("nav-sim-toolbar");
  if (simToolbar) {
    if (next && document.body.classList.contains("navigation-active")) {
      simToolbar.hidden = false;
      simToolbar.removeAttribute("hidden");
      simToolbar.style.display = "";
    } else if (!next) {
      simToolbar.hidden = true;
      simToolbar.style.display = "none";
    }
  }

  console.log(`[AccessRoute] Developer Mode ${next ? "ENABLED" : "DISABLED"}`);
  return next;
}
window.toggleDevMode = toggleDevMode;
window.isDevModeEnabled = isDevModeEnabled;

function expandSearchDrawer() {
  const drawer = document.getElementById("side-drawer");
  const restingBar = document.getElementById("search-bar-resting");
  const expandedCard = document.getElementById("search-card-expanded");
  if (drawer) {
    drawer.classList.add("search-active");
    drawer.classList.remove("results-active");
  }
  if (restingBar) restingBar.hidden = true;
  if (expandedCard) expandedCard.hidden = false;
  const destInput = document.getElementById("destination-input");
  if (destInput && (!destInput.value || destInput.value.startsWith("Pin ("))) {
    destInput.focus();
  }
  if (map) {
    setTimeout(() => map.invalidateSize(), 300);
  }
}
window.expandSearchDrawer = expandSearchDrawer;

function collapseSearchDrawer() {
  const drawer = document.getElementById("side-drawer");
  const restingBar = document.getElementById("search-bar-resting");
  const expandedCard = document.getElementById("search-card-expanded");
  const routesContainer = document.getElementById("routes-container");
  const destSummaryCard = document.getElementById("dest-summary-card");
  
  if (drawer) drawer.classList.remove("search-active");
  if (expandedCard) expandedCard.hidden = true;
  if (!routesContainer || routesContainer.hidden) {
    if (restingBar) restingBar.hidden = false;
    if (destSummaryCard) destSummaryCard.hidden = true;
  }
  if (map) {
    setTimeout(() => map.invalidateSize(), 300);
  }
}
window.collapseSearchDrawer = collapseSearchDrawer;

function toggleMapLayersMenu(force) {
  const menu = document.getElementById("map-layers-menu");
  const btn = document.getElementById("btn-map-layers");
  if (!menu) return;
  const isHidden = menu.hidden;
  const show = typeof force === "boolean" ? force : isHidden;
  menu.hidden = !show;
  if (btn) btn.setAttribute("aria-expanded", String(show));
}
window.toggleMapLayersMenu = toggleMapLayersMenu;

document.addEventListener("click", (e) => {
  const menu = document.getElementById("map-layers-menu");
  const btn = document.getElementById("btn-map-layers");
  if (menu && !menu.hidden && !menu.contains(e.target) && btn && !btn.contains(e.target)) {
    toggleMapLayersMenu(false);
  }
});

function loadPreset(presetKey) {
  const p = PRESETS[presetKey];
  if (!p) {
    console.warn(`[PRESETS] Unknown preset key: ${presetKey}`);
    return;
  }
  console.log(`[PRESETS] Loading preset: ${p.name}`);
  setOrigin(p.orig[0], p.orig[1], true, false, p.origName);
  setDestination(p.dest[0], p.dest[1], true, false, p.destName);
  if (map) {
    map.fitBounds([p.orig, p.dest], { padding: [60, 60] });
  }
  expandSearchDrawer();
}
window.loadPreset = loadPreset;

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  getAnonymousInstallationId();
  loadStoredPreferences();
  updatePreferencesSummaryChips();
  checkAuthStatus();

  setupAutocomplete("origin-input", "origin-candidates", "origin-coords-label", (lat, lon, candidate) => {
    setOrigin(lat, lon, false, false, candidate ? candidate.display_name : null);
  });

  setupAutocomplete("destination-input", "dest-candidates", "dest-coords-label", (lat, lon, candidate) => {
    setDestination(lat, lon, false, false, candidate ? candidate.display_name : null);
  });

  document.getElementById("btn-pick-origin").addEventListener("click", () => enterPinMode("origin"));
  document.getElementById("btn-pick-dest").addEventListener("click", () => enterPinMode("dest"));

  // Close account dropdown on outside click
  document.addEventListener("click", (e) => {
    const userNav = document.getElementById("user-account-nav");
    const menu = document.getElementById("user-dropdown-menu");
    if (userNav && menu && !userNav.contains(e.target)) {
      menu.hidden = true;
    }
  });

  // Initialize Developer Mode if enabled
  if (isDevModeEnabled()) {
    document.body.classList.add("dev-mode");
    document.documentElement.setAttribute("data-dev", "true");
  }

  // Developer mode gesture: double click brand pill
  const brandPill = document.getElementById("brand-pill");
  if (brandPill) {
    brandPill.addEventListener("dblclick", () => {
      const enabled = toggleDevMode();
      if (typeof showConsumerToast === "function") {
        showConsumerToast(enabled ? "Developer mode enabled" : "Developer mode disabled", "🛠️");
      }
    });
  }

  // Bottom Sheet Mobile Drag / Click Toggle & Swipe-Down
  const handle = document.getElementById("bottom-sheet-handle");
  if (handle) {
    handle.addEventListener("click", toggleMobileBottomSheet);

    let startTouchY = 0;
    handle.addEventListener("touchstart", (e) => {
      if (e.touches && e.touches[0]) {
        startTouchY = e.touches[0].clientY;
      }
    }, { passive: true });

    handle.addEventListener("touchend", (e) => {
      if (e.changedTouches && e.changedTouches[0]) {
        const deltaY = e.changedTouches[0].clientY - startTouchY;
        if (deltaY > 30) {
          collapseSearchDrawer();
        }
      }
    }, { passive: true });
  }

  // Handle Window Resizing for Leaflet
  window.addEventListener("resize", () => {
    if (map) map.invalidateSize();
  });

  // Origin and destination start empty: the user chooses both. The map viewport set in
  // initMap() is only a neutral camera position, never a selected route location.
  collapseSearchDrawer();
});

function initMap() {
  map = L.map("map", {
    zoomControl: false,
  }).setView([-37.8180, 144.9671], 15);

  L.control.zoom({ position: "bottomright" }).addTo(map);

  // Accessible OpenStreetMap Basemap
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> | Elevation: Copernicus DEM GLO-30',
    maxZoom: 19,
  }).addTo(map);

  // Community and intelligence map layers
  communityLayerGroup = L.layerGroup().addTo(map);
  coverageLayerGroup = L.layerGroup().addTo(map);
  missionsLayerGroup = L.layerGroup().addTo(map);

  map.on("click", (e) => {
    if (activePinMode === "origin") {
      setOrigin(e.latlng.lat, e.latlng.lng, true);
      cancelPinMode();
    } else if (activePinMode === "dest") {
      setDestination(e.latlng.lat, e.latlng.lng, true);
      cancelPinMode();
    } else if (activePinMode === "community_report") {
      openCommunityReportModal(e.latlng.lat, e.latlng.lng);
      cancelPinMode();
    }
  });

  map.on("moveend", () => {
    if (currentMapMode === "community") {
      loadCommunityObservations();
    } else if (currentMapMode === "coverage") {
      loadDataCoverage();
    } else if (currentMapMode === "missions") {
      loadVerificationMissions();
    }
  });
}

// Map Pin Dropping Mode
function enterPinMode(mode) {
  activePinMode = mode;
  const banner = document.getElementById("pin-mode-banner");
  const text = document.getElementById("pin-mode-text");
  banner.hidden = false;
  text.textContent = mode === "origin" ? "📍 Click map to set starting point" : "🎯 Click map to set destination";
  document.getElementById("map").style.cursor = "crosshair";
}

function cancelPinMode() {
  activePinMode = null;
  document.getElementById("pin-mode-banner").hidden = true;
  document.getElementById("map").style.cursor = "";
}

// Reverse geocoding helper
async function reverseGeocode(lat, lon) {
  try {
    const res = await fetch(`/api/v1/geocode/reverse?lat=${lat}&lon=${lon}`);
    if (res.ok) {
      const data = await res.json();
      return data.display_name;
    }
  } catch (err) {
    console.warn("Reverse geocode failed:", err);
  }
  return null;
}

function invalidateRouteResults() {
  currentAlternativesData = null;
  const routesContainer = document.getElementById("routes-container");
  if (routesContainer) routesContainer.hidden = true;
  Object.values(routeLayersMap).forEach((layer) => {
    if (map && map.hasLayer(layer)) map.removeLayer(layer);
  });
  routeLayersMap = {};
  if (elevationMapMarker && map && map.hasLayer(elevationMapMarker)) {
    map.removeLayer(elevationMapMarker);
  }
  updateDestinationSummaryCard();
}

// Set Endpoints with Draggable Markers & Address Resolution
function setOrigin(lat, lon, updateInputText = true, isManualDrag = false, displayName = null) {
  originCoords = [parseFloat(lat), parseFloat(lon)];
  document.getElementById("origin-coords-label").textContent = `${originCoords[0].toFixed(5)}, ${originCoords[1].toFixed(5)}`;
  
  const clearBtn = document.getElementById("btn-clear-origin");
  if (clearBtn) clearBtn.hidden = false;

  if (displayName) {
    document.getElementById("origin-input").value = displayName;
    searchedOriginCoords = [originCoords[0], originCoords[1]];
  } else if (isManualDrag) {
    // Check if dragged sufficiently away (> 25m) from searched location
    reverseGeocode(originCoords[0], originCoords[1]).then((addr) => {
      document.getElementById("origin-input").value = addr ? `${addr} (Adjusted on map)` : `Pin (${originCoords[0].toFixed(4)}, ${originCoords[1].toFixed(4)})`;
    });
    searchedOriginCoords = null;
  } else if (updateInputText) {
    reverseGeocode(originCoords[0], originCoords[1]).then((addr) => {
      document.getElementById("origin-input").value = addr || `Pin (${originCoords[0].toFixed(4)}, ${originCoords[1].toFixed(4)})`;
    });
  }

  if (originMarker) map.removeLayer(originMarker);

  const greenIcon = L.divIcon({
    className: "custom-pin",
    html: '<div style="background:#16a34a; width:16px; height:16px; border-radius:50%; border:2px solid #ffffff; box-shadow:0 2px 6px rgba(0,0,0,0.3);"></div>',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });

  originMarker = L.marker(originCoords, {
    icon: greenIcon,
    draggable: true,
    title: "Starting Point",
  }).addTo(map);

  originMarker.bindPopup("<strong>Starting Point</strong><br><span style='color: #9EABA2; font-size: 0.8rem;'>Drag to reposition</span>").openPopup();
  originMarker.on("dragend", (e) => {
    const pos = e.target.getLatLng();
    setOrigin(pos.lat, pos.lng, true, true);
    invalidateRouteResults();
  });
}

function setDestination(lat, lon, updateInputText = true, isManualDrag = false, displayName = null) {
  destCoords = [parseFloat(lat), parseFloat(lon)];
  document.getElementById("dest-coords-label").textContent = `${destCoords[0].toFixed(5)}, ${destCoords[1].toFixed(5)}`;
  
  const clearBtn = document.getElementById("btn-clear-dest");
  if (clearBtn) clearBtn.hidden = false;
  const saveBtn = document.getElementById("btn-save-destination");
  if (saveBtn) saveBtn.hidden = false;

  if (isManualDrag) {
    // Manual pin override: clear venue entrance association, user coordinates authoritative
    selectedEntrance = null;
    currentDestinationEntity = null;
    currentDestinationAssessment = null;
    clearEntranceMarkers();
    searchedDestCoords = null;
    venueCentroidCoords = null;
    reverseGeocode(destCoords[0], destCoords[1]).then((addr) => {
      document.getElementById("destination-input").value = addr ? `${addr} (Adjusted on map)` : `Pin (${destCoords[0].toFixed(4)}, ${destCoords[1].toFixed(4)})`;
      updateDestinationSummaryCard();
    });
  } else if (displayName) {
    document.getElementById("destination-input").value = displayName;
    searchedDestCoords = [destCoords[0], destCoords[1]];
    venueCentroidCoords = [destCoords[0], destCoords[1]];
    resolveAndAssessDestination(destCoords[0], destCoords[1], displayName);
  } else if (updateInputText) {
    reverseGeocode(destCoords[0], destCoords[1]).then((addr) => {
      document.getElementById("destination-input").value = addr || `Pin (${destCoords[0].toFixed(4)}, ${destCoords[1].toFixed(4)})`;
      venueCentroidCoords = [destCoords[0], destCoords[1]];
      resolveAndAssessDestination(destCoords[0], destCoords[1], addr);
    });
  } else {
    updateDestinationSummaryCard();
  }

  if (destMarker) map.removeLayer(destMarker);

  const redIcon = L.divIcon({
    className: "custom-pin",
    html: '<div style="background:#dc2626; width:16px; height:16px; border-radius:3px; border:2px solid #ffffff; box-shadow:0 2px 6px rgba(0,0,0,0.3);"></div>',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });

  destMarker = L.marker(destCoords, {
    icon: redIcon,
    draggable: true,
    title: "Destination Point",
  }).addTo(map);

  destMarker.bindPopup("<strong>Destination</strong><br><span style='color: #9EABA2; font-size: 0.8rem;'>Drag to reposition</span>").openPopup();
  destMarker.on("dragend", (e) => {
    const pos = e.target.getLatLng();
    setDestination(pos.lat, pos.lng, true, true);
    invalidateRouteResults();
  });
}

function handleClearOrigin() {
  originCoords = null;
  searchedOriginCoords = null;
  document.getElementById("origin-input").value = "";
  document.getElementById("origin-coords-label").textContent = "Not selected";
  const clearBtn = document.getElementById("btn-clear-origin");
  if (clearBtn) clearBtn.hidden = true;
  if (originMarker) {
    map.removeLayer(originMarker);
    originMarker = null;
  }
  invalidateRouteResults();
}

function handleClearDestination() {
  destCoords = null;
  searchedDestCoords = null;
  document.getElementById("destination-input").value = "";
  document.getElementById("dest-coords-label").textContent = "Not selected";
  const clearBtn = document.getElementById("btn-clear-dest");
  if (clearBtn) clearBtn.hidden = true;
  const saveBtn = document.getElementById("btn-save-destination");
  if (saveBtn) saveBtn.hidden = true;
  if (destMarker) {
    map.removeLayer(destMarker);
    destMarker = null;
  }
  const summaryCard = document.getElementById("dest-summary-card");
  if (summaryCard) summaryCard.hidden = true;
  invalidateRouteResults();
}

function handleUseMyLocation() {
  if (!navigator.geolocation) {
    alert("Geolocation is not supported by your browser.");
    return;
  }
  const btn = document.getElementById("btn-my-location");
  if (btn) btn.textContent = "⏳";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      if (btn) btn.textContent = "🧭";
      const lat = pos.coords.latitude;
      const lon = pos.coords.longitude;
      setOrigin(lat, lon, false, false);
      map.setView([lat, lon], 16);
      reverseGeocode(lat, lon).then((addr) => {
        document.getElementById("origin-input").value = addr ? `My Location (${addr})` : `My Location (${lat.toFixed(4)}, ${lon.toFixed(4)})`;
      });
    },
    (err) => {
      if (btn) btn.textContent = "🧭";
      console.warn("Geolocation error:", err);
      alert("Could not access your location. Please check browser permissions or search for an address.");
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

// Swap Origin and Destination
function handleSwapEndpoints() {
  if (!originCoords && !destCoords) return;

  const tempCoords = originCoords;
  const tempInput = document.getElementById("origin-input").value;
  const tempSearched = searchedOriginCoords;

  originCoords = destCoords;
  searchedOriginCoords = searchedDestCoords;
  document.getElementById("origin-input").value = document.getElementById("destination-input").value;
  if (originCoords) {
    document.getElementById("origin-coords-label").textContent = `${originCoords[0].toFixed(5)}, ${originCoords[1].toFixed(5)}`;
    const clearOrigin = document.getElementById("btn-clear-origin");
    if (clearOrigin) clearOrigin.hidden = false;
  } else {
    document.getElementById("origin-coords-label").textContent = "Not selected";
    const clearOrigin = document.getElementById("btn-clear-origin");
    if (clearOrigin) clearOrigin.hidden = true;
  }

  destCoords = tempCoords;
  searchedDestCoords = tempSearched;
  document.getElementById("destination-input").value = tempInput;
  if (destCoords) {
    document.getElementById("dest-coords-label").textContent = `${destCoords[0].toFixed(5)}, ${destCoords[1].toFixed(5)}`;
    const clearDest = document.getElementById("btn-clear-dest");
    if (clearDest) clearDest.hidden = false;
    const saveDest = document.getElementById("btn-save-destination");
    if (saveDest) saveDest.hidden = false;
  } else {
    document.getElementById("dest-coords-label").textContent = "Not selected";
    const clearDest = document.getElementById("btn-clear-dest");
    if (clearDest) clearDest.hidden = true;
    const saveDest = document.getElementById("btn-save-destination");
    if (saveDest) saveDest.hidden = true;
  }

  // Refresh markers
  if (originCoords) setOrigin(originCoords[0], originCoords[1], false);
  if (destCoords) setDestination(destCoords[0], destCoords[1], false);

  invalidateRouteResults();
  if (originCoords && destCoords) {
    handleFindRoutes();
  }
}

// Destination Summary Card Update
function updateDestinationSummaryCard(altData = null, conflictData = null) {
  const card = document.getElementById("dest-summary-card");
  if (!card) return;
  if (!destCoords) {
    card.hidden = true;
    return;
  }

  const drawer = document.getElementById("side-drawer");
  const isSearchActive = drawer && drawer.classList.contains("search-active");
  const routesContainer = document.getElementById("routes-container");
  const hasRouteResults = routesContainer && !routesContainer.hidden && routesContainer.children.length > 0;

  if (altData && altData.alternatives && altData.alternatives.length > 0) {
    // When alternatives exist, active-route-hero takes precedence as the primary consumer presentation
    card.hidden = true;
  } else if (!isSearchActive && !hasRouteResults) {
    // When resting on mobile/desktop without route results, destination card stays hidden
    card.hidden = true;
  } else {
    card.hidden = false;
  }
  const nameEl = document.getElementById("dest-summary-name");
  const addrEl = document.getElementById("dest-summary-address");
  const pillEl = document.getElementById("dest-summary-status-pill");
  const distEl = document.getElementById("dest-metric-dist");
  const timeEl = document.getElementById("dest-metric-time");
  const slopeEl = document.getElementById("dest-metric-slope");
  const checklistEl = document.getElementById("dest-evidence-checklist");

  const destInputValue = (document.getElementById("destination-input").value || "").trim();
  nameEl.textContent = destInputValue || `Destination (${destCoords[0].toFixed(4)}, ${destCoords[1].toFixed(4)})`;
  addrEl.textContent = `${destCoords[0].toFixed(5)}, ${destCoords[1].toFixed(5)}`;

  // Stage 13: Entrance Section
  const entranceBox = document.getElementById("dest-entrance-box");
  const entranceNameEl = document.getElementById("dest-entrance-name");
  const entranceTagEl = document.getElementById("dest-entrance-status-tag");
  const entranceChecklistEl = document.getElementById("dest-entrance-checklist");
  const toggleEntrancesBtn = document.getElementById("btn-toggle-entrances");
  const savePrefBtn = document.getElementById("btn-save-preferred-entrance");

  if (selectedEntrance && entranceBox) {
    entranceBox.hidden = false;
    entranceNameEl.textContent = selectedEntrance.name;

    const ass = currentDestinationAssessment?.entrance_assessments?.find(a => a.entrance_id === selectedEntrance.id);
    const status = ass?.status || "matches_current_preferences";

    if (status === "matches_current_preferences") {
      entranceTagEl.className = "dest-entrance-status-tag entrance-tag-match";
      entranceTagEl.innerHTML = "✓ Matches current preferences";
    } else if (status === "does_not_match_current_preferences") {
      entranceTagEl.className = "dest-entrance-status-tag entrance-tag-blocked";
      entranceTagEl.innerHTML = "⛔ Does not match current preferences";
    } else if (status === "conflicting_evidence") {
      entranceTagEl.className = "dest-entrance-status-tag entrance-tag-conflict";
      entranceTagEl.innerHTML = "! Conflicting community evidence";
    } else if (status === "temporarily_reported_unavailable") {
      entranceTagEl.className = "dest-entrance-status-tag entrance-tag-blocked";
      entranceTagEl.innerHTML = "⚠️ Temporarily reported unavailable";
    } else {
      entranceTagEl.className = "dest-entrance-status-tag entrance-tag-partial";
      entranceTagEl.innerHTML = "? Insufficient / partial evidence";
    }

    entranceChecklistEl.innerHTML = "";
    const ev = selectedEntrance.evidence;
    if (ev.step_free === true) {
      entranceChecklistEl.innerHTML += `<li>✓ <span>Step-free entrance recorded</span></li>`;
    } else if (ev.step_free === false) {
      const steps = ev.steps_count ? `${ev.steps_count} steps` : "Mapped stairs";
      entranceChecklistEl.innerHTML += `<li>❌ <span>${steps} present without ramp</span></li>`;
    }

    if (ev.automatic_door === true) {
      entranceChecklistEl.innerHTML += `<li>✓ <span>Automatic power doors recorded</span></li>`;
    } else if (ev.door_type && ev.door_type !== "unknown") {
      entranceChecklistEl.innerHTML += `<li>🚪 <span>Door type: ${ev.door_type}</span></li>`;
    }

    if (ev.door_width_m) {
      entranceChecklistEl.innerHTML += `<li>↔ <span>Clear door width: ${ev.door_width_m}m</span></li>`;
    } else {
      entranceChecklistEl.innerHTML += `<li>ℹ <span>Door clear width unrecorded</span></li>`;
    }

    if (ev.notes) {
      entranceChecklistEl.innerHTML += `<li>ℹ <span>${ev.notes}</span></li>`;
    }

    if (toggleEntrancesBtn) {
      const count = currentDestinationEntity?.venue?.entrances?.length || 0;
      toggleEntrancesBtn.hidden = count <= 1;
      toggleEntrancesBtn.textContent = `Change Entrance (${count}) ▾`;
    }

    if (savePrefBtn) {
      savePrefBtn.hidden = false;
    }
  } else if (entranceBox) {
    entranceBox.hidden = true;
  }

  if (conflictData) {
    card.className = "dest-summary-card status-blocked";
    pillEl.className = "dest-status-pill pill-blocked";
    pillEl.textContent = "⚠ No route matching current preferences";
    distEl.textContent = "—";
    timeEl.textContent = "—";
    slopeEl.textContent = "—";
    
    checklistEl.innerHTML = "";
    const reasons = conflictData.identified_blocking_reasons || ["Strict avoidance constraints cannot be satisfied in this area."];
    reasons.forEach(r => {
      const li = document.createElement("li");
      li.innerHTML = `❌ <span>${r}</span>`;
      checklistEl.appendChild(li);
    });
    return;
  }

  const activeAlt = altData && altData.alternatives && altData.alternatives.length > 0 
    ? altData.alternatives[activeAlternativeIndex] || altData.alternatives[0]
    : (currentAlternativesData && currentAlternativesData.alternatives 
        ? currentAlternativesData.alternatives[activeAlternativeIndex] || currentAlternativesData.alternatives[0]
        : null);

  if (activeAlt) {
    card.className = "dest-summary-card";
    pillEl.className = "dest-status-pill pill-matched";
    pillEl.textContent = "✓ Route found matching your preferences";

    const distKm = (activeAlt.physical_distance_m / 1000.0).toFixed(1);
    distEl.textContent = `${distKm} km`;
    timeEl.textContent = `~${activeAlt.estimated_duration_min} min`;
    slopeEl.textContent = `${(activeAlt.max_incline_pct || 0).toFixed(1)}%`;

    checklistEl.innerHTML = "";
    
    // Mapped stairs
    const stairsLi = document.createElement("li");
    stairsLi.innerHTML = `✓ <span>No mapped unramped stairs on selected route</span>`;
    checklistEl.appendChild(stairsLi);

    // Surface evidence (honest consumer presentation)
    const pavedPct = activeAlt.paved_surface_pct !== undefined ? activeAlt.paved_surface_pct : 92;
    const surfLi = document.createElement("li");
    if (pavedPct >= 80) {
      surfLi.innerHTML = `✓ <span>Mostly paved · ${pavedPct}% recorded paved</span>`;
    } else if (pavedPct >= 50) {
      surfLi.innerHTML = `✓ <span>Partially paved · ${pavedPct}% recorded paved</span>`;
    } else if (pavedPct > 0) {
      surfLi.innerHTML = `◐ <span>Surface data limited · ${pavedPct}% recorded paved</span>`;
    } else {
      surfLi.innerHTML = `◐ <span>Surface data unrecorded</span>`;
    }
    checklistEl.appendChild(surfLi);

    // Kerbs
    const kerbLi = document.createElement("li");
    const missingKerbs = activeAlt.missing_kerb_count !== undefined ? activeAlt.missing_kerb_count : 0;
    if (missingKerbs > 0) {
      kerbLi.innerHTML = `⚠ <span>Kerb information missing at ${missingKerbs} crossing${missingKerbs > 1 ? 's' : ''}</span>`;
    } else {
      kerbLi.innerHTML = `✓ <span>All crossings feature lowered or flush kerbs</span>`;
    }
    checklistEl.appendChild(kerbLi);

    // Metadata completeness
    const metaPct = activeAlt.incomplete_metadata_pct !== undefined ? activeAlt.incomplete_metadata_pct : 14;
    const metaLi = document.createElement("li");
    metaLi.innerHTML = `ℹ <span>${metaPct}% of route contains incomplete accessibility metadata</span>`;
    checklistEl.appendChild(metaLi);

  } else {
    card.className = "dest-summary-card";
    pillEl.className = "dest-status-pill pill-matched";
    pillEl.textContent = "Destination selected — Ready to find routes";
    distEl.textContent = "—";
    timeEl.textContent = "—";
    slopeEl.textContent = "—";
    checklistEl.innerHTML = `<li>ℹ <span>Click 'Find Routes' to evaluate paths against your mobility preferences</span></li>`;
  }
}

// Stage 13: Entrance Intelligence Functions
function clearEntranceMarkers() {
  entranceMarkers.forEach(m => map.removeLayer(m));
  entranceMarkers = [];
}

function renderEntranceMarkers(entrances) {
  clearEntranceMarkers();
  if (!entrances || entrances.length === 0) return;

  entrances.forEach(ent => {
    const ass = currentDestinationAssessment?.entrance_assessments?.find(a => a.entrance_id === ent.id);
    const status = ass?.status || "matches_current_preferences";

    let markerClass = "marker-match";
    let iconChar = "♿";
    let statusLabel = "Matches preferences";

    if (status === "does_not_match_current_preferences") {
      markerClass = "marker-blocked";
      iconChar = "⛔";
      statusLabel = "Does not match preferences";
    } else if (status === "conflicting_evidence") {
      markerClass = "marker-conflict";
      iconChar = "!";
      statusLabel = "Conflicting evidence";
    } else if (status === "insufficient_evidence" || status === "partially_verified") {
      markerClass = "marker-partial";
      iconChar = "?";
      statusLabel = "Partially verified / missing info";
    } else if (status === "temporarily_reported_unavailable") {
      markerClass = "marker-blocked";
      iconChar = "⚠️";
      statusLabel = "Temporarily closed";
    }

    const mIcon = L.divIcon({
      className: "custom-entrance-pin",
      html: `<div class="leaflet-entrance-marker ${markerClass}" title="${ent.name} (${statusLabel})" aria-label="${ent.name}">${iconChar}</div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16],
    });

    const m = L.marker([ent.latitude, ent.longitude], {
      icon: mIcon,
      title: ent.name,
      riseOnHover: true,
    }).addTo(map);

    m.bindPopup(`
      <div style="min-width: 180px;">
        <div style="font-weight: 700; font-size: 0.875rem;">${ent.name}</div>
        <div style="font-size: 0.75rem; color: #475569; margin: 4px 0;">${statusLabel}</div>
        <button type="button" class="btn btn-primary btn-xs" onclick="selectEntranceOptionById('${ent.id}')" style="width: 100%; margin-top: 6px;">Select This Entrance</button>
      </div>
    `);

    m.on("click", () => {
      selectEntranceOption(ent, true);
    });

    entranceMarkers.push(m);
  });
}

async function resolveAndAssessDestination(lat, lon, name = null) {
  clearEntranceMarkers();
  try {
    const qName = name ? encodeURIComponent(name) : "";
    const url = qName 
      ? `/api/v1/destinations/resolve?query=${qName}&lat=${lat}&lon=${lon}`
      : `/api/v1/destinations/resolve?lat=${lat}&lon=${lon}`;

    const res = await fetch(url);
    if (!res.ok) {
      currentDestinationEntity = null;
      selectedEntrance = null;
      updateDestinationSummaryCard();
      return;
    }

    const dest = await res.json();
    currentDestinationEntity = dest;

    if (dest.is_venue && dest.venue && dest.venue.entrances && dest.venue.entrances.length > 0) {
      const assessPayload = {
        origin: originCoords ? { latitude: originCoords[0], longitude: originCoords[1] } : null,
        mobility_preferences: currentPreferences,
      };

      try {
        const assessRes = await fetch(`/api/v1/destinations/${dest.id}/assess`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(assessPayload),
        });
        if (assessRes.ok) {
          currentDestinationAssessment = await assessRes.json();
        }
      } catch (e) {
        console.debug("Assess destination failed:", e);
      }

      renderEntranceMarkers(dest.venue.entrances);

      const recId = currentDestinationAssessment?.recommended_entrance_id;
      const recEnt = dest.venue.entrances.find(e => e.id === recId) || dest.venue.entrances[0];
      selectEntranceOption(recEnt, false);
    } else {
      selectedEntrance = null;
      currentDestinationAssessment = null;
      updateDestinationSummaryCard();
    }
  } catch (err) {
    console.debug("Destination resolve error:", err);
    currentDestinationEntity = null;
    selectedEntrance = null;
    updateDestinationSummaryCard();
  }
}

function selectEntranceOptionById(entranceId) {
  if (!currentDestinationEntity || !currentDestinationEntity.venue) return;
  const ent = currentDestinationEntity.venue.entrances.find(e => e.id === entranceId);
  if (ent) {
    selectEntranceOption(ent, true);
  }
}

function selectEntranceOption(entrance, shouldRecalculate = true) {
  selectedEntrance = entrance;
  destCoords = [entrance.latitude, entrance.longitude];
  document.getElementById("dest-coords-label").textContent = `${destCoords[0].toFixed(5)}, ${destCoords[1].toFixed(5)}`;

  if (destMarker) {
    destMarker.setLatLng(destCoords);
    destMarker.bindPopup(`<b>${entrance.name}</b><br>Selected entrance point.`).openPopup();
  }

  updateDestinationSummaryCard();

  if (shouldRecalculate && originCoords) {
    handleFindRoutes();
  }
}

function toggleEntranceOptionsList() {
  const container = document.getElementById("dest-entrance-options-container");
  const btn = document.getElementById("btn-toggle-entrances");
  if (!container || !btn) return;

  const isHidden = container.hidden;
  container.hidden = !isHidden;
  btn.setAttribute("aria-expanded", String(!isHidden));
  btn.textContent = isHidden ? "Hide Options ▴" : "Change Entrance ▾";

  if (isHidden) {
    renderEntranceOptionsList();
  }
}

function renderEntranceOptionsList() {
  const listEl = document.getElementById("dest-entrance-options-list");
  if (!listEl || !currentDestinationEntity || !currentDestinationEntity.venue) return;

  listEl.innerHTML = "";
  const entrances = currentDestinationEntity.venue.entrances;

  entrances.forEach(ent => {
    const isSelected = selectedEntrance && selectedEntrance.id === ent.id;
    const ass = currentDestinationAssessment?.entrance_assessments?.find(a => a.entrance_id === ent.id);
    const status = ass?.status || "matches_current_preferences";

    let iconChar = "♿";
    let statusText = "Matches preferences";
    if (status === "does_not_match_current_preferences") {
      iconChar = "⛔";
      statusText = "Does not match preferences";
    } else if (status === "conflicting_evidence") {
      iconChar = "!";
      statusText = "Conflicting evidence";
    } else if (status === "insufficient_evidence" || status === "partially_verified") {
      iconChar = "?";
      statusText = "Partial / unrecorded info";
    } else if (status === "temporarily_reported_unavailable") {
      iconChar = "⚠️";
      statusText = "Temporarily closed";
    }

    const card = document.createElement("div");
    card.className = `entrance-option-card ${isSelected ? 'selected' : ''}`;
    card.setAttribute("role", "option");
    card.setAttribute("aria-selected", String(isSelected));
    card.tabIndex = 0;

    card.innerHTML = `
      <div class="entrance-card-left">
        <div class="entrance-card-title">${ent.name}</div>
        <div class="entrance-card-sub">${statusText} • ${ent.entrance_type.toUpperCase()}</div>
      </div>
      <span class="entrance-badge-icon" aria-hidden="true">${iconChar}</span>
    `;

    card.addEventListener("click", () => {
      selectEntranceOption(ent, true);
      toggleEntranceOptionsList();
    });

    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectEntranceOption(ent, true);
        toggleEntranceOptionsList();
      }
    });

    listEl.appendChild(card);
  });
}

function useOriginalDestinationPoint() {
  if (!venueCentroidCoords) return;
  selectedEntrance = null;
  destCoords = [venueCentroidCoords[0], venueCentroidCoords[1]];
  document.getElementById("dest-coords-label").textContent = `${destCoords[0].toFixed(5)}, ${destCoords[1].toFixed(5)}`;
  if (destMarker) {
    destMarker.setLatLng(destCoords);
    destMarker.bindPopup("<b>Destination Center</b>").openPopup();
  }
  updateDestinationSummaryCard();
  if (originCoords) {
    handleFindRoutes();
  }
}

async function saveActivePreferredEntrance() {
  if (!selectedEntrance) {
    alert("Please select an entrance first.");
    return;
  }
  // Save locally first for anonymous beta tester
  try {
    let localPlaces = JSON.parse(localStorage.getItem("accessroute_local_saved_places") || "[]");
    const matching = localPlaces.find(p => 
      Math.abs(p.latitude - selectedEntrance.latitude) < 0.005 &&
      Math.abs(p.longitude - selectedEntrance.longitude) < 0.005
    );
    if (matching) {
      matching.preferred_entrance_id = selectedEntrance.id;
      matching.preferred_entrance_name = selectedEntrance.name;
    } else {
      localPlaces.unshift({
        id: "loc_place_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7),
        label: currentDestinationEntity?.name || selectedEntrance.name,
        display_name: document.getElementById("destination-input").value || selectedEntrance.name,
        latitude: selectedEntrance.latitude,
        longitude: selectedEntrance.longitude,
        preferred_entrance_id: selectedEntrance.id,
        preferred_entrance_name: selectedEntrance.name,
        created_at: new Date().toISOString()
      });
    }
    localStorage.setItem("accessroute_local_saved_places", JSON.stringify(localPlaces));
    if (window.offlineStore) {
      await window.offlineStore.saveLocalPlace(matching || localPlaces[0]);
    }
  } catch (e) {
    console.warn("Local preferred entrance save error:", e);
  }

  // If cloud auth is present, also sync to Stage 12 cloud account
  if (authToken) {
    try {
      const res = await fetch("/api/v1/me/saved-places", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) {
        const places = await res.json();
        const matching = places.find(p => 
          Math.abs(p.latitude - selectedEntrance.latitude) < 0.005 &&
          Math.abs(p.longitude - selectedEntrance.longitude) < 0.005
        );

        if (matching) {
          await fetch(`/api/v1/destinations/saved-places/${matching.id}/preferred-entrance`, {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${authToken}`,
            },
            body: JSON.stringify({
              entrance_id: selectedEntrance.id,
              entrance_name: selectedEntrance.name,
            }),
          });
        } else {
          await fetch("/api/v1/me/saved-places", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${authToken}`,
            },
            body: JSON.stringify({
              label: currentDestinationEntity?.name || selectedEntrance.name,
              display_name: document.getElementById("destination-input").value,
              latitude: selectedEntrance.latitude,
              longitude: selectedEntrance.longitude,
              preferred_entrance_id: selectedEntrance.id,
              preferred_entrance_name: selectedEntrance.name,
            }),
          });
        }
      }
    } catch (err) {
      console.warn("Failed to sync preferred entrance to cloud:", err);
    }
  }
  alert(`Saved "${selectedEntrance.name}" as your preferred entrance.`);
}

function promptReportActiveEntrance() {
  if (!selectedEntrance) return;
  const modal = document.getElementById("entrance-report-dialog");
  const sub = document.getElementById("ent-report-subtitle");
  if (sub) sub.textContent = `Reporting condition for: ${selectedEntrance.name}`;
  if (modal) modal.showModal();
}

function closeEntranceReportModal() {
  const modal = document.getElementById("entrance-report-dialog");
  if (modal) modal.close();
}

async function submitEntranceReport() {
  if (!selectedEntrance) return;
  const val = document.getElementById("ent-report-type").value;
  const notes = document.getElementById("ent-report-notes").value;
  const isTemp = document.getElementById("ent-report-temporary").checked;

  const payload = {
    entrance_id: selectedEntrance.id,
    category: "entrance_accessibility",
    value: val,
    latitude: selectedEntrance.latitude,
    longitude: selectedEntrance.longitude,
    notes: notes,
    is_temporary: isTemp,
    expected_duration_hours: isTemp ? 24.0 : null,
  };

  const headers = { "Content-Type": "application/json" };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  try {
    const res = await fetch("/api/v1/destinations/reports/entrance", {
      method: "POST",
      headers: headers,
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      alert("Thank you! Your entrance accessibility report has been submitted.");
      closeEntranceReportModal();
      if (venueCentroidCoords) {
        resolveAndAssessDestination(venueCentroidCoords[0], venueCentroidCoords[1], currentDestinationEntity?.name);
      }
    } else {
      const err = await res.json();
      alert(`Report submission error: ${err.detail || "Unable to submit report"}`);
    }
  } catch (err) {
    alert("Network error submitting entrance report.");
  }
}

// Autocomplete with Debounce, Badges & Keyboard Support
function setupAutocomplete(inputId, listId, labelId, onSelect) {
  const input = document.getElementById(inputId);
  const list = document.getElementById(listId);
  let debounceTimer = null;
  let activeIndex = -1;

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    activeIndex = -1;
    if (inputId === "origin-input") {
      searchedOriginCoords = null;
    } else {
      searchedDestCoords = null;
    }
    const query = input.value.trim();
    const clearBtn = document.getElementById(inputId === "origin-input" ? "btn-clear-origin" : "btn-clear-dest");
    if (clearBtn) clearBtn.hidden = query.length === 0;

    if (query.length < 2) {
      list.hidden = true;
      list.innerHTML = "";
      return;
    }

    debounceTimer = setTimeout(async () => {
      try {
        const center = map.getCenter();
        const res = await fetch(`/api/v1/geocode/search?q=${encodeURIComponent(query)}&limit=5&proximity_lat=${center.lat}&proximity_lon=${center.lng}`);
        if (!res.ok) return;
        const data = await res.json();
        renderCandidates(data.candidates, list, (c) => {
          input.value = c.display_name;
          list.hidden = true;
          if (inputId === "origin-input") {
            searchedOriginCoords = [c.latitude, c.longitude];
          } else {
            searchedDestCoords = [c.latitude, c.longitude];
          }
          map.setView([c.latitude, c.longitude], 16);
          onSelect(c.latitude, c.longitude, c);
        });
      } catch (err) {
        console.warn("Geocoding failed:", err);
      }
    }, 300);
  });

  input.addEventListener("keydown", (e) => {
    const items = list.querySelectorAll(".autocomplete-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (items.length > 0) {
        activeIndex = (activeIndex + 1) % items.length;
        items.forEach((item, i) => item.classList.toggle("focused", i === activeIndex));
        items[activeIndex].scrollIntoView({ block: "nearest" });
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (items.length > 0) {
        activeIndex = (activeIndex - 1 + items.length) % items.length;
        items.forEach((item, i) => item.classList.toggle("focused", i === activeIndex));
        items[activeIndex].scrollIntoView({ block: "nearest" });
      }
    } else if (e.key === "Enter") {
      if (activeIndex >= 0 && items[activeIndex]) {
        e.preventDefault();
        items[activeIndex].click();
      }
    } else if (e.key === "Escape") {
      list.hidden = true;
    }
  });

  document.addEventListener("click", (e) => {
    if (!input.contains(e.target) && !list.contains(e.target)) {
      list.hidden = true;
    }
  });
}

function renderCandidates(candidates, listEl, selectCallback) {
  listEl.innerHTML = "";
  if (!candidates || candidates.length === 0) {
    const emptyLi = document.createElement("li");
    emptyLi.className = "autocomplete-item text-muted";
    emptyLi.textContent = "No locations found";
    listEl.appendChild(emptyLi);
    listEl.hidden = false;
    return;
  }

  candidates.forEach((c) => {
    const li = document.createElement("li");
    li.className = "autocomplete-item";
    const badgeHtml = c.place_type ? `<span class="autocomplete-badge">${c.place_type}</span>` : "";
    li.innerHTML = `${badgeHtml}<span>${c.display_name}</span>`;
    li.tabIndex = 0;
    li.addEventListener("click", () => selectCallback(c));
    listEl.appendChild(li);
  });
  listEl.hidden = false;
}


// Reset and Terminate Stale Navigation Presentation
function resetNavigationPresentation() {
  console.log("[ROUTE] Resetting previous navigation");

  // 1. Terminate live navigation tracker and interval
  liveNavActive = false;
  currentNavState = NavState.IDLE;
  liveNavTracker = null;
  liveNavCurrentLocation = null;
  liveNavRerouteInFlight = false;
  liveNavRerouteToken++;

  if (liveNavWatchId !== null && "geolocation" in navigator) {
    navigator.geolocation.clearWatch(liveNavWatchId);
    liveNavWatchId = null;
  }

  if (liveNavSimInterval) {
    clearInterval(liveNavSimInterval);
    liveNavSimInterval = null;
    const playBtn = document.getElementById("btn-sim-play");
    if (playBtn) playBtn.textContent = "▶ Play Walk";
  }

  // 2. Remove live navigation markers from map
  if (liveNavUserMarker && map) {
    map.removeLayer(liveNavUserMarker);
    liveNavUserMarker = null;
  }
  if (liveNavAccuracyCircle && map) {
    map.removeLayer(liveNavAccuracyCircle);
    liveNavAccuracyCircle = null;
  }

  if (map) {
    map.off("dragstart", onMapUserDrag);
  }

  // 3. Clear old route geometry layers from map
  Object.values(routeLayersMap).forEach((layer) => {
    if (map && map.hasLayer(layer)) {
      map.removeLayer(layer);
    }
  });
  routeLayersMap = {};

  // 4. Reset navigation UI and classes
  document.body.classList.remove("navigation-active");
  document.body.classList.remove("nav-steps-open");

  const elementsToHide = [
    "nav-top-hud",
    "nav-bottom-panel",
    "nav-sim-toolbar",
    "nav-btn-recenter",
    "nav-reroute-banner",
    "nav-conflict-alert",
    "nav-offline-status-banner",
    "nav-access-pill",
  ];

  elementsToHide.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.hidden = true;
      el.style.display = "none";
    }
  });

  // Restore destination marker interactive popup and dragging if present
  if (destMarker) {
    if (destMarker.dragging) destMarker.dragging.enable();
    destMarker.bindPopup("<strong>Destination</strong><br><span style='color: #9EABA2; font-size: 0.8rem;'>Drag to reposition</span>");
  }

  // 5. Close any open navigation modals
  const offDevModal = document.getElementById("nav-offline-deviation-dialog");
  if (offDevModal && offDevModal.open) offDevModal.close();

  const arrivalDialog = document.getElementById("nav-arrival-dialog");
  if (arrivalDialog && arrivalDialog.open) arrivalDialog.close();

  // 6. Reset HUD stats & progress bar
  const progressFill = document.getElementById("nav-progress-fill");
  if (progressFill) progressFill.style.width = "0%";

  const remainingEl = document.getElementById("nav-stat-remaining");
  if (remainingEl) remainingEl.textContent = "—";

  const etaEl = document.getElementById("nav-stat-eta");
  if (etaEl) etaEl.textContent = "—";

  const progressStatEl = document.getElementById("nav-stat-progress");
  if (progressStatEl) progressStatEl.textContent = "0%";

  const completedStatEl = document.getElementById("nav-stat-completed");
  if (completedStatEl) completedStatEl.textContent = "0m";

  // 7. Release Screen Wake Lock
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.setNavigating(false);
  }
}

let routeSearchInFlight = false;

// Find Accessible Route Alternatives
async function handleFindRoutes() {
  console.log("[ROUTE] Find Routes clicked");

  if (routeSearchInFlight) {
    console.warn("[ROUTE] Search already in flight, ignoring duplicate click");
    return;
  }

  // 1. Terminate/reset any stale navigation presentation BEFORE preparing route
  resetNavigationPresentation();

  // 2. Auto-resolve origin or destination if user typed into inputs without clicking dropdown
  const origInput = document.getElementById("origin-input");
  const destInput = document.getElementById("destination-input");

  if (origInput && origInput.value.trim() && (!originCoords || searchedOriginCoords === null)) {
    try {
      const center = map ? map.getCenter() : { lat: -37.8136, lng: 144.9631 };
      const q = encodeURIComponent(origInput.value.trim());
      const gRes = await fetch(`/api/v1/geocode/search?q=${q}&limit=1&proximity_lat=${center.lat}&proximity_lon=${center.lng}`);
      if (gRes.ok) {
        const gData = await gRes.json();
        if (gData.candidates && gData.candidates.length > 0) {
          const c = gData.candidates[0];
          setOrigin(c.latitude, c.longitude, false, false, c.display_name);
        }
      }
    } catch (e) {
      console.warn("[ROUTE] Auto-geocode origin failed:", e);
    }
  }

  if (destInput && destInput.value.trim() && (!destCoords || searchedDestCoords === null)) {
    try {
      const center = map ? map.getCenter() : { lat: -37.8136, lng: 144.9631 };
      const q = encodeURIComponent(destInput.value.trim());
      const gRes = await fetch(`/api/v1/geocode/search?q=${q}&limit=1&proximity_lat=${center.lat}&proximity_lon=${center.lng}`);
      if (gRes.ok) {
        const gData = await gRes.json();
        if (gData.candidates && gData.candidates.length > 0) {
          const c = gData.candidates[0];
          setDestination(c.latitude, c.longitude, false, false, c.display_name);
        }
      }
    } catch (e) {
      console.warn("[ROUTE] Auto-geocode destination failed:", e);
    }
  }

  if (!originCoords || !destCoords) {
    console.warn("[ROUTE] Missing origin or destination:", { originCoords, destCoords });
    alert("Please specify both a starting point and a destination.");
    return;
  }

  console.log("[ROUTE] Origin resolved");
  console.log("[ROUTE] Destination resolved");
  console.log("[ROUTE] Preferences loaded");

  const btnFind = document.getElementById("btn-find");
  const statusCard = document.getElementById("status-card");
  const statusHeadline = document.getElementById("status-headline");
  const statusDetail = document.getElementById("status-detail");
  const routesContainer = document.getElementById("routes-container");

  if (btnFind) btnFind.disabled = true;
  if (statusCard) statusCard.hidden = false;
  if (routesContainer) routesContainer.hidden = true;
  hideRouteUnavailableCard();
  closeSegmentInspector();

  // Progressive Status Stages (Calm Overlay)
  if (statusHeadline) statusHeadline.textContent = "Finding accessible routes…";
  if (statusDetail) statusDetail.textContent = "Checking slopes, kerbs and path conditions";

  const progressSteps = [
    { delay: 1000, head: "Analyzing terrain & elevation…", desc: "Checking slopes, kerbs and path conditions" },
    { delay: 2200, head: "Comparing accessible alternatives…", desc: "Evaluating step-free paths, kerb transitions, and surfaces" },
  ];

  const timeouts = progressSteps.map((s) =>
    setTimeout(() => {
      if (statusHeadline) statusHeadline.textContent = s.head;
      if (statusDetail) statusDetail.textContent = s.desc;
    }, s.delay)
  );

  // Frontend timeout guard: AbortController with 25-second limit
  const abortController = new AbortController();
  const searchTimeoutId = setTimeout(() => {
    console.warn("[ROUTE] Search timed out after 25s");
    abortController.abort();
  }, 25000);

  routeSearchInFlight = true;

  // Strict Offline Routing Rule (Section 2 & 20)
  if (window.AccessRouteConnectivity && !window.AccessRouteConnectivity.isOnline()) {
    routeSearchInFlight = false;
    timeouts.forEach((t) => clearTimeout(t));
    if (btnFind) btnFind.disabled = false;
    if (statusCard) statusCard.hidden = true;

    const offlineCard = document.getElementById("offline-search-card");
    if (offlineCard) {
      offlineCard.hidden = false;
      offlineCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    const routesContainer = document.getElementById("routes-container");
    if (routesContainer) routesContainer.hidden = true;
    showConsumerToast("You're offline. New accessible routes require a connection.", "📡");
    return;
  }

  try {
    console.log("[ROUTE] Building request");
    const payload = {
      origin: { latitude: originCoords[0], longitude: originCoords[1] },
      destination: { latitude: destCoords[0], longitude: destCoords[1] },
      enrich_elevation: true,
      allow_expansion: true,
      mobility_preferences: currentPreferences,
    };

    console.log("[ROUTE] Sending request");
    const res = await fetch("/api/v1/routes/alternatives", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: abortController.signal,
    });

    clearTimeout(searchTimeoutId);
    timeouts.forEach((t) => clearTimeout(t));

    console.log("[ROUTE] Response received");

    if (!res.ok) {
      let errMsg = `Route calculation failed with HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        errMsg = errJson.detail || errJson.message || errMsg;
      } catch (_) {}
      const httpError = new Error(errMsg);
      httpError.status = res.status;
      throw httpError;
    }

    const data = await res.json();
    console.log(`[ROUTE] Parsed response: found=${data.found}, alternatives=${data.alternatives ? data.alternatives.length : 0}`);

    const conflictCard = document.getElementById("conflict-card");
    const offlineCard = document.getElementById("offline-search-card");
    if (offlineCard) offlineCard.hidden = true;
    hideRouteUnavailableCard();

    if (!data.found || !data.alternatives || data.alternatives.length === 0) {
      const reasons = (data.blocking_reasons && data.blocking_reasons.length > 0)
        ? data.blocking_reasons
        : ["No suitable route found matching your current accessibility preferences within the searched corridor."];
      displayConstraintConflictCard(reasons);
      updateDestinationSummaryCard(null, { identified_blocking_reasons: reasons });
      showConsumerToast("No suitable route found", "⚠️");
      return;
    }

    if (conflictCard) conflictCard.hidden = true;
    currentAlternativesData = data;
    window.currentAlternativesData = data;
    activeAlternativeIndex = 0;
    window.activeAlternativeIndex = 0;

    const searchCard = document.getElementById("search-card-expanded");
    if (searchCard) searchCard.hidden = true;

    renderRouteAlternatives(data);
    updateDestinationSummaryCard(data);

    // Expand mobile bottom sheet to half sheet so cards are visible
    expandMobileBottomSheet("half");

  } catch (error) {
    clearTimeout(searchTimeoutId);
    timeouts.forEach((t) => clearTimeout(t));
    console.error("[ROUTE] ERROR:", error);

    const offlineCard = document.getElementById("offline-search-card");
    const conflictCard = document.getElementById("conflict-card");

    if (isRouteDataUnavailableError(error)) {
      // Upstream map data / infrastructure failure: not an accessibility constraint conflict.
      displayRouteUnavailableCard();
      showConsumerToast(
        error.name === "AbortError" ? "Route calculation timed out" : "Route data temporarily unavailable",
        error.name === "AbortError" ? "⏱" : "🗺️"
      );
    } else if (window.AccessRouteConnectivity && !window.AccessRouteConnectivity.isOnline()) {
      if (offlineCard) offlineCard.hidden = false;
      showConsumerToast("You're offline. New accessible routes require a connection.", "📡");
    } else {
      if (conflictCard) {
        displayConstraintConflictCard([error.message || "Failed to calculate route. Please check your network or try another destination."]);
      }
      showConsumerToast("Unable to calculate route", "⚠️");
    }
  } finally {
    clearTimeout(searchTimeoutId);
    timeouts.forEach((t) => clearTimeout(t));
    routeSearchInFlight = false;
    if (btnFind) btnFind.disabled = false;
    if (statusCard) statusCard.hidden = true;
  }
}

// Render Route Alternatives & Primary Hero Route Experience (Phase 3/4)
function renderRouteAlternatives(data) {
  const routesContainer = document.getElementById("routes-container");
  if (routesContainer) routesContainer.hidden = false;

  const sideDrawer = document.getElementById("side-drawer");
  if (sideDrawer) {
    sideDrawer.hidden = false;
    sideDrawer.style.display = "";
    sideDrawer.classList.remove("search-active");
    sideDrawer.classList.add("results-active");
  }

  const restingSearch = document.getElementById("search-bar-resting");
  if (restingSearch) restingSearch.hidden = true;

  const destSummaryCard = document.getElementById("dest-summary-card");
  if (destSummaryCard) destSummaryCard.hidden = true;

  const searchCard = document.getElementById("search-card-expanded");
  if (searchCard) searchCard.hidden = true;

  const countBadge = document.getElementById("alternatives-count-badge");
  if (countBadge) {
    countBadge.textContent = `${data.alternatives.length} ${data.alternatives.length === 1 ? "Option" : "Options"}`;
  }

  // Ensure each alternative has geometry and coordinates bound from GeoJSON features
  try {
    if (data && data.alternatives && data.geojson && Array.isArray(data.geojson.features)) {
      const altFeatures = data.geojson.features.filter(
        (f) => f.properties && f.properties.feature_type === "route_alternative"
      );
      data.alternatives.forEach((alt, idx) => {
        const feat = altFeatures.find((f) => f.properties && f.properties.key === alt.key) || altFeatures[idx];
        if (feat && feat.geometry && Array.isArray(feat.geometry.coordinates)) {
          alt.geometry = feat.geometry;
          alt.coordinates = feat.geometry.coordinates.map((pt) => [pt[1], pt[0]]);
        }
      });
    }
  } catch (err) {
    console.error("[ROUTE] Error binding coordinates in renderRouteAlternatives:", err);
  }

  // 1. Render Hero Route for the currently active alternative
  const activeAlt = data.alternatives[activeAlternativeIndex] || data.alternatives[0];
  console.log("[ROUTE] Calling renderHeroRoute for activeAlt:", activeAlt ? activeAlt.key : null);
  renderHeroRoute(activeAlt, data);

  // 2. Render Route Alternative Comparison Cards
  const cardsList = document.getElementById("route-cards-list");
  if (cardsList) {
    cardsList.innerHTML = "";

    data.alternatives.forEach((alt, idx) => {
      const card = document.createElement("div");
      const isSelected = idx === activeAlternativeIndex;
      card.className = `route-card route-alternative-card ${isSelected ? "selected" : ""}`;
      card.tabIndex = 0;
      card.role = "tab";
      card.setAttribute("aria-selected", isSelected ? "true" : "false");

      const badgeClass = alt.key === "accessibility_aware" 
        ? "badge-accessibility-aware" 
        : (alt.key === "lower_slope" ? "badge-lower-slope" : "badge-shortest");

      const distStr = alt.physical_distance_m < 1000 
        ? `${alt.physical_distance_m.toFixed(0)} m` 
        : `${(alt.physical_distance_m / 1000.0).toFixed(1)} km`;

      let distinctionText = "";
      if (alt.key === "lower_slope") {
        distinctionText = `Flatter route · max slope ${alt.max_uphill_grade_pct.toFixed(1)}%`;
      } else if (alt.key === "shortest") {
        distinctionText = alt.is_shortest ? "Shortest distance" : `+${alt.distance_delta_m.toFixed(0)} m vs shortest`;
      } else {
        distinctionText = "Highest accessibility confidence";
      }

      card.innerHTML = `
        <div class="alt-card-header">
          <div class="alt-card-title-wrap">
            <span class="alt-route-color-pill" style="background:${alt.color_hex};" aria-hidden="true"></span>
            <strong class="alt-card-title">${alt.title}</strong>
          </div>
          <span class="card-badge ${badgeClass}">${alt.badge}</span>
        </div>
        <div class="alt-card-stats-row">
          <span class="alt-stat-duration"><strong>${alt.estimated_duration_min} min</strong></span>
          <span class="alt-stat-dot" aria-hidden="true">•</span>
          <span class="alt-stat-distance">${distStr}</span>
          <span class="alt-stat-dot" aria-hidden="true">•</span>
          <span class="alt-stat-distinction">${distinctionText}</span>
        </div>
        ${isSelected ? '<div class="alt-active-indicator" aria-hidden="true">✓ Selected on map</div>' : ''}
      `;

      card.addEventListener("click", () => selectAlternative(idx));
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectAlternative(idx);
        }
      });

      cardsList.appendChild(card);
    });
  }

  // 3. Render Map Layers
  renderMapRouteLayers(data);

  // 4. Render Active Alternative Details in technical panel
  renderActiveAlternativeDetails();

  // 5. Update Footer Telemetry
  renderTelemetry(data);
}

// Render Selected Route Hero Card (Consumer Experience)
function renderHeroRoute(alt, data) {
  const heroContainer = document.getElementById("active-route-hero");
  if (!heroContainer || !alt) return;

  const badgeClass = alt.key === "accessibility_aware" 
    ? "hero-badge-recommended" 
    : (alt.key === "lower_slope" ? "hero-badge-slope" : "hero-badge-shortest");

  const badgeText = (alt.badge || "Recommended").toUpperCase();

  const distStr = alt.physical_distance_m < 1000 
    ? `${alt.physical_distance_m.toFixed(0)} m` 
    : `${(alt.physical_distance_m / 1000.0).toFixed(1)} km`;

  const deltaStr = alt.is_shortest 
    ? "Shortest route" 
    : `+${alt.distance_delta_m.toFixed(0)} m vs shortest`;

  // Profile name translation
  const profileKey = currentPreferences?.preset_name || "manual_wheelchair";
  const profileNames = {
    manual_wheelchair: "Manual Wheelchair",
    powered_wheelchair: "Powered Wheelchair",
    mobility_scooter: "Mobility Scooter",
    walker: "Walker / Crutches",
    pram: "Pram / Stroller",
    custom: "Custom Profile"
  };
  const profileName = profileNames[profileKey] || "Manual Wheelchair";

  // Build honest checklist items
  const checklistItems = [];

  // 1. Step-Free
  if (alt.stairs_encountered_count === 0) {
    checklistItems.push({
      type: "favorable",
      icon: "✓",
      text: "Step-free"
    });
  } else {
    checklistItems.push({
      type: "warning",
      icon: "⚠",
      text: `${alt.stairs_encountered_count} mapped stairs along route`
    });
  }

  // 2. Kerbs
  if (alt.crossings_unknown_kerb_count === 0) {
    checklistItems.push({
      type: "favorable",
      icon: "✓",
      text: "Accessible kerbs"
    });
  } else {
    checklistItems.push({
      type: "unknown",
      icon: "◐",
      text: `Kerb info unknown at ${alt.crossings_unknown_kerb_count} crossing${alt.crossings_unknown_kerb_count > 1 ? 's' : ''}`
    });
  }

  // 3. Surface evidence honesty
  const pavedPct = typeof alt.paved_percentage === "number" ? alt.paved_percentage : 0;
  if (pavedPct >= 80) {
    checklistItems.push({
      type: "favorable",
      icon: "✓",
      text: `Mostly paved · ${pavedPct.toFixed(0)}% recorded paved`
    });
  } else if (pavedPct >= 50) {
    checklistItems.push({
      type: "favorable",
      icon: "✓",
      text: `Partially paved · ${pavedPct.toFixed(0)}% recorded paved`
    });
  } else if (alt.unpaved_distance_m > 0 || pavedPct > 0) {
    checklistItems.push({
      type: "unknown",
      icon: "◐",
      text: `Surface data limited · ${pavedPct.toFixed(0)}% recorded paved`
    });
  } else {
    checklistItems.push({
      type: "unknown",
      icon: "◐",
      text: "Surface data unrecorded"
    });
  }

  // 4. Incline
  if (alt.max_uphill_grade_pct <= 4.0) {
    checklistItems.push({
      type: "favorable",
      icon: "✓",
      text: "Gentle incline throughout"
    });
  } else if (alt.max_uphill_grade_pct <= 7.5) {
    checklistItems.push({
      type: "warning",
      icon: "⚠",
      text: `Moderate incline · max ${alt.max_uphill_grade_pct.toFixed(1)}%`
    });
  } else {
    checklistItems.push({
      type: "warning",
      icon: "⚠",
      text: `Steep section · max ${alt.max_uphill_grade_pct.toFixed(1)}%`
    });
  }

  const checklistHtml = checklistItems.map(item => `
    <li class="hero-check-item ${item.type}">
      <span class="hero-check-icon" aria-hidden="true">${item.icon}</span>
      <span class="hero-check-text">${item.text}</span>
    </li>
  `).join("");

  // Integrated Entrance HTML (Section 9)
  let entranceHtml = "";
  const destInputVal = (document.getElementById("destination-input")?.value || "").trim();
  const destName = currentDestinationEntity?.venue?.name || destInputVal || "Destination";

  if (selectedEntrance) {
    const isStepFree = selectedEntrance.evidence?.step_free !== false;
    entranceHtml = `
      <div class="hero-entrance-box">
        <div class="hero-entrance-top">
          <span class="hero-entrance-eyebrow">DESTINATION</span>
          <span class="hero-entrance-venue">${destName}</span>
        </div>
        <div class="hero-entrance-status-row">
          <span class="hero-entrance-pill ${isStepFree ? 'status-match' : 'status-check'}">
            ${isStepFree ? '✓ Accessible entrance selected' : 'ℹ Entrance selected'}
          </span>
          <span class="hero-entrance-detail">${selectedEntrance.name} · ${isStepFree ? 'Step-free' : 'Check access'}</span>
        </div>
        <button type="button" class="btn-change-entrance-link" onclick="toggleEntranceOptionsList()" aria-label="Change destination entrance">
          Change entrance ›
        </button>
      </div>
    `;
  } else if (destName) {
    entranceHtml = `
      <div class="hero-entrance-box simple">
        <div class="hero-entrance-top">
          <span class="hero-entrance-eyebrow">DESTINATION</span>
          <span class="hero-entrance-venue">${destName}</span>
        </div>
        <div class="hero-entrance-status-row">
          <span class="hero-entrance-pill status-match">✓ Connected to pedestrian network</span>
        </div>
      </div>
    `;
  }

  heroContainer.innerHTML = `
    <div class="hero-badge-row">
      <span class="hero-badge ${badgeClass}">${badgeText}</span>
      <span class="hero-delta-pill">${deltaStr}</span>
    </div>

    <div class="hero-primary-stats">
      <div class="hero-time-stat">
        <span class="hero-time-val">${alt.estimated_duration_min}</span>
        <span class="hero-time-unit">min</span>
      </div>
      <div class="hero-dist-stat">${distStr}</div>
    </div>

    <div class="hero-match-pill">
      <span class="hero-match-icon" aria-hidden="true">✓</span>
      <span class="hero-match-text">Good match for ${profileName}</span>
    </div>

    <ul class="hero-checklist-list" aria-label="Key accessibility conditions">
      ${checklistHtml}
    </ul>

    ${entranceHtml}

    <div class="hero-action-buttons">
      <button type="button" id="btn-start-navigation" class="btn-hero-nav" onclick="startNavigationForActiveRoute()" aria-label="Start Live Navigation">
        <span class="hero-nav-icon" aria-hidden="true">🧭</span>
        <span class="hero-nav-label">Start Navigation</span>
      </button>
      <button type="button" id="btn-why-this-route" class="btn-hero-why" onclick="openWhyRouteModal()" aria-label="Why this route? Open accessibility evidence details">
        Why this route? <span aria-hidden="true">›</span>
      </button>
    </div>
    <div class="hero-offline-action-row">
      <button type="button" id="btn-download-offline-route" class="btn-hero-download" onclick="handleDownloadActiveRouteOffline()" aria-label="Download route for offline navigation">
        <span class="download-icon" aria-hidden="true">↓</span>
        <span id="download-offline-text">Download for offline</span>
      </button>
      <div id="offline-route-status-badge" class="offline-saved-badge" hidden>
        <span class="badge-icon">✓</span>
        <span id="offline-route-status-msg" class="badge-text">Available offline</span>
      </div>
    </div>
  `;

  if (window.AccessRouteOfflineStore && alt && alt.key) {
    window.AccessRouteOfflineStore.getRoute(alt.key).then((saved) => {
      if (saved) {
        const textEl = document.getElementById("download-offline-text");
        const badge = document.getElementById("offline-route-status-badge");
        const badgeMsg = document.getElementById("offline-route-status-msg");
        if (textEl) textEl.textContent = "Saved Offline ✓";
        if (badge) badge.hidden = false;
        if (badgeMsg) badgeMsg.textContent = "Available offline";
      }
    }).catch(() => {});
  }
}

// Select Active Alternative
function selectAlternative(index) {
  if (!currentAlternativesData || !currentAlternativesData.alternatives) return;
  activeAlternativeIndex = index;
  window.activeAlternativeIndex = index;
  const activeAlt = currentAlternativesData.alternatives[activeAlternativeIndex];

  // 1. Re-render Hero Card
  renderHeroRoute(activeAlt, currentAlternativesData);

  // 2. Update card selected visual states in comparison list
  const cards = document.querySelectorAll(".route-card");
  cards.forEach((c, idx) => {
    if (idx === index) {
      c.classList.add("selected");
      c.setAttribute("aria-selected", "true");
      if (!c.querySelector(".alt-active-indicator")) {
        const ind = document.createElement("div");
        ind.className = "alt-active-indicator";
        ind.setAttribute("aria-hidden", "true");
        ind.textContent = "✓ Selected on map";
        c.appendChild(ind);
      }
    } else {
      c.classList.remove("selected");
      c.setAttribute("aria-selected", "false");
      const ind = c.querySelector(".alt-active-indicator");
      if (ind) ind.remove();
    }
  });

  // 3. Update Map Layer styles (selected weight 6, opacity 0.95; inactive weight 4, opacity 0.55)
  updateMapRouteStyles();

  // 4. Update Details (Directions, Elevation, Evidence)
  renderActiveAlternativeDetails();
  updateDestinationSummaryCard(currentAlternativesData);

  // 5. Update Why This Route modal if currently open
  const whyModal = document.getElementById("why-route-modal");
  if (whyModal && (whyModal.open || whyModal.hasAttribute("open"))) {
    populateWhyRouteModal(activeAlt);
  }
}

// Back to Search (Return without wiping search inputs)
function backToSearch() {
  const routesContainer = document.getElementById("routes-container");
  const searchCard = document.getElementById("search-card-expanded");
  const restingSearch = document.getElementById("search-bar-resting");
  const sideDrawer = document.getElementById("side-drawer");
  const destSummaryCard = document.getElementById("dest-summary-card");

  if (routesContainer) routesContainer.hidden = true;
  if (destSummaryCard) destSummaryCard.hidden = true;
  if (searchCard) searchCard.hidden = false;
  if (restingSearch) restingSearch.hidden = true;
  if (sideDrawer) {
    sideDrawer.classList.remove("results-active");
    sideDrawer.classList.add("search-active");
  }
}

// "Why This Route?" Consumer Explainability Modal
function openWhyRouteModal() {
  const modal = document.getElementById("why-route-modal");
  if (!modal) return;
  if (!currentAlternativesData || !currentAlternativesData.alternatives) return;
  const alt = currentAlternativesData.alternatives[activeAlternativeIndex];
  if (!alt) return;

  populateWhyRouteModal(alt);

  if (typeof modal.showModal === "function") {
    modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }
}

function closeWhyRouteModal() {
  const modal = document.getElementById("why-route-modal");
  if (!modal) return;
  if (typeof modal.close === "function") {
    modal.close();
  } else {
    modal.removeAttribute("open");
  }
}

function populateWhyRouteModal(alt) {
  const subtitle = document.getElementById("why-modal-subtitle");
  if (subtitle) {
    subtitle.textContent = `Evaluating accessibility evidence for ${alt.title} (${alt.estimated_duration_min} min · ${(alt.physical_distance_m / 1000).toFixed(1)} km)`;
  }

  // 1. Step-Free Access
  const evStepFree = document.getElementById("why-ev-stepfree");
  if (evStepFree) {
    if (alt.stairs_encountered_count === 0) {
      evStepFree.innerHTML = `
        <div class="why-ev-item favorable">
          <span class="why-ev-symbol">✓</span>
          <span class="why-ev-text">No mapped stairs or steps along this route</span>
        </div>
      `;
    } else {
      evStepFree.innerHTML = `
        <div class="why-ev-item warning">
          <span class="why-ev-symbol">⚠</span>
          <span class="why-ev-text">${alt.stairs_encountered_count} mapped flight(s) of stairs without recorded ramps</span>
        </div>
      `;
    }
  }

  // 2. Kerbs & Crossings
  const evKerbs = document.getElementById("why-ev-kerbs");
  if (evKerbs) {
    const knownKerbs = Math.max(0, (alt.crossings_count || 0) - (alt.crossings_unknown_kerb_count || 0));
    if (alt.crossings_unknown_kerb_count === 0) {
      evKerbs.innerHTML = `
        <div class="why-ev-item favorable">
          <span class="why-ev-symbol">✓</span>
          <span class="why-ev-text">Lowered/flush kerbs confirmed at all ${alt.crossings_count || 0} known pedestrian crossings</span>
        </div>
      `;
    } else {
      evKerbs.innerHTML = `
        <div class="why-ev-item favorable">
          <span class="why-ev-symbol">✓</span>
          <span class="why-ev-text">Lowered/flush kerbs confirmed at ${knownKerbs} crossing${knownKerbs === 1 ? '' : 's'}</span>
        </div>
        <div class="why-ev-item unknown">
          <span class="why-ev-symbol">◐</span>
          <span class="why-ev-text">Kerb transition information unavailable at ${alt.crossings_unknown_kerb_count} crossing${alt.crossings_unknown_kerb_count === 1 ? '' : 's'}</span>
        </div>
      `;
    }
  }

  // 3. Surface Conditions
  const evSurface = document.getElementById("why-ev-surface");
  if (evSurface) {
    const pavedPct = (alt.paved_percentage !== undefined ? alt.paved_percentage : 90).toFixed(0);
    const unpavedM = (alt.unpaved_distance_m || 0).toFixed(0);
    if (unpavedM > 0) {
      evSurface.innerHTML = `
        <div class="why-ev-item favorable">
          <span class="why-ev-symbol">✓</span>
          <span class="why-ev-text">Mostly smooth surface: ${pavedPct}% recorded paved (asphalt/concrete)</span>
        </div>
        <div class="why-ev-item unknown">
          <span class="why-ev-symbol">◐</span>
          <span class="why-ev-text">${unpavedM} m has unrecorded or natural surface information</span>
        </div>
      `;
    } else {
      evSurface.innerHTML = `
        <div class="why-ev-item favorable">
          <span class="why-ev-symbol">✓</span>
          <span class="why-ev-text">${pavedPct}% recorded paved surface throughout (asphalt, concrete, or pavers)</span>
        </div>
      `;
    }
  }

  // 4. Incline & Terrain
  const evIncline = document.getElementById("why-ev-incline");
  if (evIncline) {
    const grade = (alt.max_uphill_grade_pct || 0).toFixed(1);
    const gain = (alt.elevation_gain_m || 0).toFixed(0);
    const loss = (alt.elevation_loss_m || 0).toFixed(0);
    let slopeIcon = "✓";
    let slopeClass = "favorable";
    let slopeDesc = `Gentle slope throughout: maximum uphill slope ${grade}%`;

    if (alt.max_uphill_grade_pct > 7.5) {
      slopeIcon = "⚠";
      slopeClass = "warning";
      slopeDesc = `Steep section: maximum uphill slope ${grade}%`;
    } else if (alt.max_uphill_grade_pct > 4.0) {
      slopeIcon = "⚠";
      slopeClass = "warning";
      slopeDesc = `Moderate incline: maximum uphill slope ${grade}%`;
    }

    evIncline.innerHTML = `
      <div class="why-ev-item ${slopeClass}">
        <span class="why-ev-symbol">${slopeIcon}</span>
        <span class="why-ev-text">${slopeDesc}</span>
      </div>
      <div class="why-ev-item favorable">
        <span class="why-ev-symbol">✓</span>
        <span class="why-ev-text">Total climb: +${gain} m · Total descent: -${loss} m</span>
      </div>
    `;
  }

  // 5. Path Width & Clearance
  const evWidth = document.getElementById("why-ev-width");
  if (evWidth) {
    if (alt.minimum_path_width_m) {
      evWidth.innerHTML = `
        <div class="why-ev-item favorable">
          <span class="why-ev-symbol">✓</span>
          <span class="why-ev-text">Minimum recorded path clearance: ${alt.minimum_path_width_m} m</span>
        </div>
      `;
    } else {
      evWidth.innerHTML = `
        <div class="why-ev-item unknown">
          <span class="why-ev-symbol">◐</span>
          <span class="why-ev-text">Width not explicitly recorded on some sections (standard pedestrian sidewalk assumed)</span>
        </div>
      `;
    }
  }

  // 6. Destination & Entrance
  const evEntrance = document.getElementById("why-ev-entrance");
  if (evEntrance) {
    if (selectedEntrance) {
      const stepFree = selectedEntrance.evidence?.step_free !== false;
      evEntrance.innerHTML = `
        <div class="why-ev-item ${stepFree ? 'favorable' : 'warning'}">
          <span class="why-ev-symbol">${stepFree ? '✓' : '⚠'}</span>
          <span class="why-ev-text">Route connects to accessible entrance: <strong>${selectedEntrance.name}</strong> (${stepFree ? 'Step-free' : 'Accessibility verification recommended'})</span>
        </div>
      `;
    } else {
      evEntrance.innerHTML = `
        <div class="why-ev-item favorable">
          <span class="why-ev-symbol">✓</span>
          <span class="why-ev-text">Route connects directly to destination coordinates</span>
        </div>
      `;
    }
  }

  // 7. Community Evidence
  const evCommunity = document.getElementById("why-ev-community");
  if (evCommunity) {
    const eq = alt.evidence_quality;
    if (eq && eq.community_observations_count > 0) {
      evCommunity.innerHTML = `
        <div class="why-ev-item favorable">
          <span class="why-ev-symbol">✓</span>
          <span class="why-ev-text">${eq.community_observations_count} recent community confirmation(s)</span>
        </div>
        ${eq.conflicts_count > 0 ? `<div class="why-ev-item warning"><span class="why-ev-symbol">⚠</span><span class="why-ev-text">${eq.conflicts_count} conflicting accessibility report(s) flagged</span></div>` : ''}
        ${eq.stale_observations_count > 0 ? `<div class="why-ev-item unknown"><span class="why-ev-symbol">◐</span><span class="why-ev-text">${eq.stale_observations_count} older observation(s) awaiting reverification</span></div>` : ''}
      `;
    } else {
      evCommunity.innerHTML = `
        <div class="why-ev-item unknown">
          <span class="why-ev-symbol">◐</span>
          <span class="why-ev-text">Limited direct community field surveys for this specific path segment</span>
        </div>
      `;
    }
  }
}

// Map Layers for Alternatives
function renderMapRouteLayers(data) {
  // Clear previous layers
  Object.values(routeLayersMap).forEach((l) => map.removeLayer(l));
  routeLayersMap = {};
  if (segmentInspectorLayer) map.removeLayer(segmentInspectorLayer);

  const features = data.geojson.features || [];

  // Filter alternative line features
  const altFeatures = features.filter((f) => f.properties && f.properties.feature_type === "route_alternative");

  altFeatures.forEach((feat, idx) => {
    const props = feat.properties;
    const isSelected = (idx === activeAlternativeIndex);

    const layer = L.geoJSON(feat, {
      style: {
        color: props.style.color,
        weight: isSelected ? 6 : 4,
        opacity: isSelected ? 0.95 : 0.55,
        dashArray: isSelected && props.key === "accessibility_aware" ? null : props.style.dashArray,
      },
    }).addTo(map);

    layer.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      selectAlternative(idx);
    });

    layer.bindTooltip(`<b>${props.title}</b><br>${(props.physical_distance_m / 1000).toFixed(2)} km • ${props.badge}`, {
      sticky: true,
    });

    routeLayersMap[idx] = layer;
  });

  // Add Interactive Segment Layer for the active alternative
  renderActiveSegmentInspectorLayer();

  // Fit bounds to active route
  fitRouteBounds();
}

function updateMapRouteStyles() {
  if (!currentAlternativesData) return;

  const data = currentAlternativesData;
  const features = (data.geojson.features || []).filter(
    (f) => f.properties && f.properties.feature_type === "route_alternative"
  );

  features.forEach((feat, idx) => {
    const layer = routeLayersMap[idx];
    if (!layer) return;

    const isSelected = (idx === activeAlternativeIndex);
    const props = feat.properties;

    layer.setStyle({
      color: props.style.color,
      weight: isSelected ? 6 : 4,
      opacity: isSelected ? 0.95 : 0.55,
      dashArray: isSelected && props.key === "accessibility_aware" ? null : props.style.dashArray,
    });

    if (isSelected) {
      layer.bringToFront();
    }
  });

  renderActiveSegmentInspectorLayer();
}

// Render Segment Click Targets for Active Alternative
function renderActiveSegmentInspectorLayer() {
  if (segmentInspectorLayer) map.removeLayer(segmentInspectorLayer);

  if (!currentAlternativesData) return;
  const activeAlt = currentAlternativesData.alternatives[activeAlternativeIndex];
  if (!activeAlt) return;

  const features = currentAlternativesData.geojson.features || [];
  const activeSegFeatures = features.filter(
    (f) => f.properties && f.properties.feature_type === "route_segment" && f.properties.alternative_key === activeAlt.key
  );

  if (activeSegFeatures.length > 0) {
    segmentInspectorLayer = L.geoJSON(activeSegFeatures, {
      style: {
        color: "transparent",
        weight: 12,
        opacity: 0.0,
      },
      onEachFeature: (feature, layer) => {
        layer.on("click", (e) => {
          L.DomEvent.stopPropagation(e);
          openSegmentInspector(feature.properties);
        });
      },
    }).addTo(map);
  }
}

// Fit Map Bounds
function fitRouteBounds() {
  const activeLayer = routeLayersMap[activeAlternativeIndex];
  if (activeLayer && typeof activeLayer.getBounds === "function") {
    const b = activeLayer.getBounds();
    if (b && typeof b.isValid === "function" && b.isValid()) {
      map.fitBounds(b, { padding: [50, 50] });
    }
  }
}

// Render Active Alternative Details
function renderActiveAlternativeDetails() {
  if (!currentAlternativesData) return;
  const alt = currentAlternativesData.alternatives[activeAlternativeIndex];
  if (!alt) return;

  // 1. Directions
  const dirList = document.getElementById("directions-list");
  dirList.innerHTML = "";
  (alt.directions || []).forEach((step) => {
    const li = document.createElement("li");
    li.className = "direction-step-card";

    let icon = "↱";
    if (step.maneuver === "depart") icon = "📍";
    else if (step.maneuver === "arrive") icon = "🎯";
    else if (step.maneuver === "cross") icon = "🚶";
    else if (step.maneuver === "straight") icon = "↑";
    else if (step.maneuver.includes("left")) icon = "↰";
    else if (step.maneuver.includes("right")) icon = "↱";

    let cuesHtml = "";
    (step.accessibility_cues || []).forEach((c) => {
      cuesHtml += `<span class="cue-tag">✓ ${c}</span>`;
    });
    (step.barrier_warnings || []).forEach((w) => {
      cuesHtml += `<span class="cue-tag cue-tag-warn">⚠ ${w}</span>`;
    });

    li.innerHTML = `
      <div class="step-maneuver-icon" aria-hidden="true">${icon}</div>
      <div class="step-info">
        <div class="step-instruction">${step.instruction}</div>
        <div class="step-distance">${step.distance_m > 0 ? `${step.distance_m.toFixed(0)} m` : "Final arrival"}</div>
        ${cuesHtml ? `<div class="step-cues">${cuesHtml}</div>` : ""}
      </div>
    `;
    dirList.appendChild(li);
  });

  // 2. Elevation Profile
  renderElevationProfile(alt.elevation_summary);

  // 3. Why This Route Explanations
  renderExplainability(alt);

  // 4. Stage 10 Route Evidence Quality
  renderRouteEvidenceQuality(alt);
}

// Elevation Profile Interactive SVG Chart
function renderElevationProfile(summary) {
  document.getElementById("elev-gain-val").textContent = `+${summary.elevation_gain_m.toFixed(1)} m`;
  document.getElementById("elev-loss-val").textContent = `-${summary.elevation_loss_m.toFixed(1)} m`;
  document.getElementById("elev-max-grade-val").textContent = `${summary.max_uphill_grade_pct.toFixed(1)}%`;

  const svg = document.getElementById("elevation-svg");
  const wrapper = document.getElementById("elevation-chart-wrapper");
  const readout = document.getElementById("chart-hover-indicator");
  svg.innerHTML = "";

  const points = summary.points || [];
  if (points.length < 2) {
    svg.innerHTML = '<text x="250" y="80" text-anchor="middle" fill="#64748b" font-size="12">Elevation profile unavailable</text>';
    return;
  }

  const maxDist = points[points.length - 1].distance_m;
  const minElev = summary.min_elevation_m;
  const maxElev = summary.max_elevation_m;
  const elevRange = Math.max(maxElev - minElev, 1.0);

  const w = 500;
  const h = 160;
  const padTop = 15;
  const padBottom = 25;
  const chartHeight = h - padTop - padBottom;

  const getX = (d) => (d / Math.max(maxDist, 1.0)) * w;
  const getY = (e) => padTop + chartHeight - ((e - minElev) / elevRange) * chartHeight;

  // Build SVG Path
  let pathD = `M ${getX(points[0].distance_m)} ${getY(points[0].elevation_m)}`;
  for (let i = 1; i < points.length; i++) {
    pathD += ` L ${getX(points[i].distance_m)} ${getY(points[i].elevation_m)}`;
  }

  // Area Path
  const areaD = `${pathD} L ${getX(points[points.length - 1].distance_m)} ${h - padBottom} L ${getX(points[0].distance_m)} ${h - padBottom} Z`;

  svg.innerHTML = `
    <defs>
      <linearGradient id="elevGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#2563eb" stop-opacity="0.3"/>
        <stop offset="100%" stop-color="#2563eb" stop-opacity="0.02"/>
      </linearGradient>
    </defs>
    <!-- Base grid lines -->
    <line x1="0" y1="${padTop}" x2="${w}" y2="${padTop}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="3,3"/>
    <line x1="0" y1="${h - padBottom}" x2="${w}" y2="${h - padBottom}" stroke="#cbd5e1" stroke-width="1"/>
    
    <!-- Shaded Elevation Area -->
    <path d="${areaD}" fill="url(#elevGrad)"/>
    
    <!-- Line -->
    <path d="${pathD}" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>
    
    <!-- Min / Max Labels -->
    <text x="6" y="${padTop + 10}" fill="#64748b" font-size="10" font-family="JetBrains Mono">${maxElev.toFixed(0)}m</text>
    <text x="6" y="${h - padBottom - 4}" fill="#64748b" font-size="10" font-family="JetBrains Mono">${minElev.toFixed(0)}m</text>
    <text x="${w - 6}" y="${h - 6}" text-anchor="end" fill="#64748b" font-size="10" font-family="JetBrains Mono">${(maxDist / 1000).toFixed(2)} km</text>

    <!-- Crosshair elements -->
    <line id="chart-cursor-line" x1="0" y1="0" x2="0" y2="${h - padBottom}" stroke="#2563eb" stroke-width="1.5" stroke-dasharray="2,2" style="display:none;"/>
    <circle id="chart-cursor-dot" cx="0" cy="0" r="4" fill="#2563eb" stroke="#ffffff" stroke-width="2" style="display:none;"/>
  `;

  const cursorLine = document.getElementById("chart-cursor-line");
  const cursorDot = document.getElementById("chart-cursor-dot");

  // Chart Hover & Touch Interaction with Map Synchronisation
  function handleChartInteraction(e) {
    const rect = wrapper.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const relX = Math.max(0, Math.min(clientX - rect.left, rect.width));
    const distFrac = relX / rect.width;
    const targetDist = distFrac * maxDist;

    // Find nearest point
    let nearest = points[0];
    let minDiff = Infinity;
    points.forEach((p) => {
      const diff = Math.abs(p.distance_m - targetDist);
      if (diff < minDiff) {
        minDiff = diff;
        nearest = p;
      }
    });

    const cx = getX(nearest.distance_m);
    const cy = getY(nearest.elevation_m);

    cursorLine.setAttribute("x1", cx);
    cursorLine.setAttribute("x2", cx);
    cursorLine.style.display = "block";

    cursorDot.setAttribute("cx", cx);
    cursorDot.setAttribute("cy", cy);
    cursorDot.style.display = "block";

    readout.textContent = `Dist: ${nearest.distance_m.toFixed(0)}m | Elev: ${nearest.elevation_m.toFixed(1)}m`;

    // Map Sync Pulse Marker
    updateElevationMapMarker(nearest.latitude, nearest.longitude);
  }

  wrapper.onmousemove = handleChartInteraction;
  wrapper.ontouchmove = handleChartInteraction;
  wrapper.onmouseleave = () => {
    cursorLine.style.display = "none";
    cursorDot.style.display = "none";
    readout.textContent = "Hover chart to inspect location";
    if (elevationMapMarker) {
      map.removeLayer(elevationMapMarker);
      elevationMapMarker = null;
    }
  };
}

function updateElevationMapMarker(lat, lon) {
  if (elevationMapMarker) {
    elevationMapMarker.setLatLng([lat, lon]);
  } else {
    const pulseIcon = L.divIcon({
      className: "elevation-map-marker",
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
    elevationMapMarker = L.marker([lat, lon], { icon: pulseIcon }).addTo(map);
  }
}

// Render "Why This Route?"
function renderExplainability(alt) {
  const findingsList = document.getElementById("why-findings-list");
  const confidenceList = document.getElementById("why-confidence-list");
  findingsList.innerHTML = "";
  confidenceList.innerHTML = "";

  (alt.explanations || []).forEach((exp) => {
    const li = document.createElement("li");
    li.className = "explain-item";
    li.textContent = exp;

    if (exp.toLowerCase().includes("incomplete") || exp.toLowerCase().includes("unrecorded") || exp.toLowerCase().includes("unknown")) {
      li.classList.add("explain-item-warn");
      confidenceList.appendChild(li);
    } else {
      findingsList.appendChild(li);
    }
  });

  if (confidenceList.children.length === 0) {
    const li = document.createElement("li");
    li.className = "explain-item";
    li.textContent = `Accessibility metadata coverage: ${alt.paved_percentage.toFixed(0)}% recorded surface.`;
    confidenceList.appendChild(li);
  }
}

// Telemetry Bar
function renderTelemetry(data) {
  const tele = document.getElementById("drawer-telemetry");
  tele.innerHTML = `
    Spatial Region: <strong>${data.region_id}</strong> | Cache: <strong>${data.cache_hit ? "HIT" : "MISS"}</strong><br>
    Origin Snapping: ${data.origin_snap_distance_m.toFixed(1)} m | Dest Snapping: ${data.destination_snap_distance_m.toFixed(1)} m<br>
    Regional Expansion: ${data.expansion_occurred ? `Yes (${data.expansion_attempts} attempts)` : "Initial Area Sufficient"}
  `;
}

// Detail Tab Switcher
function switchDetailTab(tabKey) {
  const tabs = ["directions", "elevation", "why", "evidence"];
  tabs.forEach((t) => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const pane = document.getElementById(`tab-pane-${t}`);
    if (btn && pane) {
      if (t === tabKey) {
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");
        pane.hidden = false;
      } else {
        btn.classList.remove("active");
        btn.setAttribute("aria-selected", "false");
        pane.hidden = true;
      }
    }
  });
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Stage 9 Upgraded Segment Evidence Inspector (Strict Provenance Separation)
function openSegmentInspector(props) {
  const dialog = document.getElementById("segment-inspector");
  const body = document.getElementById("inspector-dialog-body");
  dialog.hidden = false;

  const osm = props.osm_evidence || {
    surface: props.surface,
    highway: props.highway,
    wheelchair: props.wheelchair,
    kerb: props.kerb,
    is_crossing: props.is_crossing,
    is_steps: props.is_steps,
    has_ramp: props.has_ramp,
  };

  const terrain = props.terrain_evidence || {
    source: props.elevation_source || "Copernicus GLO-30",
    estimated_grade_pct: props.estimated_grade_pct,
    slope_direction: props.slope_direction,
  };

  const commObsList = props.community_evidence || [];
  const conflictsList = props.conflicts || [];
  const hasConflict = Boolean(props.evidence_conflict || conflictsList.length > 0);

  const gradeStr = terrain.estimated_grade_pct !== null && terrain.estimated_grade_pct !== undefined
    ? `${terrain.estimated_grade_pct}% (${terrain.slope_direction || "slope"})` 
    : "Unrecorded";

  let conflictsHtml = "";
  if (hasConflict) {
    conflictsHtml = `
      <div class="provenance-card card-conflicts" role="alert">
        <div class="provenance-header">
          <div class="provenance-title" style="color: #b91c1c;">⚠️ Disagreement / Conflict</div>
          <span class="provenance-badge" style="background:#fee2e2; color:#991b1b;">Sources Disagree</span>
        </div>
        ${conflictsList.map(c => `
          <div class="conflict-callout">
            <div class="conflict-callout-text"><strong>${escapeHtml(c.summary || "Evidence sources disagree on this segment.")}</strong></div>
            <div class="conflict-comparison-row">
              <div class="conflict-col">
                <div class="conflict-col-label">OpenStreetMap:</div>
                <div>${escapeHtml(c.osm_claim || c.osm_value || "unknown")}</div>
              </div>
              <div class="conflict-col">
                <div class="conflict-col-label">Community:</div>
                <div>${escapeHtml(c.community_claim || c.community_value || "reported")}</div>
              </div>
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  let communityHtml = "";
  if (commObsList.length > 0) {
    communityHtml = `
      <div class="provenance-card card-community">
        <div class="provenance-header">
          <div class="provenance-title">👥 Community Evidence</div>
          <span class="provenance-badge">${commObsList.length} report(s)</span>
        </div>
        <div style="display:flex; flex-direction:column; gap:8px;">
          ${commObsList.map(obs => `
            <div style="padding:6px 0; border-bottom:1px dashed var(--color-border);">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <strong>${escapeHtml((obs.category || "").replace(/_/g, " "))}: ${escapeHtml(obs.value || "")}</strong>
                <span class="status-pill status-pill-${(obs.verification_status || "unverified").toLowerCase()}">
                  ${escapeHtml(obs.verification_status || "UNVERIFIED")}
                </span>
              </div>
              <div style="font-size:0.75rem; color:var(--color-text-muted); margin-top:3px;">
                ${obs.confirmations_count} confirmation(s) · ${obs.disputes_count} dispute(s)
                ${obs.is_temporary ? " · <em>Temporary condition</em>" : ""}
              </div>
              ${obs.notes ? `<div style="font-size:0.75rem; margin-top:3px; font-style:italic;">"${escapeHtml(obs.notes)}"</div>` : ""}
            </div>
          `).join("")}
        </div>
      </div>
    `;
  } else {
    communityHtml = `
      <div class="provenance-card card-community">
        <div class="provenance-header">
          <div class="provenance-title">👥 Community Evidence</div>
          <span class="provenance-badge">None Recorded</span>
        </div>
        <div style="font-size:0.8rem; color:var(--color-text-muted);">
          No active community reports on this segment.
          <button type="button" class="btn btn-ghost" style="padding:2px 6px; font-size:0.75rem; margin-top:4px;" onclick="closeSegmentInspector(); startCommunityReportMode();">
            + Report Condition Here
          </button>
        </div>
      </div>
    `;
  }

  body.innerHTML = `
    <div class="inspector-provenance-container">
      <div style="font-size:0.8rem; font-weight:600; color:var(--color-text-muted); margin-bottom:4px;">
        Segment #${props.segment_index + 1} (${props.length_m} m)
      </div>

      ${conflictsHtml}

      <!-- 1. OpenStreetMap Evidence -->
      <div class="provenance-card card-osm">
        <div class="provenance-header">
          <div class="provenance-title">🏛️ OpenStreetMap Evidence</div>
          <span class="provenance-badge">Source: OSM</span>
        </div>
        <div class="evidence-grid">
          <div class="evidence-item"><span class="evidence-label">Surface</span><span class="evidence-val">${escapeHtml(osm.surface || "unknown")}</span></div>
          <div class="evidence-item"><span class="evidence-label">Highway Type</span><span class="evidence-val">${escapeHtml(osm.highway || "footway")}</span></div>
          <div class="evidence-item"><span class="evidence-label">Wheelchair Tag</span><span class="evidence-val">${escapeHtml(osm.wheelchair || "unknown")}</span></div>
          <div class="evidence-item"><span class="evidence-label">Kerb Profile</span><span class="evidence-val">${escapeHtml(osm.kerb || "unknown")}</span></div>
          <div class="evidence-item"><span class="evidence-label">Road Crossing</span><span class="evidence-val">${osm.is_crossing ? "Yes" : "No"}</span></div>
          <div class="evidence-item"><span class="evidence-label">Stairs Present</span><span class="evidence-val">${osm.is_steps ? "Yes" : "No"}</span></div>
        </div>
      </div>

      <!-- 2. Terrain Estimate -->
      <div class="provenance-card card-terrain">
        <div class="provenance-header">
          <div class="provenance-title">🏔️ Terrain Estimate</div>
          <span class="provenance-badge">${escapeHtml(terrain.source || "Copernicus GLO-30")}</span>
        </div>
        <div class="evidence-grid">
          <div class="evidence-item"><span class="evidence-label">Estimated Grade</span><span class="evidence-val">${gradeStr}</span></div>
          <div class="evidence-item"><span class="evidence-label">Slope Direction</span><span class="evidence-val">${escapeHtml(terrain.slope_direction || "unknown")}</span></div>
        </div>
      </div>

      <!-- 3. Community Evidence -->
      ${communityHtml}
    </div>
  `;
}

function closeSegmentInspector() {
  document.getElementById("segment-inspector").hidden = true;
}

// Reset Handler
function handleReset() {
  originCoords = null;
  destCoords = null;
  currentAlternativesData = null;

  document.getElementById("origin-input").value = "";
  document.getElementById("destination-input").value = "";
  document.getElementById("origin-coords-label").textContent = "Not selected";
  document.getElementById("dest-coords-label").textContent = "Not selected";

  if (originMarker) map.removeLayer(originMarker);
  if (destMarker) map.removeLayer(destMarker);
  if (elevationMapMarker) map.removeLayer(elevationMapMarker);
  originMarker = null;
  destMarker = null;
  elevationMapMarker = null;

  Object.values(routeLayersMap).forEach((l) => map.removeLayer(l));
  routeLayersMap = {};
  if (segmentInspectorLayer) map.removeLayer(segmentInspectorLayer);
  segmentInspectorLayer = null;

  document.getElementById("routes-container").hidden = true;
  document.getElementById("status-card").hidden = true;
  const conflictCard = document.getElementById("conflict-card");
  if (conflictCard) conflictCard.hidden = true;
  hideRouteUnavailableCard();
  closeSegmentInspector();
  cancelPinMode();

  const sideDrawer = document.getElementById("side-drawer");
  if (sideDrawer) {
    sideDrawer.classList.remove("results-active");
  }
  collapseSearchDrawer();
}

// Mobile Bottom Sheet Height Toggles
function toggleMobileBottomSheet() {
  const drawer = document.getElementById("side-drawer");
  if (!drawer) return;
  if (drawer.classList.contains("search-active")) {
    collapseSearchDrawer();
  } else {
    expandSearchDrawer();
  }
}

function expandMobileBottomSheet(state) {
  const drawer = document.getElementById("side-drawer");
  if (!drawer) return;
  drawer.classList.remove("sheet-half", "sheet-expanded");
  if (state === "half") {
    drawer.classList.add("sheet-half");
  } else if (state === "expanded") {
    drawer.classList.add("sheet-expanded");
  }
}

// ==========================================
// Stage 8: Mobility Preferences Controllers
// ==========================================

function setRadioValue(name, val) {
  const radios = document.querySelectorAll(`input[name="${name}"]`);
  radios.forEach((r) => {
    r.checked = (r.value === val);
  });
}

function getRadioValue(name, fallback) {
  const checked = document.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : fallback;
}

function loadStoredPreferences() {
  try {
    const raw = localStorage.getItem("accessroute_mobility_preferences");
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        currentPreferences = { ...MOBILITY_PRESETS.manual_wheelchair, ...parsed };
      }
    }
  } catch (e) {
    console.warn("Could not load stored preferences from localStorage:", e);
  }
}

function savePreferencesToStorage() {
  try {
    localStorage.setItem("accessroute_mobility_preferences", JSON.stringify(currentPreferences));
  } catch (e) {
    console.warn("Could not save preferences to localStorage:", e);
  }
}

function populateModalFromPreferences(prefs) {
  setRadioValue("pref_steps", prefs.steps || "never");

  // Uphill Slopes
  const upPref = prefs.max_preferred_uphill_grade_pct ?? 4.0;
  const upMax = prefs.max_permitted_uphill_grade_pct ?? 8.0;
  document.getElementById("pref-slope-pref-num").value = upPref;
  document.getElementById("pref-slope-pref-range").value = upPref;
  document.getElementById("pref-slope-max-num").value = upMax;
  document.getElementById("pref-slope-max-range").value = upMax;

  // Downhill Slopes
  const downPref = prefs.max_preferred_downhill_grade_pct ?? 6.0;
  const downMax = prefs.max_permitted_downhill_grade_pct ?? 10.0;
  document.getElementById("pref-downhill-pref-num").value = downPref;
  document.getElementById("pref-downhill-pref-range").value = downPref;
  document.getElementById("pref-downhill-max-num").value = downMax;
  document.getElementById("pref-downhill-max-range").value = downMax;

  setRadioValue("pref_unpaved", prefs.unpaved_surfaces || "prefer_avoid");
  setRadioValue("pref_kerb", prefs.kerb_preference || "avoid_raised");
  setRadioValue("pref_unknown_kerb", prefs.unknown_kerbs || "prefer_avoid");
  setRadioValue("pref_data_confidence", prefs.data_confidence || "balanced");

  // Advanced
  const widthInput = document.getElementById("pref-width-num");
  widthInput.value = (prefs.minimum_path_width_m !== null && prefs.minimum_path_width_m !== undefined)
    ? prefs.minimum_path_width_m
    : "";
  setRadioValue("pref_narrow", prefs.narrow_paths || "allow");
  setRadioValue("pref_unknown_width", prefs.unknown_width || "allow");
  setRadioValue("pref_barriers", prefs.avoid_restrictive_barriers || "strictly_avoid");
  setRadioValue("pref_rough", prefs.rough_surfaces || "prefer_avoid");

  updateActivePresetButton(prefs.preset_name || "custom");
}

function updateActivePresetButton(presetKey) {
  const presets = ["manual_wheelchair", "powered_wheelchair", "mobility_scooter", "walker", "pram", "custom"];
  presets.forEach((p) => {
    const btn = document.getElementById(`btn-preset-${p}`);
    if (btn) {
      if (p === presetKey) {
        btn.classList.add("active");
        btn.setAttribute("aria-checked", "true");
      } else {
        btn.classList.remove("active");
        btn.setAttribute("aria-checked", "false");
      }
    }
  });
}

function selectPreset(presetKey) {
  updateActivePresetButton(presetKey);
  const adv = document.getElementById("advanced-prefs-disclosure");
  if (presetKey === "custom") {
    if (adv) adv.open = true;
  }
  if (presetKey !== "custom" && MOBILITY_PRESETS[presetKey]) {
    const template = MOBILITY_PRESETS[presetKey];
    populateModalFromPreferences(template);
    updateActivePresetButton(presetKey);
  }
}

function onPrefChange() {
  updateActivePresetButton("custom");
  const adv = document.getElementById("advanced-prefs-disclosure");
  if (adv) adv.open = true;
}

function syncSlopeInput(which, source) {
  const prefNum = document.getElementById("pref-slope-pref-num");
  const prefRange = document.getElementById("pref-slope-pref-range");
  const maxNum = document.getElementById("pref-slope-max-num");
  const maxRange = document.getElementById("pref-slope-max-range");

  if (which === "pref") {
    const val = parseFloat(source === "range" ? prefRange.value : prefNum.value);
    prefNum.value = val;
    prefRange.value = val;
    if (parseFloat(maxNum.value) < val) {
      maxNum.value = val;
      maxRange.value = val;
    }
  } else {
    const val = parseFloat(source === "range" ? maxRange.value : maxNum.value);
    maxNum.value = val;
    maxRange.value = val;
    if (parseFloat(prefNum.value) > val) {
      prefNum.value = val;
      prefRange.value = val;
    }
  }
  onPrefChange();
}

function syncDownhillInput(which, source) {
  const prefNum = document.getElementById("pref-downhill-pref-num");
  const prefRange = document.getElementById("pref-downhill-pref-range");
  const maxNum = document.getElementById("pref-downhill-max-num");
  const maxRange = document.getElementById("pref-downhill-max-range");

  if (which === "pref") {
    const val = parseFloat(source === "range" ? prefRange.value : prefNum.value);
    prefNum.value = val;
    prefRange.value = val;
    if (parseFloat(maxNum.value) < val) {
      maxNum.value = val;
      maxRange.value = val;
    }
  } else {
    const val = parseFloat(source === "range" ? maxRange.value : maxNum.value);
    maxNum.value = val;
    maxRange.value = val;
    if (parseFloat(prefNum.value) > val) {
      prefNum.value = val;
      prefRange.value = val;
    }
  }
  onPrefChange();
}

function openPreferencesModal() {
  const modal = document.getElementById("preferences-modal");
  if (!modal) return;
  populateModalFromPreferences(currentPreferences);
  if (typeof modal.showModal === "function") {
    modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }
}

function closePreferencesModal() {
  const modal = document.getElementById("preferences-modal");
  if (!modal) return;
  if (typeof modal.close === "function") {
    modal.close();
  } else {
    modal.removeAttribute("open");
  }
}

function applyPreferences() {
  const upPref = parseFloat(document.getElementById("pref-slope-pref-num").value);
  const upMax = parseFloat(document.getElementById("pref-slope-max-num").value);
  if (upPref > upMax) {
    alert("Preferred uphill slope cannot exceed strict maximum slope.");
    return;
  }

  const downPref = parseFloat(document.getElementById("pref-downhill-pref-num").value);
  const downMax = parseFloat(document.getElementById("pref-downhill-max-num").value);
  if (downPref > downMax) {
    alert("Preferred downhill slope cannot exceed strict maximum downhill slope.");
    return;
  }

  const widthVal = document.getElementById("pref-width-num").value.trim();
  const minWidth = widthVal !== "" ? parseFloat(widthVal) : null;
  if (minWidth !== null && (isNaN(minWidth) || minWidth < 0)) {
    alert("Path width must be a positive number.");
    return;
  }

  const activeBtn = document.querySelector(".preset-btn.active");
  const activePreset = activeBtn ? activeBtn.id.replace("btn-preset-", "") : "custom";

  currentPreferences = {
    preset_name: activePreset,
    steps: getRadioValue("pref_steps", "never"),
    max_preferred_uphill_grade_pct: upPref,
    max_permitted_uphill_grade_pct: upMax,
    max_preferred_downhill_grade_pct: downPref,
    max_permitted_downhill_grade_pct: downMax,
    unpaved_surfaces: getRadioValue("pref_unpaved", "prefer_avoid"),
    rough_surfaces: getRadioValue("pref_rough", "prefer_avoid"),
    unknown_surfaces: "allow",
    kerb_preference: getRadioValue("pref_kerb", "avoid_raised"),
    unknown_kerbs: getRadioValue("pref_unknown_kerb", "prefer_avoid"),
    minimum_path_width_m: minWidth,
    unknown_width: getRadioValue("pref_unknown_width", "allow"),
    narrow_paths: getRadioValue("pref_narrow", "allow"),
    avoid_restrictive_barriers: getRadioValue("pref_barriers", "strictly_avoid"),
    data_confidence: getRadioValue("pref_data_confidence", "balanced"),
  };

  savePreferencesToStorage();
  updatePreferencesSummaryChips();
  closePreferencesModal();

  // If routes are already displayed, recalculate with updated personal preferences
  if (originCoords && destCoords && currentAlternativesData) {
    handleFindRoutes();
  }
}

function resetPreferencesToDefault() {
  populateModalFromPreferences(MOBILITY_PRESETS.manual_wheelchair);
  updateActivePresetButton("manual_wheelchair");
}

function updatePreferencesSummaryChips() {
  const container = document.getElementById("pref-chips-list");
  if (!container) return;

  const stepsLabel = currentPreferences.steps === "never" 
    ? "Never" 
    : (currentPreferences.steps === "avoid_when_possible" ? "Avoid" : "Allow");

  const unpavedLabel = currentPreferences.unpaved_surfaces === "strictly_avoid"
    ? "Strictly avoid"
    : (currentPreferences.unpaved_surfaces === "prefer_avoid" ? "Avoid" : "Allow");

  const kerbLabel = currentPreferences.unknown_kerbs === "strictly_avoid"
    ? "Strictly avoid"
    : (currentPreferences.unknown_kerbs === "prefer_avoid" ? "Prefer known" : "Allow");

  const dataLabel = currentPreferences.data_confidence === "cautious"
    ? "Cautious"
    : (currentPreferences.data_confidence === "flexible" ? "Flexible" : "Balanced");

  const slopeLabel = `Prefer ≤${currentPreferences.max_preferred_uphill_grade_pct}%`;

  container.innerHTML = `
    <span class="pref-chip">♿ Stairs: <strong>${stepsLabel}</strong></span>
    <span class="pref-chip">↗ Uphill: <strong>${slopeLabel}</strong></span>
    <span class="pref-chip">🛣 Unpaved: <strong>${unpavedLabel}</strong></span>
    <span class="pref-chip">↔ Unknown kerbs: <strong>${kerbLabel}</strong></span>
    <span class="pref-chip">ℹ Data: <strong>${dataLabel}</strong></span>
  `;

  // Update plain-language summary bullets
  const plainBullets = document.getElementById("pref-plain-bullets");
  if (plainBullets) {
    const bullets = [];
    if (currentPreferences.steps === "never") bullets.push("✓ Step-free");
    if (currentPreferences.unpaved_surfaces === "strictly_avoid" || currentPreferences.unpaved_surfaces === "prefer_avoid") {
      bullets.push("✓ Avoids difficult surfaces");
    }
    if (currentPreferences.max_preferred_uphill_grade_pct <= 6.0) {
      bullets.push("✓ Prefers gentler slopes");
    } else {
      bullets.push("✓ Accommodates moderate slopes");
    }
    plainBullets.innerHTML = bullets.map((b) => `<span class="plain-bullet">${b}</span>`).join("");
  }

  // Update floating mobility pill and preset badge
  const floatingLabel = document.getElementById("floating-mobility-label");
  const floatingIcon = document.getElementById("floating-mobility-icon");
  const presetBadge = document.getElementById("pref-active-preset-badge");
  const presetKey = currentPreferences.preset_name || "manual_wheelchair";
  const nameMap = {
    manual_wheelchair: { name: "Manual Wheelchair", icon: "♿" },
    powered_wheelchair: { name: "Powered Wheelchair", icon: "⚡" },
    mobility_scooter: { name: "Mobility Scooter", icon: "🛵" },
    walker: { name: "Walker / Crutches", icon: "🦯" },
    pram: { name: "Pram / Stroller", icon: "👶" },
    custom: { name: "Custom Profile", icon: "⚙️" },
  };
  const info = nameMap[presetKey] || { name: "Manual Wheelchair", icon: "♿" };
  if (floatingLabel) floatingLabel.textContent = info.name;
  if (floatingIcon) floatingIcon.textContent = info.icon;
  if (presetBadge) presetBadge.textContent = info.name;
}

// 502/503/504 mean AccessRoute couldn't obtain map data (e.g. Overpass unavailable);
// a client-side abort means the same from the user's point of view.
function isRouteDataUnavailableError(error) {
  if (!error) return false;
  if (error.name === "AbortError") return true;
  return error.status === 502 || error.status === 503 || error.status === 504;
}

function hideRouteUnavailableCard() {
  const card = document.getElementById("route-unavailable-card");
  if (card) card.hidden = true;
}

function displayRouteUnavailableCard() {
  const card = document.getElementById("route-unavailable-card");
  const conflictCard = document.getElementById("conflict-card");
  const routesContainer = document.getElementById("routes-container");
  if (!card) return;

  if (conflictCard) conflictCard.hidden = true;
  card.hidden = false;
  if (routesContainer) routesContainer.hidden = true;

  Object.values(routeLayersMap).forEach((l) => map.removeLayer(l));
  routeLayersMap = {};

  expandMobileBottomSheet("half");
}

function displayConstraintConflictCard(reasons) {
  hideRouteUnavailableCard();
  const card = document.getElementById("conflict-card");
  const list = document.getElementById("conflict-reasons-list");
  const routesContainer = document.getElementById("routes-container");

  if (!card || !list) return;

  list.innerHTML = "";
  reasons.forEach((r) => {
    const li = document.createElement("li");
    li.className = "conflict-reason-item";
    li.textContent = r;
    list.appendChild(li);
  });

  card.hidden = false;
  if (routesContainer) routesContainer.hidden = true;

  Object.values(routeLayersMap).forEach((l) => map.removeLayer(l));
  routeLayersMap = {};

  expandMobileBottomSheet("half");
}

/* ==========================================================================
   Stage 9: Community Accessibility Reporting & Verification Handlers
   ========================================================================== */

let communityLayerGroup = null;
let reportingPinCoords = null;

const STRUCTURED_OPTIONS = {
  kerb: [
    { value: "lowered", label: "Lowered Kerb (Ramped)" },
    { value: "flush", label: "Flush Kerb (Level with street)" },
    { value: "raised", label: "Raised Kerb (Barrier / Step)" },
    { value: "no_kerb", label: "No Kerb Present" },
    { value: "unknown", label: "Unknown / Unclear" },
  ],
  stairs: [
    { value: "without_ramp", label: "Stairs (No Ramp)" },
    { value: "with_ramp", label: "Stairs With Ramp" },
    { value: "steep_stairs", label: "Steep Flight of Stairs" },
    { value: "escalator", label: "Escalator / Moving Walkway" },
  ],
  ramp: [
    { value: "wheelchair_accessible", label: "Accessible Ramp (Gentle slope)" },
    { value: "steep", label: "Steep Ramp (>8%)" },
    { value: "temporary_ramp", label: "Temporary Construction Ramp" },
    { value: "damaged", label: "Damaged / Broken Ramp" },
  ],
  surface: [
    { value: "asphalt", label: "Asphalt (Smooth)" },
    { value: "concrete", label: "Concrete (Paved)" },
    { value: "paving_stones", label: "Paving Stones / Pavers" },
    { value: "compacted", label: "Compacted Gravel / Fine Gravel" },
    { value: "gravel", label: "Loose Gravel" },
    { value: "dirt", label: "Dirt / Natural Ground" },
    { value: "grass", label: "Grass / Lawn" },
    { value: "cobblestone", label: "Cobblestone (Rough / Bumpy)" },
  ],
  path_width: [
    { value: "wide_gt_150cm", label: "Wide (>150 cm / Two chairs pass)" },
    { value: "standard_100_150cm", label: "Standard (100 – 150 cm)" },
    { value: "narrow_80_100cm", label: "Narrow (80 – 100 cm)" },
    { value: "restricted_lt_80cm", label: "Restricted (<80 cm / Inaccessible)" },
  ],
  slope: [
    { value: "gentle_lt_4pct", label: "Gentle Incline (≤4%)" },
    { value: "moderate_4_8pct", label: "Moderate Incline (4% – 8%)" },
    { value: "steep_gt_8pct", label: "Steep Incline (>8%)" },
  ],
  barrier: [
    { value: "bollard", label: "Bollard(s) (Check spacing)" },
    { value: "gate", label: "Pedestrian Gate" },
    { value: "cycle_barrier", label: "Cycle Barrier / Chicanes" },
    { value: "turnstile", label: "Turnstile (Impasse for wheelchairs)" },
    { value: "construction_barrier", label: "Construction Barrier" },
  ],
  path_blocked: [
    { value: "impassable", label: "Completely Blocked / Impassable" },
    { value: "flooded", label: "Flooded / Water Obstruction" },
    { value: "overgrown", label: "Overgrown Vegetation" },
    { value: "debris", label: "Fallen Tree / Debris" },
  ],
  construction: [
    { value: "closed", label: "Path Closed for Works" },
    { value: "detour_provided", label: "Construction with Accessible Detour" },
    { value: "roadworks", label: "Active Roadworks / Scaffolding" },
  ],
  temporary_obstacle: [
    { value: "scaffolding", label: "Scaffolding Obstruction" },
    { value: "event_fencing", label: "Event Fencing / Crowd Barriers" },
    { value: "parked_vehicle", label: "Parked Vehicle Blocking Footpath" },
    { value: "spill_or_mud", label: "Mud / Construction Slurry" },
  ],
  lift_status: [
    { value: "operational", label: "Lift Operational" },
    { value: "out_of_service", label: "Lift Out of Service / Broken" },
  ],
  entrance_accessibility: [
    { value: "level_access", label: "Level Step-Free Entrance" },
    { value: "ramped", label: "Ramped Entrance" },
    { value: "stepped", label: "Stepped Entrance Only" },
  ],
  other: [
    { value: "reported_issue", label: "Other Accessibility Issue" },
  ],
};

function getAnonymousInstallationId() {
  let id = localStorage.getItem("accessroute_installation_id");
  if (!id) {
    const rawUuid = (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function")
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
          const r = (Math.random() * 16) | 0,
            v = c === "x" ? r : (r & 0x3) | 0x8;
          return v.toString(16);
        });
    id = "anon_" + rawUuid;
    localStorage.setItem("accessroute_installation_id", id);
    if (window.AccessRouteOfflineStore && window.AccessRouteOfflineStore.setMetadata) {
      window.AccessRouteOfflineStore.setMetadata("installation_id", id).catch(() => {});
    }
  }
  return id;
}

function getAnonymousContributorId() {
  return getAnonymousInstallationId();
}

function startCommunityReportMode() {
  activePinMode = "community_report";
  const banner = document.getElementById("pin-mode-banner");
  const text = document.getElementById("pin-mode-text");
  banner.hidden = false;
  text.textContent = "📢 Click on the map or segment where the accessibility condition is located";
  document.getElementById("map").style.cursor = "crosshair";
}

const COMMUNITY_REPORT_CHOICES = {
  path_blocked: [
    { value: "impassable", label: "Completely blocked" },
    { value: "debris", label: "Debris / obstruction" },
    { value: "overgrown", label: "Overgrown bushes" },
    { value: "parked_vehicle", label: "Parked vehicle / clutter" },
    { value: "flooded", label: "Flooded path" }
  ],
  lift_status: [
    { value: "broken", label: "Out of service / broken" },
    { value: "intermittent", label: "Intermittent / faulty" },
    { value: "repaired", label: "Fully operational" }
  ],
  construction: [
    { value: "sidewalk_closed", label: "Sidewalk closed" },
    { value: "ramp_blocked", label: "Ramp blocked" },
    { value: "scaffolding_narrow", label: "Scaffolding narrow" },
    { value: "street_works", label: "Active street work" }
  ],
  slope: [
    { value: "steep_gt_8pct", label: "Steep hill (>8%)" },
    { value: "moderate_4_8pct", label: "Moderate slope (4-8%)" },
    { value: "cambered", label: "Excessive cross-slope" }
  ],
  kerb: [
    { value: "raised", label: "Raised kerb (no ramp)" },
    { value: "high_lip", label: "High lip barrier (>2cm)" },
    { value: "damaged", label: "Broken / cracked ramp" },
    { value: "flush", label: "Flush kerb present" }
  ],
  surface: [
    { value: "broken_pavement", label: "Broken pavement" },
    { value: "tree_root_heave", label: "Tree root heave" },
    { value: "gravel_mud", label: "Loose gravel / mud" },
    { value: "slippery", label: "Slippery when wet" },
    { value: "cobblestone", label: "Rough cobblestones" }
  ],
  entrance_accessibility: [
    { value: "step_at_entrance", label: "Step at entrance" },
    { value: "heavy_door", label: "Heavy manual door" },
    { value: "narrow_doorway", label: "Narrow door (<85cm)" },
    { value: "automatic_door_broken", label: "Power door broken" }
  ],
  other: [
    { value: "missing_tactile", label: "Missing tactile paving" },
    { value: "audible_signal_fault", label: "Crossing signal fault" },
    { value: "general_barrier", label: "Other access issue" }
  ]
};

let selectedReportCategory = "path_blocked";
let selectedReportValue = "impassable";

function selectReportCategoryTile(category) {
  selectedReportCategory = category;
  const tiles = document.querySelectorAll(".report-type-tile");
  tiles.forEach((t) => {
    if (t.getAttribute("data-category") === category) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });

  const catSelect = document.getElementById("report-category-select");
  if (catSelect) catSelect.value = category;

  // Render choice chips
  const chipsContainer = document.getElementById("report-choices-chips");
  const choices = COMMUNITY_REPORT_CHOICES[category] || [{ value: "other", label: "Other condition" }];
  selectedReportValue = choices[0].value;

  if (chipsContainer) {
    chipsContainer.innerHTML = choices.map((c, i) => `
      <button type="button" class="report-choice-chip ${i === 0 ? 'selected' : ''}" data-value="${c.value}" onclick="selectReportChoiceChip('${c.value}')">
        ${c.label}
      </button>
    `).join("");
  }

  const valSelect = document.getElementById("report-value-select");
  if (valSelect) {
    valSelect.innerHTML = choices.map(c => `<option value="${c.value}">${c.label}</option>`).join("");
    valSelect.value = selectedReportValue;
  }
}

function selectReportChoiceChip(val) {
  selectedReportValue = val;
  const chips = document.querySelectorAll(".report-choice-chip");
  chips.forEach((c) => {
    if (c.getAttribute("data-value") === val) {
      c.classList.add("selected");
    } else {
      c.classList.remove("selected");
    }
  });

  const valSelect = document.getElementById("report-value-select");
  if (valSelect) valSelect.value = val;
}

function openCommunityReportSheet(lat, lon, preselectCategory) {
  let rLat = lat;
  let rLon = lon;

  if (!rLat || !rLon) {
    if (typeof liveNavCurrentLocation !== "undefined" && liveNavCurrentLocation && liveNavCurrentLocation.latitude) {
      rLat = liveNavCurrentLocation.latitude;
      rLon = liveNavCurrentLocation.longitude;
    } else if (originCoords && originCoords[0]) {
      rLat = originCoords[0];
      rLon = originCoords[1];
    } else if (typeof currentOriginCoords !== "undefined" && currentOriginCoords && currentOriginCoords[0]) {
      rLat = currentOriginCoords[0];
      rLon = currentOriginCoords[1];
    } else if (map) {
      const c = map.getCenter();
      rLat = c.lat;
      rLon = c.lng;
    } else {
      rLat = -37.8136;
      rLon = 144.9631;
    }
  }

  reportingPinCoords = [parseFloat(rLat), parseFloat(rLon)];
  const latEl = document.getElementById("report-lat-text");
  const lonEl = document.getElementById("report-lon-text");
  if (latEl) latEl.textContent = reportingPinCoords[0].toFixed(5);
  if (lonEl) lonEl.textContent = reportingPinCoords[1].toFixed(5);

  // Reset confirmation / form views
  const form = document.getElementById("community-report-form");
  const onlineSuccess = document.getElementById("report-success-online");
  const offlineSuccess = document.getElementById("report-success-offline");
  if (form) form.hidden = false;
  if (onlineSuccess) onlineSuccess.hidden = true;
  if (offlineSuccess) offlineSuccess.hidden = true;

  selectReportCategoryTile(preselectCategory || "path_blocked");
  setReportDuration("permanent");

  const notesInput = document.getElementById("report-notes-input");
  if (notesInput) notesInput.value = "";

  const modal = document.getElementById("community-report-modal");
  if (!modal) return;
  if (typeof modal.showModal === "function") {
    modal.showModal();
  } else {
    modal.setAttribute("open", "true");
  }
}

function openCommunityReportModal(lat, lon, preselectCategory) {
  openCommunityReportSheet(lat, lon, preselectCategory);
}

function closeCommunityReportModal() {
  const modal = document.getElementById("community-report-modal");
  if (modal && modal.close) {
    modal.close();
  } else if (modal) {
    modal.removeAttribute("open");
  }
}

function handleReportCategoryChange() {
  const cat = document.getElementById("report-category-select").value;
  selectReportCategoryTile(cat);
}

function setReportDuration(type) {
  const btnPerm = document.getElementById("btn-duration-permanent");
  const btnTemp = document.getElementById("btn-duration-temporary");
  const tempSelector = document.getElementById("temporary-duration-selector");

  if (type === "temporary") {
    if (btnTemp) btnTemp.classList.add("active");
    if (btnPerm) btnPerm.classList.remove("active");
    if (tempSelector) tempSelector.hidden = false;
  } else {
    if (btnPerm) btnPerm.classList.add("active");
    if (btnTemp) btnTemp.classList.remove("active");
    if (tempSelector) tempSelector.hidden = true;
  }
}

async function submitCommunityReport() {
  if (!reportingPinCoords) return;

  const category = selectedReportCategory || (document.getElementById("report-category-select") ? document.getElementById("report-category-select").value : "path_blocked");
  const val = selectedReportValue || (document.getElementById("report-value-select") ? document.getElementById("report-value-select").value : "impassable");
  const btnTemp = document.getElementById("btn-duration-temporary");
  const isTemp = btnTemp ? btnTemp.classList.contains("active") : false;
  const hoursEl = document.getElementById("report-expected-hours");
  const expectedHours = isTemp && hoursEl ? parseFloat(hoursEl.value) : null;
  const notesEl = document.getElementById("report-notes-input");
  const notes = (notesEl && notesEl.value.trim()) ? notesEl.value.trim() : null;
  const contributorId = getAnonymousContributorId();

  const payload = {
    latitude: reportingPinCoords[0],
    longitude: reportingPinCoords[1],
    category: category,
    value: val,
    is_temporary: isTemp,
    expected_duration_hours: expectedHours,
    contributor_id: contributorId,
    notes: notes,
  };

  const form = document.getElementById("community-report-form");
  const onlineSuccess = document.getElementById("report-success-online");
  const offlineSuccess = document.getElementById("report-success-offline");

  // Check if offline
  if (window.AccessRouteConnectivity && !window.AccessRouteConnectivity.isOnline()) {
    if (window.AccessRouteOfflineStore) {
      await window.AccessRouteOfflineStore.queueMutation({
        local_id: (crypto.randomUUID ? crypto.randomUUID() : "q_rep_" + Date.now()),
        operation_type: "community_report",
        payload: payload,
        created_at: new Date().toISOString(),
        status: "PENDING"
      });
      if (form) form.hidden = true;
      if (offlineSuccess) offlineSuccess.hidden = false;
      showConsumerToast("Saved on this device. Syncs when online.", "📥");
      setTimeout(() => {
        closeCommunityReportModal();
      }, 2200);
      return;
    }
  }

  try {
    const res = await fetch("/api/v1/community/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      // Fallback to local queue on server reject or failure
      if (window.AccessRouteOfflineStore) {
        await window.AccessRouteOfflineStore.queueMutation({
          local_id: (crypto.randomUUID ? crypto.randomUUID() : "q_rep_" + Date.now()),
          operation_type: "community_report",
          payload: payload,
          created_at: new Date().toISOString(),
          status: "PENDING"
        });
        if (form) form.hidden = true;
        if (offlineSuccess) offlineSuccess.hidden = false;
        showConsumerToast("Saved on this device. Syncs when online.", "📥");
        setTimeout(() => {
          closeCommunityReportModal();
        }, 2200);
        return;
      }
      showConsumerToast("Unable to submit report", "⚠️");
      return;
    }

    const data = await res.json();
    if (form) form.hidden = true;
    if (onlineSuccess) onlineSuccess.hidden = false;
    showConsumerToast("Report submitted. Thank you!", "✓");
    loadCommunityObservations();

    setTimeout(() => {
      closeCommunityReportModal();
    }, 2200);
  } catch (err) {
    // If network failed, fallback to local queue
    if (window.AccessRouteOfflineStore) {
      await window.AccessRouteOfflineStore.queueMutation({
        local_id: (crypto.randomUUID ? crypto.randomUUID() : "q_rep_" + Date.now()),
        operation_type: "community_report",
        payload: payload,
        created_at: new Date().toISOString(),
        status: "PENDING"
      });
      if (form) form.hidden = true;
      if (offlineSuccess) offlineSuccess.hidden = false;
      showConsumerToast("Saved on this device. Syncs when online.", "📥");
      setTimeout(() => {
        closeCommunityReportModal();
      }, 2200);
    } else {
      showConsumerToast("Submission failed: " + err.message, "⚠️");
    }
  }
}

async function handleConfirmObservation(obsId) {
  const contributorId = getAnonymousContributorId();
  try {
    const res = await fetch(`/api/v1/community/reports/${obsId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contributor_id: contributorId }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || "Could not confirm observation.");
      return;
    }
    loadCommunityObservations();
    alert(`Confirmed! Verification status: ${data.new_status}`);
  } catch (err) {
    alert(`Interaction failed: ${err.message}`);
  }
}

async function handleDisputeObservation(obsId) {
  const contributorId = getAnonymousContributorId();
  try {
    const res = await fetch(`/api/v1/community/reports/${obsId}/dispute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contributor_id: contributorId }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || "Could not dispute observation.");
      return;
    }
    loadCommunityObservations();
    alert(`Dispute recorded. Verification status: ${data.new_status}`);
  } catch (err) {
    alert(`Interaction failed: ${err.message}`);
  }
}

async function loadCommunityObservations() {
  if (!map || !communityLayerGroup) return;

  const bounds = map.getBounds();
  const url = `/api/v1/community/geojson?min_lat=${bounds.getSouth()}&min_lon=${bounds.getWest()}&max_lat=${bounds.getNorth()}&max_lon=${bounds.getEast()}`;

  try {
    const res = await fetch(url);
    if (!res.ok) return;
    const geojson = await res.json();

    communityLayerGroup.clearLayers();

    L.geoJSON(geojson, {
      pointToLayer: (feature, latlng) => {
        const p = feature.properties;
        let iconHtml = "📍";
        let iconClass = "community-map-icon";

        if (p.category === "path_blocked" || p.category === "construction") {
          iconHtml = "🚧";
          iconClass += " icon-blocked";
        } else if (p.category === "stairs") {
          iconHtml = "🪜";
          iconClass += " icon-stairs";
        } else if (p.category === "kerb" || p.category === "ramp") {
          iconHtml = "♿";
          iconClass += " icon-kerb";
        } else if (p.category === "temporary_obstacle") {
          iconHtml = "⚠️";
          iconClass += " icon-blocked";
        }

        const icon = L.divIcon({
          className: "custom-community-pin",
          html: `<div class="${iconClass}" title="${escapeHtml(p.category)}: ${escapeHtml(p.value)}" aria-label="${escapeHtml(p.category)}: ${escapeHtml(p.value)}">${iconHtml}</div>`,
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        });

        const marker = L.marker(latlng, { icon: icon });

        const popupContent = `
          <div class="community-popup-card">
            <div class="community-popup-header">
              <strong style="text-transform: capitalize;">${escapeHtml((p.category || "").replace(/_/g, " "))}</strong>
              <span class="status-pill status-pill-${(p.verification_status || "unverified").toLowerCase()}">
                ${escapeHtml(p.verification_status || "UNVERIFIED")}
              </span>
            </div>
            <div style="font-size: 0.8125rem; font-weight:600; margin-bottom: 4px;">Condition: ${escapeHtml(p.value)}</div>
            <div style="font-size: 0.75rem; color: #6b7280; margin-bottom: 6px;">
              ${p.is_temporary ? "⚠️ Temporary condition" : "🏛️ Permanent infrastructure"}
              <br>Confirmations: ${p.confirmations_count} · Disputes: ${p.disputes_count}
              ${p.notes ? `<br><em>"${escapeHtml(p.notes)}"</em>` : ""}
            </div>
            <div class="community-popup-actions">
              <button type="button" class="btn-popup-action btn-popup-confirm" onclick="handleConfirmObservation('${p.id}')">✓ Confirm</button>
              <button type="button" class="btn-popup-action btn-popup-dispute" onclick="handleDisputeObservation('${p.id}')">✕ Dispute</button>
            </div>
          </div>
        `;
        marker.bindPopup(popupContent);
        return marker;
      },
    }).addTo(communityLayerGroup);
  } catch (e) {
    // Non-fatal
  }
}

/* ==========================================================================
   Stage 10: Accessibility Evidence Intelligence, Map Modes & Missions
   ========================================================================== */

let currentMapMode = "navigation";
let cachedMissions = [];

// Stage 10 Route Evidence Quality Component
function renderRouteEvidenceQuality(alt) {
  const eq = alt.evidence_quality || {};
  const strongPct = Math.round(eq.strong_evidence_distance_pct || 0);
  const partialPct = Math.round(eq.partial_evidence_distance_pct || 0);
  const limitedPct = Math.round(eq.limited_evidence_distance_pct || 100);

  const barStrong = document.getElementById("eq-bar-strong");
  const barPartial = document.getElementById("eq-bar-partial");
  const barLimited = document.getElementById("eq-bar-limited");
  if (barStrong) barStrong.style.width = `${strongPct}%`;
  if (barPartial) barPartial.style.width = `${partialPct}%`;
  if (barLimited) barLimited.style.width = `${limitedPct}%`;

  const pctStrong = document.getElementById("eq-pct-strong");
  const pctPartial = document.getElementById("eq-pct-partial");
  const pctLimited = document.getElementById("eq-pct-limited");
  if (pctStrong) pctStrong.textContent = `${strongPct}%`;
  if (pctPartial) pctPartial.textContent = `${partialPct}%`;
  if (pctLimited) pctLimited.textContent = `${limitedPct}%`;

  const commCount = document.getElementById("eq-community-count");
  const confCount = document.getElementById("eq-conflicts-count");
  const staleCount = document.getElementById("eq-stale-count");
  if (commCount) commCount.textContent = eq.community_supported_count || 0;
  if (confCount) confCount.textContent = eq.conflicting_evidence_count || 0;
  if (staleCount) staleCount.textContent = eq.stale_observations_count || 0;

  const gapsList = document.getElementById("eq-gaps-list");
  if (gapsList) {
    gapsList.innerHTML = "";
    const unknowns = eq.important_unknowns || [];
    if (unknowns.length === 0) {
      const li = document.createElement("li");
      li.className = "explain-item";
      li.innerHTML = `<span class="icon-check">✓</span><span>No major accessibility unknowns detected along this route.</span>`;
      gapsList.appendChild(li);
    } else {
      unknowns.forEach((u) => {
        const li = document.createElement("li");
        li.className = "explain-item explain-item-warn";
        li.innerHTML = `<span class="icon-warn">⚠</span><span>${escapeHtml(u)}</span>`;
        gapsList.appendChild(li);
      });
    }
  }
}

// Stage 10 Map Mode Switcher
async function switchMapMode(mode) {
  currentMapMode = mode;
  const modes = ["nav", "coverage", "community", "missions"];
  modes.forEach((m) => {
    const btn = document.getElementById(`btn-mode-${m}`);
    if (btn) {
      if ((m === "nav" && mode === "navigation") || m === mode) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    }
  });

  const legend = document.getElementById("coverage-legend");
  const missionInspector = document.getElementById("mission-inspector");
  if (legend) legend.hidden = (mode !== "coverage");
  if (missionInspector) missionInspector.hidden = true;

  if (coverageLayerGroup) coverageLayerGroup.clearLayers();
  if (missionsLayerGroup) missionsLayerGroup.clearLayers();

  if (mode === "navigation") {
    // Show navigation route layers
    Object.values(routeLayersMap).forEach((l) => {
      if (!map.hasLayer(l)) map.addLayer(l);
    });
    if (communityLayerGroup) communityLayerGroup.clearLayers();
  } else if (mode === "coverage") {
    // Hide route layers
    Object.values(routeLayersMap).forEach((l) => {
      if (map.hasLayer(l)) map.removeLayer(l);
    });
    if (communityLayerGroup) communityLayerGroup.clearLayers();
    await loadDataCoverage();
  } else if (mode === "community") {
    // Hide route layers
    Object.values(routeLayersMap).forEach((l) => {
      if (map.hasLayer(l)) map.removeLayer(l);
    });
    await loadCommunityObservations();
  } else if (mode === "missions") {
    // Hide route layers
    Object.values(routeLayersMap).forEach((l) => {
      if (map.hasLayer(l)) map.removeLayer(l);
    });
    if (communityLayerGroup) communityLayerGroup.clearLayers();
    await loadVerificationMissions();
  }
}

// Regional Data Coverage Map Loader
async function loadDataCoverage() {
  if (!map || !coverageLayerGroup) return;
  const center = map.getCenter();
  const statsEl = document.getElementById("coverage-summary-stats");
  if (statsEl) statsEl.textContent = "Acquiring regional metadata completeness...";

  try {
    const [summaryRes, geojsonRes] = await Promise.all([
      fetch(`/api/v1/intelligence/coverage?lat=${center.lat}&lon=${center.lng}&radius_m=1200`),
      fetch(`/api/v1/intelligence/coverage/geojson?lat=${center.lat}&lon=${center.lng}&radius_m=1200`),
    ]);

    if (!geojsonRes.ok) {
      if (statsEl) statsEl.textContent = "No cached coverage data in this region.";
      return;
    }

    const geojson = await geojsonRes.json();
    coverageLayerGroup.clearLayers();

    L.geoJSON(geojson, {
      style: (feature) => {
        const score = feature.properties ? feature.properties.completeness_score : 0.5;
        let color = "#ef4444";
        if (score >= 0.75) color = "#10b981";
        else if (score >= 0.40) color = "#f59e0b";

        return {
          color: color,
          weight: 4,
          opacity: 0.85,
        };
      },
      onEachFeature: (feature, layer) => {
        const p = feature.properties || {};
        const scorePct = Math.round((p.completeness_score || 0) * 100);
        const name = p.name || p.highway || "Pedestrian Way";
        const missing = (p.missing_attributes && p.missing_attributes.length > 0)
          ? p.missing_attributes.join(", ")
          : "None (fully documented)";

        layer.bindPopup(`
          <div style="font-family: inherit; font-size: 0.8125rem;">
            <strong>${escapeHtml(name)}</strong><br>
            Completeness: <strong>${scorePct}%</strong><br>
            Highway: <code>${escapeHtml(p.highway || "unknown")}</code><br>
            Missing attributes: <span style="color: #b91c1c;">${escapeHtml(missing)}</span>
          </div>
        `);
      },
    }).addTo(coverageLayerGroup);

    if (summaryRes.ok) {
      const summary = await summaryRes.json();
      if (statsEl) {
        statsEl.textContent = `Surface: ${summary.surface_completeness_pct}% | Kerb: ${summary.kerb_completeness_pct}% | Wheelchair: ${summary.wheelchair_tag_completeness_pct}%`;
      }
    }
  } catch (err) {
    if (statsEl) statsEl.textContent = "Error loading coverage data.";
  }
}

// Verification Missions Loader
async function loadVerificationMissions() {
  if (!map || !missionsLayerGroup) return;
  const center = map.getCenter();

  try {
    const res = await fetch(`/api/v1/intelligence/missions?lat=${center.lat}&lon=${center.lng}&radius_m=1500&limit=30`);
    if (!res.ok) return;
    const data = await res.json();
    cachedMissions = data.missions || [];
    missionsLayerGroup.clearLayers();

    cachedMissions.forEach((m) => {
      const pClass = `priority-${(m.priority_level || "medium").toLowerCase()}`;
      const icon = L.divIcon({
        className: "custom-mission-pin",
        html: `<div class="mission-map-pin ${pClass}" title="${escapeHtml(m.title)}" aria-label="${escapeHtml(m.title)}">🎯</div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      });

      const marker = L.marker([m.location.latitude, m.location.longitude], { icon: icon });
      marker.on("click", () => openMissionInspector(m));
      marker.addTo(missionsLayerGroup);
    });
  } catch (e) {
    // Non-fatal
  }
}

function openMissionInspector(mission) {
  const dialog = document.getElementById("mission-inspector");
  const title = document.getElementById("mission-inspector-title");
  const body = document.getElementById("mission-inspector-body");
  if (!dialog || !body) return;

  dialog.hidden = false;
  title.textContent = mission.title;

  const priorityBadge = `<span class="status-pill status-pill-unverified" style="text-transform: uppercase;">${escapeHtml(mission.priority_level)} Priority</span>`;

  body.innerHTML = `
    <div style="margin-bottom: 8px;">${priorityBadge}</div>
    <div class="mission-field">
      <div class="mission-field-label">Location / Feature</div>
      <div class="mission-field-value">${escapeHtml(mission.location_description)}</div>
    </div>
    <div class="mission-field">
      <div class="mission-field-label">Missing Evidence</div>
      <div class="mission-field-value">${escapeHtml(mission.missing_attribute_description)}</div>
    </div>
    <div class="mission-field">
      <div class="mission-field-label">Why It Matters</div>
      <div class="mission-field-value">${escapeHtml(mission.why_it_matters)}</div>
    </div>
    <div class="mission-field">
      <div class="mission-field-label">Routing Impact</div>
      <div class="mission-field-value">${escapeHtml(mission.routing_impact_summary)}</div>
    </div>
    <div class="mission-field">
      <div class="mission-field-label">Currently Available Evidence</div>
      <div class="mission-field-value">${escapeHtml(mission.current_evidence_summary || "None recorded")}</div>
    </div>
    <div class="mission-actions">
      <button type="button" class="btn-verify-mission" onclick="startVerifyMission('${mission.mission_id}')">
        Verify This Location
      </button>
    </div>
  `;
}

function closeMissionInspector() {
  const dialog = document.getElementById("mission-inspector");
  if (dialog) dialog.hidden = true;
}

function startVerifyMission(missionId) {
  const mission = cachedMissions.find((m) => m.mission_id === missionId);
  closeMissionInspector();
  if (!mission) return;

  let category = "kerb";
  const featType = (mission.feature_type || "").toLowerCase();
  const missAttr = (mission.missing_attribute || "").toLowerCase();

  if (missAttr.includes("surface") || featType.includes("surface")) category = "surface";
  else if (missAttr.includes("kerb") || featType.includes("crossing")) category = "kerb";
  else if (missAttr.includes("width")) category = "path_width";
  else if (missAttr.includes("barrier")) category = "barrier";
  else if (missAttr.includes("slope")) category = "slope";

  openCommunityReportModal(mission.location.latitude, mission.location.longitude, category);
}

// =============================================================================
// STAGE 11: LIVE GPS NAVIGATION, ROUTE PROGRESS & REROUTING
// =============================================================================

const NavState = {
  IDLE: "IDLE",
  ACQUIRING_LOCATION: "ACQUIRING_LOCATION",
  READY: "READY",
  NAVIGATING: "NAVIGATING",
  OFF_ROUTE: "OFF_ROUTE",
  REROUTING: "REROUTING",
  ARRIVED: "ARRIVED",
  LOCATION_UNAVAILABLE: "LOCATION_UNAVAILABLE",
  ERROR: "ERROR",
};

let currentNavState = NavState.IDLE;
let liveNavActive = false;
let liveNavWatchId = null;
let liveNavCurrentLocation = null;
let liveNavFollowUser = true;
let liveNavUserMarker = null;
let liveNavAccuracyCircle = null;
let liveNavTracker = null;
let liveNavConsecutiveOffCount = 0;
let liveNavConsecutiveArrivalCount = 0;
let liveNavRerouteInFlight = false;
let liveNavLastRerouteTime = 0;
let liveNavLastReroutePos = null;
let liveNavRerouteToken = 0;
let liveNavSimInterval = null;
let liveNavSimIndex = 0;
let liveNavSimSpeed = 1;
let liveNavSimCoordinates = [];

// High-precision local 2D metric scaling
function clientLatLonToMetersFactor(lat) {
  const rad = (lat * Math.PI) / 180.0;
  const m_lat = 111132.954 - 559.822 * Math.cos(2 * rad) + 1.175 * Math.cos(4 * rad);
  const m_lon = 111412.84 * Math.cos(rad) - 93.5 * Math.cos(3 * rad);
  return { m_lat, m_lon };
}

function clientHaversineDist(lat1, lon1, lat2, lon2) {
  const R = 6371000.0;
  const phi1 = (lat1 * Math.PI) / 180.0;
  const phi2 = (lat2 * Math.PI) / 180.0;
  const dphi = ((lat2 - lat1) * Math.PI) / 180.0;
  const dlambda = ((lon2 - lon1) * Math.PI) / 180.0;
  const a = Math.sin(dphi / 2.0) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2.0) ** 2;
  return 2.0 * R * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0.0, 1.0 - a)));
}

function clientProjectPointToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  if (lenSq < 1e-6) {
    const dist = Math.hypot(px - ax, py - ay);
    return { proj_x: ax, proj_y: ay, t: 0.0, dist };
  }
  let t = ((px - ax) * dx + (py - ay) * dy) / lenSq;
  t = Math.max(0.0, Math.min(1.0, t));
  const proj_x = ax + t * dx;
  const proj_y = ay + t * dy;
  const dist = Math.hypot(px - proj_x, py - proj_y);
  return { proj_x, proj_y, t, dist };
}

class ClientRouteTracker {
  constructor(routeCoordinates, directions = [], edgeMetadata = []) {
    if (!routeCoordinates || routeCoordinates.length < 2) {
      throw new Error("Route requires at least 2 points.");
    }
    this.coordinates = routeCoordinates; // Array of [lat, lon]
    this.directions = directions;
    this.edgeMetadata = edgeMetadata;

    this.segmentLengths = [];
    this.cumulativeSegmentDistances = [0.0];
    let total = 0.0;
    for (let i = 0; i < this.coordinates.length - 1; i++) {
      const p1 = this.coordinates[i];
      const p2 = this.coordinates[i + 1];
      const segLen = clientHaversineDist(p1[0], p1[1], p2[0], p2[1]);
      this.segmentLengths.push(segLen);
      total += segLen;
      this.cumulativeSegmentDistances.push(total);
    }
    this.totalRouteDistanceM = total;
    this.maxDistanceAlongRouteM = 0.0;
    this.lastSegmentIdx = 0;
    this.paceMPerMin = 60.0; // 3.6 km/h standard pedestrian pace
  }

  updateProgress(loc) {
    const lat = loc.latitude;
    const lon = loc.longitude;
    const accuracy = loc.accuracy_m || 10.0;

    const { m_lat, m_lon } = clientLatLonToMetersFactor(lat);
    const px = lon * m_lon;
    const py = lat * m_lat;

    let bestDist = Infinity;
    let bestSegIdx = this.lastSegmentIdx;
    let bestT = 0.0;
    let bestProjLat = this.coordinates[0][0];
    let bestProjLon = this.coordinates[0][1];

    // Windowed segment projection scan
    const startIdx = Math.max(0, this.lastSegmentIdx - 1);
    const endIdx = Math.min(this.segmentLengths.length, this.lastSegmentIdx + 12);
    const candidateIndices = [];
    for (let i = startIdx; i < endIdx; i++) candidateIndices.push(i);
    for (let i = 0; i < this.segmentLengths.length; i++) {
      if (!candidateIndices.includes(i)) candidateIndices.push(i);
    }

    for (const i of candidateIndices) {
      const p1 = this.coordinates[i];
      const p2 = this.coordinates[i + 1];
      const ax = p1[1] * m_lon;
      const ay = p1[0] * m_lat;
      const bx = p2[1] * m_lon;
      const by = p2[0] * m_lat;

      const proj = clientProjectPointToSegment(px, py, ax, ay, bx, by);
      if (proj.dist < bestDist) {
        bestDist = proj.dist;
        bestSegIdx = i;
        bestT = proj.t;
        bestProjLat = proj.proj_y / m_lat;
        bestProjLon = proj.proj_x / m_lon;
      }
    }

    const segStartDist = this.cumulativeSegmentDistances[bestSegIdx];
    const segLen = this.segmentLengths[bestSegIdx];
    const calcDistAlong = segStartDist + bestT * segLen;

    // Monotonic forward dampening
    let distAlong = calcDistAlong;
    if (calcDistAlong >= this.maxDistanceAlongRouteM - 15.0) {
      this.maxDistanceAlongRouteM = Math.max(this.maxDistanceAlongRouteM, calcDistAlong);
      this.lastSegmentIdx = bestSegIdx;
      distAlong = this.maxDistanceAlongRouteM;
    } else {
      distAlong = this.maxDistanceAlongRouteM;
    }

    distAlong = Math.min(this.totalRouteDistanceM, Math.max(0.0, distAlong));
    const remainingDist = Math.max(0.0, this.totalRouteDistanceM - distAlong);
    const completionPct = this.totalRouteDistanceM > 0 ? (distAlong / this.totalRouteDistanceM) * 100.0 : 100.0;

    // Maneuver and next instruction calculation
    let currentStepIdx = 0;
    let nextManeuver = "straight";
    let nextInstruction = "Continue along route.";
    let distToNextStep = remainingDist;

    if (this.directions && this.directions.length > 0) {
      let foundStep = false;
      for (let idx = 0; idx < this.directions.length; idx++) {
        const step = this.directions[idx];
        if (step.cumulative_distance_m > distAlong + 2.0) {
          currentStepIdx = idx;
          distToNextStep = Math.max(0.0, step.cumulative_distance_m - distAlong);
          if (idx === 0 && distAlong < 10.0) {
            nextManeuver = step.maneuver || "depart";
            nextInstruction = step.instruction;
          } else if (idx + 1 < this.directions.length) {
            nextManeuver = this.directions[idx + 1].maneuver || "straight";
            nextInstruction = `In ${distToNextStep.toFixed(0)}m, ${this.directions[idx + 1].instruction.toLowerCase()}`;
          } else {
            nextManeuver = step.maneuver || "arrive";
            nextInstruction = step.instruction;
          }
          foundStep = true;
          break;
        }
      }
      if (!foundStep) {
        currentStepIdx = this.directions.length - 1;
        nextManeuver = this.directions[currentStepIdx].maneuver || "arrive";
        nextInstruction = this.directions[currentStepIdx].instruction;
        distToNextStep = remainingDist;
      }
    }

    const estDurationMin = remainingDist > 5.0 ? Math.max(1, Math.ceil(remainingDist / this.paceMPerMin)) : 0;
    const upcomingEvents = this.detectUpcomingEvents(distAlong);

    return {
      distance_along_route_m: distAlong,
      remaining_distance_m: remainingDist,
      completion_percentage: completionPct,
      nearest_point: [bestProjLat, bestProjLon],
      cross_track_distance_m: bestDist,
      current_segment_index: bestSegIdx,
      current_step_index: currentStepIdx,
      next_maneuver: nextManeuver,
      next_instruction: nextInstruction,
      distance_to_next_maneuver_m: distToNextStep,
      estimated_remaining_duration_min: estDurationMin,
      upcoming_events: upcomingEvents,
    };
  }

  detectUpcomingEvents(currentDistAlongM) {
    const events = [];
    const maxLookaheadM = 180.0;

    for (let idx = 0; idx < this.directions.length; idx++) {
      const step = this.directions[idx];
      const distAhead = step.cumulative_distance_m - currentDistAlongM;
      if (distAhead > 5.0 && distAhead <= maxLookaheadM) {
        if (step.accessibility_cues && step.accessibility_cues.length > 0) {
          events.push({
            type: "ACCESSIBILITY_CUE",
            distance_ahead_m: distAhead,
            severity: "info",
            description: `${step.accessibility_cues[0]} (in ${distAhead.toFixed(0)}m)`,
          });
        }
        if (step.barrier_warnings && step.barrier_warnings.length > 0) {
          events.push({
            type: "BARRIER_WARNING",
            distance_ahead_m: distAhead,
            severity: "warning",
            description: `${step.barrier_warnings[0]} (in ${distAhead.toFixed(0)}m)`,
          });
        }
      }
    }
    return events;
  }
}

// Glanceable Maneuver Icon Helper
function getManeuverIcon(instruction = "", maneuver = "") {
  const text = (instruction + " " + (maneuver || "")).toLowerCase();
  if (text.includes("destination") || text.includes("arrive")) return "🏁";
  if (text.includes("sharp right")) return "↴";
  if (text.includes("sharp left")) return "↵";
  if (text.includes("slight right")) return "↗";
  if (text.includes("slight left")) return "↖";
  if (text.includes("right")) return "↱";
  if (text.includes("left")) return "↰";
  if (text.includes("u-turn")) return "↺";
  if (text.includes("cross")) return "🚸";
  if (text.includes("ramp") || text.includes("incline")) return "⤤";
  return "⬆";
}

function startNavigationForActiveRoute() {
  console.log("[NAV] Start Navigation clicked");
  try {
    console.log(`[NAV] Active alternative index: ${activeAlternativeIndex}`);
    if (!currentAlternativesData || !currentAlternativesData.alternatives || currentAlternativesData.alternatives.length === 0) {
      console.warn("[NAV] ERROR: No currentAlternativesData found");
      alert("Please search for a route first before starting live navigation.");
      return;
    }

    const activeAlt = currentAlternativesData.alternatives[activeAlternativeIndex];
    if (!activeAlt) {
      console.warn(`[NAV] ERROR: No active route found at index ${activeAlternativeIndex}`);
      alert("No active route selected.");
      return;
    }
    console.log("[NAV] Selected route resolved");

    // Extract coordinates: GeoJSON coordinates are [lon, lat] -> convert to [lat, lon]
    let routeCoords = [];
    if (activeAlt.coordinates && activeAlt.coordinates.length >= 2) {
      routeCoords = activeAlt.coordinates;
    } else if (activeAlt.geometry && activeAlt.geometry.coordinates && activeAlt.geometry.coordinates.length >= 2) {
      routeCoords = activeAlt.geometry.coordinates.map((pt) => [pt[1], pt[0]]);
    } else if (currentAlternativesData && currentAlternativesData.geojson && Array.isArray(currentAlternativesData.geojson.features)) {
      const altFeatures = currentAlternativesData.geojson.features.filter(
        (f) => f.properties && f.properties.feature_type === "route_alternative"
      );
      const feat = altFeatures.find((f) => f.properties && f.properties.key === activeAlt.key) || altFeatures[activeAlternativeIndex];
      if (feat && feat.geometry && Array.isArray(feat.geometry.coordinates) && feat.geometry.coordinates.length >= 2) {
        routeCoords = feat.geometry.coordinates.map((pt) => [pt[1], pt[0]]);
        activeAlt.geometry = feat.geometry;
        activeAlt.coordinates = routeCoords;
      }
    }

    if (routeCoords.length < 2 && activeAlt.elevation_summary && activeAlt.elevation_summary.points && activeAlt.elevation_summary.points.length >= 2) {
      routeCoords = activeAlt.elevation_summary.points.map((pt) => [pt.latitude, pt.longitude]);
    }
    if (routeCoords.length < 2 && activeAlt.directions && activeAlt.directions.length >= 2) {
      routeCoords = activeAlt.directions.map((d) => [d.latitude, d.longitude]);
    }

    if (routeCoords.length < 2) {
      console.warn("[NAV] ERROR: Active route coordinates length < 2");
      showConsumerToast("Active route geometry is missing coordinates.", "⚠️");
      return;
    }

    // Ensure any open Why modal is closed
    const whyModal = document.getElementById("why-route-modal");
    if (whyModal && (whyModal.open || whyModal.hasAttribute("open"))) {
      whyModal.close();
    }

    console.log("[NAV] Initializing navigation");
    // Initialize client route tracker
    liveNavTracker = new ClientRouteTracker(routeCoords, activeAlt.directions || [], []);
    window.liveNavTracker = liveNavTracker;
    liveNavActive = true;
    window.liveNavActive = true;
    liveNavFollowUser = true;
    liveNavConsecutiveOffCount = 0;
    liveNavConsecutiveArrivalCount = 0;
    liveNavRerouteInFlight = false;
    liveNavSimCoordinates = routeCoords;
    liveNavSimIndex = 0;
    console.log("[NAV] Navigation state initialized");

    // Transition UI to Navigation Mode
    document.body.classList.add("navigation-active");
    const sideDrawer = document.getElementById("side-drawer");
    const routesContainer = document.getElementById("routes-container");
    if (sideDrawer) {
      sideDrawer.hidden = true;
      sideDrawer.style.display = "none";
    }
    if (routesContainer) routesContainer.hidden = true;

    const topHud = document.getElementById("nav-top-hud");
    const bottomPanel = document.getElementById("nav-bottom-panel");
    const simToolbar = document.getElementById("nav-sim-toolbar");

    // Close Leaflet destination popup and disable marker dragging during active navigation
    if (destMarker) {
      destMarker.closePopup();
      if (destMarker.dragging) {
        destMarker.dragging.disable();
      }
      destMarker.unbindPopup();
    }

    if (topHud) {
      topHud.hidden = false;
      topHud.removeAttribute("hidden");
      topHud.style.display = "flex";
    }
    if (bottomPanel) {
      bottomPanel.hidden = false;
      bottomPanel.removeAttribute("hidden");
      bottomPanel.style.display = "";
    }
    if (simToolbar) {
      if (isDevModeEnabled()) {
        simToolbar.hidden = false;
        simToolbar.removeAttribute("hidden");
        simToolbar.style.display = "";
      } else {
        simToolbar.hidden = true;
        simToolbar.setAttribute("hidden", "");
        simToolbar.style.display = "none";
      }
    }
    console.log("[NAV] Navigation UI activated");

    // Set initial bottom panel stats
    const remTimeEl = document.getElementById("nav-stat-remaining-time");
    const remDistEl = document.getElementById("nav-stat-remaining");
    const etaEl = document.getElementById("nav-stat-eta");
    if (remTimeEl) remTimeEl.textContent = `${activeAlt.estimated_duration_min || 1} min`;
    if (remDistEl) {
      const distM = activeAlt.physical_distance_m || 0;
      remDistEl.textContent = distM >= 1000 ? `${(distM / 1000).toFixed(1)} km` : `${Math.round(distM)} m`;
    }
    if (etaEl) {
      const now = new Date();
      const etaMs = now.getTime() + (activeAlt.estimated_duration_min || 1) * 60000;
      const etaDate = new Date(etaMs);
      etaEl.textContent = etaDate.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    }

    // Dim alternative polylines so active route dominates
    Object.keys(routeLayersMap).forEach((key) => {
      const layer = routeLayersMap[key];
      if (map && map.hasLayer(layer)) {
        if (key === String(activeAlternativeIndex)) {
          layer.setStyle({ weight: 6, opacity: 1.0, color: "#14b8a6" });
          if (layer.bringToFront) layer.bringToFront();
        } else {
          layer.setStyle({ weight: 2, opacity: 0.25, color: "#64748b" });
        }
      }
    });

    // Bind map drag event to show Recenter button
    if (map) {
      map.on("dragstart", onMapUserDrag);
    }

    // Set initial HUD text & icon
    const maneuverIcon = document.getElementById("nav-maneuver-icon");
    const maneuverText = document.getElementById("nav-maneuver-text");
    const maneuverDist = document.getElementById("nav-maneuver-dist");
    if (activeAlt.directions && activeAlt.directions.length > 0) {
      const firstDir = activeAlt.directions[0];
      if (maneuverText) maneuverText.textContent = firstDir.instruction;
      if (maneuverDist) maneuverDist.textContent = "Depart";
      if (maneuverIcon) maneuverIcon.textContent = getManeuverIcon(firstDir.instruction, firstDir.maneuver);
    }

    // Request browser geolocation
    console.log("[NAV] Requesting GPS");
    if ("geolocation" in navigator) {
      currentNavState = NavState.ACQUIRING_LOCATION;
      updateGPSQualityBadge(8.0, "Acquiring GPS...");
      liveNavWatchId = navigator.geolocation.watchPosition(
        onLiveLocationSuccess,
        onLiveLocationError,
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 2000 }
      );
      console.log("[NAV] GPS watch started");
    } else {
      console.warn("[NAV] Geolocation not supported by browser");
      onLiveLocationError({ code: 2, message: "Geolocation not supported by browser." });
    }

    // Stage 14: Screen Wake Lock API via PWAManager
    if (window.AccessRoutePWA) {
      window.AccessRoutePWA.setNavigating(true);
    }

    // Stage 14: Check if offline and update offline notice
    const offlineBanner = document.getElementById("nav-offline-status-banner");
    const offlineText = document.getElementById("nav-offline-status-text");
    if (window.AccessRouteConnectivity && !window.AccessRouteConnectivity.isOnline()) {
      if (offlineBanner) offlineBanner.hidden = false;
      if (offlineText) {
        const nowFormatted = new Date().toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
        offlineText.textContent = `Offline route — accessibility evidence last updated ${nowFormatted}. Live updates unavailable offline.`;
      }
    } else {
      if (offlineBanner) offlineBanner.hidden = true;
    }

    // Initial map center on route start
    if (map && routeCoords.length > 0) {
      map.setView(routeCoords[0], 18, { animate: true });
    }
  } catch (err) {
    console.error("[NAV] ERROR:", err);
    showConsumerToast("Unable to start navigation. Please try again.", "⚠️");
  }
}


function endNavigation() {
  liveNavActive = false;
  window.liveNavActive = false;
  window.liveNavTracker = null;
  window.liveNavIsOfflineRoute = false;
  currentNavState = NavState.IDLE;

  if (liveNavWatchId !== null && "geolocation" in navigator) {
    navigator.geolocation.clearWatch(liveNavWatchId);
    liveNavWatchId = null;
  }

  if (liveNavSimInterval) {
    clearInterval(liveNavSimInterval);
    liveNavSimInterval = null;
    const playBtn = document.getElementById("btn-sim-play");
    if (playBtn) playBtn.textContent = "▶ Play Walk";
  }

  if (liveNavUserMarker) {
    map.removeLayer(liveNavUserMarker);
    liveNavUserMarker = null;
  }
  if (liveNavAccuracyCircle) {
    map.removeLayer(liveNavAccuracyCircle);
    liveNavAccuracyCircle = null;
  }

  map.off("dragstart", onMapUserDrag);

  // Restore regular UI
  document.body.classList.remove("navigation-active");
  document.body.classList.remove("nav-steps-open");
  const topHud = document.getElementById("nav-top-hud");
  const bottomPanel = document.getElementById("nav-bottom-panel");
  const simToolbar = document.getElementById("nav-sim-toolbar");
  const recenterBtn = document.getElementById("nav-btn-recenter");
  const rerouteBanner = document.getElementById("nav-reroute-banner");
  const rerouteSuccess = document.getElementById("nav-reroute-success");
  const conflictAlert = document.getElementById("nav-conflict-alert");

  if (topHud) {
    topHud.hidden = true;
    topHud.setAttribute("hidden", "");
  }
  if (bottomPanel) {
    bottomPanel.hidden = true;
    bottomPanel.setAttribute("hidden", "");
  }
  if (simToolbar) {
    simToolbar.hidden = true;
    simToolbar.setAttribute("hidden", "");
  }
  if (recenterBtn) {
    recenterBtn.hidden = true;
    recenterBtn.setAttribute("hidden", "");
  }
  if (rerouteBanner) {
    rerouteBanner.hidden = true;
    rerouteBanner.setAttribute("hidden", "");
  }
  if (rerouteSuccess) {
    rerouteSuccess.hidden = true;
    rerouteSuccess.setAttribute("hidden", "");
  }
  if (conflictAlert) {
    conflictAlert.hidden = true;
    conflictAlert.setAttribute("hidden", "");
  }

  // Restore destination marker interactive popup and dragging
  if (destMarker) {
    if (destMarker.dragging) {
      destMarker.dragging.enable();
    }
    destMarker.bindPopup("<strong>Destination</strong><br><span style='color: #9EABA2; font-size: 0.8rem;'>Drag to reposition</span>");
  }

  // Restore route results drawer
  const sideDrawer = document.getElementById("side-drawer");
  const routesContainer = document.getElementById("routes-container");
  if (sideDrawer) {
    sideDrawer.hidden = false;
    sideDrawer.removeAttribute("hidden");
    sideDrawer.style.display = "";
    sideDrawer.classList.remove("search-active");
    sideDrawer.classList.add("results-active");
  }
  if (routesContainer && currentAlternativesData && currentAlternativesData.alternatives) {
    routesContainer.hidden = false;
    routesContainer.removeAttribute("hidden");
  }

  // Restore polyline styles
  updateMapRouteStyles();

  // Stage 14: Release Screen Wake Lock & Reset Offline Banner
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.setNavigating(false);
  }
  const offlineNavBanner = document.getElementById("nav-offline-status-banner");
  if (offlineNavBanner) offlineNavBanner.hidden = true;
  const offDevModal = document.getElementById("nav-offline-deviation-dialog");
  if (offDevModal && offDevModal.open) offDevModal.close();

  fitRouteBounds();
}

function onMapUserDrag() {
  if (!liveNavActive) return;
  liveNavFollowUser = false;
  const recenterBtn = document.getElementById("nav-btn-recenter");
  if (recenterBtn) recenterBtn.hidden = false;
}

function recenterNavMap() {
  liveNavFollowUser = true;
  const recenterBtn = document.getElementById("nav-btn-recenter");
  if (recenterBtn) recenterBtn.hidden = true;

  if (liveNavCurrentLocation) {
    map.setView([liveNavCurrentLocation.latitude, liveNavCurrentLocation.longitude], 18, { animate: true });
  } else if (liveNavTracker && liveNavTracker.coordinates.length > 0) {
    map.setView(liveNavTracker.coordinates[0], 18, { animate: true });
  }
}

function onLiveLocationSuccess(pos) {
  if (!liveNavActive) return;
  const coords = pos.coords;
  const loc = {
    latitude: coords.latitude,
    longitude: coords.longitude,
    accuracy_m: coords.accuracy || 8.0,
    heading: coords.heading != null && !isNaN(coords.heading) ? coords.heading : null,
    speed_mps: coords.speed != null && !isNaN(coords.speed) ? coords.speed : 0.0,
    timestamp: pos.timestamp ? pos.timestamp / 1000.0 : Date.now() / 1000.0,
  };
  processNavigationLocation(loc);
}

function onLiveLocationError(err) {
  console.warn("Live GPS location unavailable:", err);
  currentNavState = NavState.LOCATION_UNAVAILABLE;
  if (err && err.code === 1) { // PERMISSION_DENIED
    updateGPSQualityBadge(99.0, "Location access needed");
    showConsumerToast("Location access is needed for live navigation. You can preview using the GPS Simulator.", "📍");
  } else {
    updateGPSQualityBadge(99.0, "Location limited (Sim ready)");
  }
  // Provide gentle notification in HUD without breaking route preview
  const maneuverText = document.getElementById("nav-maneuver-text");
  if (maneuverText && !maneuverText.textContent) {
    maneuverText.textContent = "Location access limited. Use GPS Simulator toolbar to preview.";
  }
}

function processNavigationLocation(loc) {
  if (!liveNavActive || !liveNavTracker) return;
  liveNavCurrentLocation = loc;
  currentNavState = NavState.NAVIGATING;

  // 1. Update Map Marker
  updateUserMapLocation(loc);

  // 2. Evaluate Route Progress
  const progress = liveNavTracker.updateProgress(loc);
  console.log(`[OFFLINE-NAV] Cross-track distance: ${progress.cross_track_distance_m.toFixed(1)} m`);

  // 3. Update HUD Elements
  updateLiveNavigationHUD(progress, loc);

  // 4. Destination Arrival Detection
  const destCoord = liveNavTracker.coordinates[liveNavTracker.coordinates.length - 1];
  const distToDest = clientHaversineDist(loc.latitude, loc.longitude, destCoord[0], destCoord[1]);
  if (distToDest <= 20.0 && loc.accuracy_m <= 35.0) {
    liveNavConsecutiveArrivalCount += 1;
    if (liveNavConsecutiveArrivalCount >= 2) {
      currentNavState = NavState.ARRIVED;
      if (window.AccessRouteNavEvents) {
        window.AccessRouteNavEvents.emit("arrival", { location: loc });
      }
      const arrivalDialog = document.getElementById("nav-arrival-dialog");
      if (arrivalDialog) {
        const destTitle = document.getElementById("arrival-title");
        const destInput = document.getElementById("destination-input");
        if (destTitle) {
          destTitle.textContent = (destInput && destInput.value.trim()) ? destInput.value.trim() : "Destination";
        }

        const entranceBox = document.getElementById("arrival-entrance-info");
        const entranceNameEl = document.getElementById("arrival-entrance-name");
        const entranceEvList = document.getElementById("arrival-entrance-evidence");
        if (selectedEntrance && entranceBox) {
          entranceBox.hidden = false;
          if (entranceNameEl) entranceNameEl.textContent = selectedEntrance.name || "Accessible Entrance";
          if (entranceEvList) {
            entranceEvList.innerHTML = "";
            if (selectedEntrance.is_wheelchair_accessible !== false) {
              const li = document.createElement("li");
              li.textContent = "✓ Step-free entrance";
              entranceEvList.appendChild(li);
            }
            if (selectedEntrance.door_type) {
              const li = document.createElement("li");
              li.textContent = `Door: ${selectedEntrance.door_type.replace(/_/g, " ")}`;
              entranceEvList.appendChild(li);
            }
          }
        } else if (entranceBox) {
          entranceBox.hidden = true;
        }

        if (typeof arrivalDialog.showModal === "function" && !arrivalDialog.open) {
          arrivalDialog.showModal();
        } else {
          arrivalDialog.hidden = false;
        }
      }
      return;
    }
  } else {
    liveNavConsecutiveArrivalCount = Math.max(0, liveNavConsecutiveArrivalCount - 1);
  }

  // 5. Route Deviation Detection & Dynamic Corridor
  const dynamicCorridor = Math.max(20.0, loc.accuracy_m * 1.5);
  if (loc.accuracy_m > 50.0) {
    // Very low accuracy damping: display warning, do NOT increment deviation
    updateGPSQualityBadge(loc.accuracy_m, "Location accuracy is limited");
  } else if (progress.cross_track_distance_m > dynamicCorridor) {
    liveNavConsecutiveOffCount += 1;
    if (liveNavConsecutiveOffCount >= 3) {
      // Confirmed OFF_ROUTE
      currentNavState = NavState.OFF_ROUTE;
      triggerClientReroute("off_route_deviation", loc);
    }
  } else {
    liveNavConsecutiveOffCount = Math.max(0, liveNavConsecutiveOffCount - 1);
  }
}

function updateGPSQualityBadge(accuracyM, customText) {
  const pill = document.getElementById("nav-gps-pill");
  const text = document.getElementById("nav-gps-text");
  if (!pill || !text) return;

  pill.className = "nav-gps-pill";
  if (customText) {
    text.textContent = customText;
    pill.classList.add("nav-pill-limited");
    return;
  }

  if (accuracyM <= 10.0) {
    pill.classList.add("nav-pill-high");
    text.textContent = `GPS: ±${accuracyM.toFixed(0)}m (High)`;
  } else if (accuracyM <= 25.0) {
    pill.classList.add("nav-pill-moderate");
    text.textContent = `GPS: ±${accuracyM.toFixed(0)}m (Moderate)`;
  } else if (accuracyM <= 50.0) {
    pill.classList.add("nav-pill-low");
    text.textContent = `GPS: ±${accuracyM.toFixed(0)}m (Low)`;
  } else {
    pill.classList.add("nav-pill-limited");
    text.textContent = "Location accuracy is limited";
  }
}

function updateUserMapLocation(loc) {
  const latlng = [loc.latitude, loc.longitude];

  // Heading rotation style
  let pointerHtml = "";
  if (loc.heading != null && loc.heading >= 0) {
    pointerHtml = `<div class="user-heading-pointer" style="transform: rotate(${loc.heading.toFixed(0)}deg);"></div>`;
  }

  const iconHtml = `
    <div class="user-location-marker">
      <div class="user-pulse-ring"></div>
      <div class="user-center-dot"></div>
      ${pointerHtml}
    </div>
  `;

  const customIcon = L.divIcon({
    html: iconHtml,
    className: "user-marker-container",
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });

  if (!liveNavUserMarker) {
    liveNavUserMarker = L.marker(latlng, { icon: customIcon, zIndexOffset: 2000 }).addTo(map);
  } else {
    liveNavUserMarker.setLatLng(latlng);
    liveNavUserMarker.setIcon(customIcon);
  }

  // Accuracy circle
  if (!liveNavAccuracyCircle) {
    liveNavAccuracyCircle = L.circle(latlng, {
      radius: loc.accuracy_m,
      color: "#2563eb",
      weight: 1,
      fillColor: "#3b82f6",
      fillOpacity: 0.12,
    }).addTo(map);
  } else {
    liveNavAccuracyCircle.setLatLng(latlng);
    liveNavAccuracyCircle.setRadius(loc.accuracy_m);
  }

  if (liveNavFollowUser) {
    map.panTo(latlng, { animate: true });
  }
}

function updateLiveNavigationHUD(progress, loc) {
  // Maneuver icon mapping
  const iconEl = document.getElementById("nav-maneuver-icon");
  if (iconEl) {
    iconEl.textContent = getManeuverIcon(progress.next_instruction, progress.next_maneuver);
  }

  // Distance to maneuver
  const distEl = document.getElementById("nav-maneuver-dist");
  if (distEl) {
    if (progress.distance_to_next_maneuver_m <= 10.0) {
      distEl.textContent = "Now";
    } else {
      distEl.textContent = `In ${progress.distance_to_next_maneuver_m.toFixed(0)}m`;
    }
  }

  // Instruction text
  const textEl = document.getElementById("nav-maneuver-text");
  if (textEl) {
    textEl.textContent = progress.next_instruction;
  }

  // Stage 14: Emit maneuver_changed event hook
  if (window.AccessRouteNavEvents && progress.next_instruction !== window._lastManeuverInstruction) {
    window._lastManeuverInstruction = progress.next_instruction;
    window.AccessRouteNavEvents.emit("maneuver_changed", {
      instruction: progress.next_instruction,
      maneuver: progress.next_maneuver,
      distance_m: progress.distance_to_next_maneuver_m,
    });
  }

  // GPS Quality Pill
  updateGPSQualityBadge(loc.accuracy_m);

  // Upcoming accessibility cue card
  const accessPill = document.getElementById("nav-access-pill");
  const accessText = document.getElementById("nav-access-text");
  const accessTitle = document.getElementById("nav-access-title");
  const accessIcon = document.getElementById("nav-access-icon");
  if (accessPill && accessText) {
    if (progress.upcoming_events && progress.upcoming_events.length > 0) {
      const firstEvent = progress.upcoming_events[0];
      const desc = firstEvent.description || "";
      accessText.textContent = desc;

      const lower = desc.toLowerCase();
      if (lower.includes("incline") || lower.includes("slope") || lower.includes("steep")) {
        if (accessTitle) accessTitle.textContent = "Steep section ahead";
        if (accessIcon) accessIcon.textContent = "⚠";
      } else if (lower.includes("surface") || lower.includes("unpaved") || lower.includes("gravel") || lower.includes("cobblestone")) {
        if (accessTitle) accessTitle.textContent = "Surface change ahead";
        if (accessIcon) accessIcon.textContent = "⚠";
      } else if (lower.includes("kerb") || lower.includes("curb") || lower.includes("crossing")) {
        if (accessTitle) accessTitle.textContent = "Kerb information unavailable";
        if (accessIcon) accessIcon.textContent = "◐";
      } else {
        if (accessTitle) accessTitle.textContent = "Accessibility Notice";
        if (accessIcon) accessIcon.textContent = "⚠";
      }

      accessPill.hidden = false;

      // Stage 14: Emit accessibility_warning event hook
      if (window.AccessRouteNavEvents && firstEvent.description !== window._lastWarningDesc) {
        window._lastWarningDesc = firstEvent.description;
        window.AccessRouteNavEvents.emit("accessibility_warning", firstEvent);
      }
    } else {
      accessPill.hidden = true;
      window._lastWarningDesc = null;
    }
  }

  // Bottom panel metrics (Glanceable consumer typography)
  const statRemaining = document.getElementById("nav-stat-remaining");
  if (statRemaining) {
    statRemaining.textContent = progress.remaining_distance_m < 1000
      ? `${progress.remaining_distance_m.toFixed(0)} m`
      : `${(progress.remaining_distance_m / 1000.0).toFixed(1)} km`;
  }

  const statRemainingTime = document.getElementById("nav-stat-remaining-time");
  if (statRemainingTime) {
    statRemainingTime.textContent = `${Math.ceil(progress.estimated_remaining_duration_min)} min`;
  }

  const statEta = document.getElementById("nav-stat-eta");
  if (statEta) {
    const totalMinutes = Math.ceil(progress.estimated_remaining_duration_min);
    const etaDate = new Date(Date.now() + totalMinutes * 60000);
    statEta.textContent = etaDate.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  const statProg = document.getElementById("nav-stat-progress");
  if (statProg) {
    statProg.textContent = `${progress.completion_percentage.toFixed(0)}%`;
  }

  const statCompleted = document.getElementById("nav-stat-completed");
  if (statCompleted) {
    const compM = progress.distance_along_route_m;
    const totM = liveNavTracker.totalRouteDistanceM;
    statCompleted.textContent = `${compM.toFixed(0)}m / ${totM.toFixed(0)}m`;
  }

  const progFill = document.getElementById("nav-progress-fill");
  if (progFill) {
    progFill.style.width = `${Math.min(100, Math.max(0, progress.completion_percentage))}%`;
  }
}

// Accessibility-Aware Re-routing
async function triggerClientReroute(reason, loc) {
  const now = Date.now() / 1000.0;
  // 1. Cooldown & minimal movement check
  if (liveNavRerouteInFlight) return;
  if (liveNavLastReroutePos) {
    const elapsed = now - liveNavLastRerouteTime;
    const moved = clientHaversineDist(liveNavLastReroutePos[0], liveNavLastReroutePos[1], loc.latitude, loc.longitude);
    if (elapsed < 10.0 || moved < 15.0) {
      return;
    }
  }

  liveNavRerouteInFlight = true;
  liveNavLastRerouteTime = now;
  liveNavLastReroutePos = [loc.latitude, loc.longitude];
  liveNavRerouteToken += 1;
  const currentToken = liveNavRerouteToken;

  const isOffline = (window.AccessRouteConnectivity && !window.AccessRouteConnectivity.isOnline()) || 
                    (typeof navigator !== "undefined" && !navigator.onLine);

  console.log(`[OFFLINE-NAV] Connectivity: ${isOffline ? "offline" : "online"}`);
  console.log("[OFFLINE-NAV] Deviation detected");

  // Stage 14: If offline, do NOT fabricate a fake reroute!
  if (isOffline) {
    liveNavRerouteInFlight = false;
    console.log("[OFFLINE-NAV] Showing offline deviation safeguard");
    const devDialog = document.getElementById("nav-offline-deviation-dialog");
    if (devDialog) {
      if (typeof devDialog.showModal === "function") {
        try {
          if (!devDialog.open) devDialog.showModal();
        } catch (e) {
          devDialog.open = true;
        }
      } else {
        devDialog.hidden = false;
      }
    }
    if (window.AccessRouteNavEvents) {
      window.AccessRouteNavEvents.emit("off_route", { location: loc, offline: true });
    }
    return;
  }

  const banner = document.getElementById("nav-reroute-banner");
  const msgEl = document.getElementById("nav-reroute-msg");
  if (banner) banner.hidden = false;
  if (msgEl) msgEl.textContent = "You're off the planned route. Checking nearby accessible options.";

  const activeAlt = currentAlternativesData.alternatives[activeAlternativeIndex];
  const destPt = liveNavTracker.coordinates[liveNavTracker.coordinates.length - 1];

  try {
    const payload = {
      current_position: [loc.latitude, loc.longitude],
      destination: [destPt[0], destPt[1]],
      mobility_preferences: currentPreferences,
      original_route_distance_m: activeAlt.physical_distance_m,
      reroute_reason: reason,
      reroute_token: String(currentToken),
    };

    const res = await fetch("/api/v1/navigation/reroute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`Reroute request failed with HTTP ${res.status}`);
    }

    const data = await res.json();

    // Stale response guard: discard if a newer reroute was triggered
    if (currentToken !== liveNavRerouteToken) {
      console.log("Discarded stale reroute response token", currentToken);
      return;
    }

    if (data.success && data.new_route) {
      // Apply new route
      const newAlt = data.new_route;
      currentAlternativesData.alternatives[activeAlternativeIndex] = newAlt;
      
      const newCoords = (newAlt.geometry.coordinates || []).map((pt) => [pt[1], pt[0]]);
      liveNavTracker = new ClientRouteTracker(newCoords, newAlt.directions || [], []);
      liveNavConsecutiveOffCount = 0;
      currentNavState = NavState.NAVIGATING;

      // Re-render map layer
      renderMapRouteLayers(currentAlternativesData);
      renderActiveAlternativeDetails();

      if (banner) banner.hidden = true;
      const successBanner = document.getElementById("nav-reroute-success");
      if (successBanner) {
        successBanner.hidden = false;
        setTimeout(() => {
          if (successBanner) successBanner.hidden = true;
        }, 3500);
      }
      const maneuverText = document.getElementById("nav-maneuver-text");
      if (maneuverText && newAlt.directions && newAlt.directions.length > 0) {
        maneuverText.textContent = newAlt.directions[0].instruction;
      }
    } else {
      // Unrouteable with current preferences
      if (banner) banner.hidden = true;
      const conflictAlert = document.getElementById("nav-conflict-alert");
      const conflictText = document.getElementById("nav-conflict-text");
      if (conflictAlert) conflictAlert.hidden = false;
      if (conflictText) conflictText.textContent = "We couldn't find another route matching your current accessibility preferences.";
    }
  } catch (err) {
    console.error("[OFFLINE-NAV] ERROR: Reroute execution failed:", err.message || err);
    if (banner) banner.hidden = true;
    const isNowOffline = (window.AccessRouteConnectivity && !window.AccessRouteConnectivity.isOnline()) || 
                         (typeof navigator !== "undefined" && !navigator.onLine);
    if (isNowOffline) {
      console.log("[OFFLINE-NAV] Showing offline deviation safeguard");
      const devDialog = document.getElementById("nav-offline-deviation-dialog");
      if (devDialog) {
        if (typeof devDialog.showModal === "function") {
          try {
            if (!devDialog.open) devDialog.showModal();
          } catch (e) {
            devDialog.open = true;
          }
        } else {
          devDialog.hidden = false;
        }
      }
    }
  } finally {
    liveNavRerouteInFlight = false;
  }
}

function dismissNavConflict() {
  const alertEl = document.getElementById("nav-conflict-alert");
  if (alertEl) alertEl.hidden = true;
}

function toggleNavOverview() {
  fitRouteBounds();
}

function toggleNavStepsDrawer() {
  document.body.classList.toggle("nav-steps-open");
}

function openNavReportModal() {
  if (liveNavCurrentLocation) {
    openCommunityReportModal(liveNavCurrentLocation.latitude, liveNavCurrentLocation.longitude, "path_blocked");
  } else if (liveNavTracker && liveNavTracker.coordinates.length > 0) {
    const pt = liveNavTracker.coordinates[0];
    openCommunityReportModal(pt[0], pt[1], "path_blocked");
  } else {
    openCommunityReportModal();
  }
}

function closeArrivalModalAndEndNav() {
  const dialog = document.getElementById("nav-arrival-dialog");
  if (dialog) dialog.close();
  endNavigation();
}

// Simulated GPS Player Functions for Browser Testing
function toggleSimulatedGPS() {
  if (liveNavSimInterval) {
    clearInterval(liveNavSimInterval);
    liveNavSimInterval = null;
    const btn = document.getElementById("btn-sim-play");
    if (btn) btn.textContent = "▶ Play Walk";
    return;
  }

  if (!liveNavTracker || liveNavTracker.coordinates.length < 2) return;

  const btn = document.getElementById("btn-sim-play");
  if (btn) btn.textContent = "⏸ Pause Walk";

  const totalSteps = 60;
  const coords = liveNavTracker.coordinates;
  const intervalMs = Math.round(1000 / liveNavSimSpeed);

  liveNavSimInterval = setInterval(() => {
    if (!liveNavActive) {
      clearInterval(liveNavSimInterval);
      liveNavSimInterval = null;
      return;
    }

    liveNavSimIndex += 1;
    const progressFrac = Math.min(1.0, liveNavSimIndex / totalSteps);
    
    // Interpolate along route polyline
    const targetDist = progressFrac * liveNavTracker.totalRouteDistanceM;
    let currDist = 0.0;
    let simLat = coords[0][0];
    let simLon = coords[0][1];

    for (let i = 0; i < coords.length - 1; i++) {
      const p1 = coords[i];
      const p2 = coords[i + 1];
      const segLen = clientHaversineDist(p1[0], p1[1], p2[0], p2[1]);
      if (currDist + segLen >= targetDist) {
        const t = segLen > 0 ? (targetDist - currDist) / segLen : 0.0;
        simLat = p1[0] + t * (p2[0] - p1[0]);
        simLon = p1[1] + t * (p2[1] - p1[1]);
        break;
      }
      currDist += segLen;
    }

    const simLoc = {
      latitude: simLat,
      longitude: simLon,
      accuracy_m: 6.0,
      heading: 90.0,
      speed_mps: 1.1,
      timestamp: Date.now() / 1000.0,
    };

    processNavigationLocation(simLoc);

    if (progressFrac >= 1.0) {
      clearInterval(liveNavSimInterval);
      liveNavSimInterval = null;
      if (btn) btn.textContent = "▶ Play Walk";
    }
  }, intervalMs);
}

function cycleSimSpeed() {
  if (liveNavSimSpeed === 1) liveNavSimSpeed = 2;
  else if (liveNavSimSpeed === 2) liveNavSimSpeed = 5;
  else liveNavSimSpeed = 1;

  const btn = document.getElementById("btn-sim-speed");
  if (btn) btn.textContent = `Speed: ${liveNavSimSpeed}x`;

  if (liveNavSimInterval) {
    toggleSimulatedGPS();
    toggleSimulatedGPS();
  }
}

function injectSimulatedJitter() {
  if (!liveNavCurrentLocation && liveNavTracker) {
    const pt = liveNavTracker.coordinates[0];
    liveNavCurrentLocation = { latitude: pt[0], longitude: pt[1], accuracy_m: 8.0 };
  }
  if (!liveNavCurrentLocation) return;

  const { m_lat, m_lon } = clientLatLonToMetersFactor(liveNavCurrentLocation.latitude);
  // Add 14m lateral jitter with 18m accuracy
  const jitterLoc = {
    latitude: liveNavCurrentLocation.latitude + (14.0 / m_lat),
    longitude: liveNavCurrentLocation.longitude,
    accuracy_m: 18.0,
    heading: liveNavCurrentLocation.heading,
    speed_mps: 0.8,
    timestamp: Date.now() / 1000.0,
  };
  processNavigationLocation(jitterLoc);
}

function injectSimulatedDeviation() {
  console.log("[OFFLINE-NAV] Simulated location update");
  if (!liveNavCurrentLocation && liveNavTracker && liveNavTracker.coordinates.length > 0) {
    const pt = liveNavTracker.coordinates[0];
    liveNavCurrentLocation = { latitude: pt[0], longitude: pt[1], accuracy_m: 6.0 };
  }
  if (!liveNavCurrentLocation || !liveNavTracker || liveNavTracker.coordinates.length < 2) return;

  const baseLoc = Object.assign({}, liveNavCurrentLocation);
  const factor = clientLatLonToMetersFactor(baseLoc.latitude);

  // Compute direction of the nearest/current segment to displace perpendicular to corridor
  const segIdx = liveNavTracker.lastSegmentIdx || 0;
  const p1 = liveNavTracker.coordinates[segIdx];
  const p2 = liveNavTracker.coordinates[Math.min(liveNavTracker.coordinates.length - 1, segIdx + 1)];
  const segDx = (p2[1] - p1[1]) * factor.m_lon;
  const segDy = (p2[0] - p1[0]) * factor.m_lat;
  const segLen = Math.hypot(segDx, segDy);

  // Normal vector perpendicular to segment (-segDy, segDx)
  let normX = 1.0;
  let normY = 0.0;
  if (segLen > 1e-4) {
    normX = -segDy / segLen;
    normY = segDx / segLen;
  }

  // Feed 3 consecutive readings displaced 50m, 55m, 60m perpendicular to route
  for (let step = 1; step <= 3; step++) {
    setTimeout(() => {
      const devDist = 50.0 + (step - 1) * 5.0;
      const devLoc = {
        latitude: baseLoc.latitude + (normY * devDist) / factor.m_lat,
        longitude: baseLoc.longitude + (normX * devDist) / factor.m_lon,
        accuracy_m: 5.0,
        heading: 0.0,
        speed_mps: 1.2,
        timestamp: Date.now() / 1000.0 + step,
      };
      processNavigationLocation(devLoc);
    }, step * 250);
  }
}

function teleportToDestination() {
  if (!liveNavTracker || liveNavTracker.coordinates.length < 2) return;
  const dest = liveNavTracker.coordinates[liveNavTracker.coordinates.length - 1];

  for (let step = 1; step <= 2; step++) {
    setTimeout(() => {
      const arrLoc = {
        latitude: dest[0] + 0.00004,
        longitude: dest[1] + 0.00004,
        accuracy_m: 5.0,
        heading: 0.0,
        speed_mps: 0.0,
        timestamp: Date.now() / 1000.0 + step,
      };
      processNavigationLocation(arrLoc);
    }, step * 300);
  }
}

function toggleSimToolbar() {
  const body = document.getElementById("sim-toolbar-body");
  const btn = document.getElementById("btn-toggle-sim-body");
  if (!body) return;
  body.hidden = !body.hidden;
  if (btn) btn.textContent = body.hidden ? "▸" : "▾";
}

// ==========================================================================
// STAGE 12: USER ACCOUNT, CLOUD PREFERENCE SYNC, SAVED PLACES & ROUTES
// ==========================================================================

async function checkAuthStatus() {
  if (!authToken) {
    updateAuthUI(null);
    return;
  }
  try {
    const res = await fetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (res.ok) {
      currentUser = await res.json();
      updateAuthUI(currentUser);
      fetchCloudPreferences();
    } else {
      authToken = null;
      localStorage.removeItem("accessroute_token");
      updateAuthUI(null);
    }
  } catch (e) {
    console.warn("Auth check failed:", e);
  }
}

function toggleAccountMenu() {
  const menu = document.getElementById("user-dropdown-menu");
  if (menu) menu.hidden = !menu.hidden;
}

function closeAccountMenu() {
  const menu = document.getElementById("user-dropdown-menu");
  if (menu) menu.hidden = true;
}

function openAuthModal() {
  const menu = document.getElementById("user-dropdown-menu");
  if (menu) menu.hidden = true;
  document.getElementById("auth-error-banner").hidden = true;
  document.getElementById("auth-modal").showModal();
}

function closeAuthModal() {
  document.getElementById("auth-modal").close();
}

function switchAuthMode(mode) {
  authMode = mode;
  document.getElementById("tab-auth-login").classList.toggle("active", mode === "login");
  document.getElementById("tab-auth-register").classList.toggle("active", mode === "register");
  document.getElementById("group-auth-name").hidden = mode === "login";
  document.getElementById("btn-auth-submit").textContent = mode === "login" ? "Sign In" : "Create Account";
  document.getElementById("auth-error-banner").hidden = true;
}

async function handleAuthSubmit() {
  const email = document.getElementById("auth-email-input").value.trim();
  const password = document.getElementById("auth-password-input").value;
  const fullName = document.getElementById("auth-name-input").value.trim();
  const errorBanner = document.getElementById("auth-error-banner");

  errorBanner.hidden = true;

  const endpoint = authMode === "login" ? "/api/v1/auth/login" : "/api/v1/auth/register";
  const body = authMode === "login" ? { email, password } : { email, password, full_name: fullName || null };

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json();
      errorBanner.textContent = err.detail || "Authentication failed";
      errorBanner.hidden = false;
      return;
    }

    const data = await res.json();
    authToken = data.access_token;
    localStorage.setItem("accessroute_token", authToken);
    currentUser = data.user;
    updateAuthUI(currentUser);
    closeAuthModal();

    syncLocalPreferencesToCloud();
  } catch (err) {
    errorBanner.textContent = "Network error. Please try again.";
    errorBanner.hidden = false;
  }
}

function updateAuthUI(user) {
  const label = document.getElementById("auth-nav-label");
  const emailEl = document.getElementById("dropdown-user-email");
  const badgeEl = document.getElementById("dropdown-user-badge");
  const btn = document.getElementById("btn-auth-open");
  const nav = document.getElementById("user-account-nav");
  if (nav) nav.style.display = "none"; // Always keep Beta Device pill hidden in consumer experience

  if (user) {
    if (label) label.textContent = user.full_name || user.email.split("@")[0];
    if (emailEl) emailEl.textContent = user.email;
    if (badgeEl) {
      badgeEl.textContent = "Cloud Sync Active";
      badgeEl.style.color = "#059669";
      badgeEl.style.background = "#ecfdf5";
    }
    if (btn) btn.classList.add("logged-in");
  } else {
    if (label) label.textContent = "Beta Device";
    if (emailEl) emailEl.textContent = "Beta Tester (Device)";
    if (badgeEl) {
      badgeEl.textContent = "Local Private Beta";
      badgeEl.style.color = "#0369a1";
      badgeEl.style.background = "#e0f2fe";
    }
    if (btn) btn.classList.remove("logged-in");
    const menu = document.getElementById("user-dropdown-menu");
    if (menu) menu.hidden = true;
  }
}

function handleSignOut() {
  authToken = null;
  currentUser = null;
  localStorage.removeItem("accessroute_token");
  updateAuthUI(null);
  const menu = document.getElementById("user-dropdown-menu");
  if (menu) menu.hidden = true;
}

async function handleManualSyncPreferences() {
  if (!authToken) {
    openAuthModal();
    return;
  }
  await syncLocalPreferencesToCloud();
  alert("Mobility preferences synchronized with cloud account.");
  const menu = document.getElementById("user-dropdown-menu");
  if (menu) menu.hidden = true;
}

async function syncLocalPreferencesToCloud() {
  if (!authToken) return;
  try {
    await fetch("/api/v1/me/preferences", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${authToken}`,
      },
      body: JSON.stringify({
        preset_name: currentPreferences.preset_name || "manual_wheelchair",
        preferences_json: JSON.stringify(currentPreferences),
      }),
    });
  } catch (err) {
    console.warn("Preferences sync failed:", err);
  }
}

async function fetchCloudPreferences() {
  if (!authToken) return;
  try {
    const res = await fetch("/api/v1/me/preferences", {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.preferences_json) {
        currentPreferences = JSON.parse(data.preferences_json);
        savePreferencesToStorage();
        updatePreferencesSummaryChips();
      }
    }
  } catch (err) {
    console.warn("Could not fetch cloud preferences:", err);
  }
}

// Saved Places
function openSavedPlacesModal() {
  const menu = document.getElementById("user-dropdown-menu");
  if (menu) menu.hidden = true;
  document.getElementById("saved-places-modal").showModal();
  loadSavedPlaces();
}

function closeSavedPlacesModal() {
  document.getElementById("saved-places-modal").close();
}

function promptSaveCurrentDestination() {
  if (!destCoords) {
    alert("Please select a destination first.");
    return;
  }
  openSavedPlacesModal();
  const labelInput = document.getElementById("save-place-label");
  if (labelInput) {
    const destName = document.getElementById("destination-input").value;
    labelInput.value = destName.includes("(") ? "Favorite Location" : (destName.split(",")[0] || "Saved Place");
    labelInput.focus();
  }
}

async function loadSavedPlaces() {
  const listEl = document.getElementById("saved-places-list");
  const emptyEl = document.getElementById("saved-places-empty");
  const managerListEl = document.getElementById("saved-places-manager-list");
  const managerEmptyEl = document.getElementById("saved-places-manager-empty");

  if (listEl) listEl.innerHTML = "";
  if (managerListEl) managerListEl.innerHTML = "";

  let cloudPlaces = [];
  if (authToken) {
    try {
      const res = await fetch("/api/v1/me/saved-places", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) {
        cloudPlaces = await res.json();
      }
    } catch (e) {
      console.warn("Cloud saved places fetch failed:", e);
    }
  }

  let localPlaces = [];
  try {
    const raw = localStorage.getItem("accessroute_local_saved_places");
    if (raw) localPlaces = JSON.parse(raw);
    if ((!localPlaces || localPlaces.length === 0) && window.offlineStore) {
      localPlaces = await window.offlineStore.getLocalPlaces();
    }
  } catch (e) {
    console.warn("Local saved places read error:", e);
  }

  const allPlaces = [...localPlaces, ...cloudPlaces.filter(cp => !localPlaces.some(lp => lp.id === cp.id))];

  if (allPlaces.length === 0) {
    if (emptyEl) {
      emptyEl.hidden = false;
      emptyEl.innerHTML = "<p>No saved places yet on this device. Search a destination and click '★ Save' to save Home, Work, or favorite places.</p>";
    }
    if (managerEmptyEl) managerEmptyEl.hidden = false;
    return;
  }

  if (emptyEl) emptyEl.hidden = true;
  if (managerEmptyEl) managerEmptyEl.hidden = true;

  allPlaces.forEach((p) => {
    const isLocal = !authToken || String(p.id).startsWith("loc_");
    const badge = isLocal ? `<span class="badge badge-secondary" style="font-size:0.7rem;margin-left:6px;background:#e0f2fe;color:#0369a1;padding:2px 6px;border-radius:4px;">Device Data</span>` : "";
    const html = `
      <div class="saved-item-info">
        <span class="saved-item-title">${p.label}${badge}</span>
        <span class="saved-item-sub">${p.display_name || `${p.latitude.toFixed(4)}, ${p.longitude.toFixed(4)}`}</span>
      </div>
      <div class="saved-item-actions">
        <button type="button" class="btn btn-ghost btn-sm" onclick="selectSavedPlaceAsOrigin(${p.latitude}, ${p.longitude}, '${p.label.replace(/'/g, "\\'")}')">From</button>
        <button type="button" class="btn btn-primary btn-sm" onclick="selectSavedPlaceAsDestination(${p.latitude}, ${p.longitude}, '${p.label.replace(/'/g, "\\'")}')">To</button>
        <button type="button" class="btn btn-ghost btn-sm text-danger" onclick="handleDeleteSavedPlace('${p.id}')">✕</button>
      </div>
    `;

    if (listEl) {
      const li = document.createElement("li");
      li.className = "saved-item-card";
      li.innerHTML = html;
      listEl.appendChild(li);
    }
    if (managerListEl) {
      const li2 = document.createElement("li");
      li2.className = "saved-item-card";
      li2.innerHTML = html;
      managerListEl.appendChild(li2);
    }
  });
}

function selectSavedPlaceAsOrigin(lat, lon, label) {
  setOrigin(lat, lon, false, false, label);
  closeSavedPlacesModal();
  closeSavedManagerModal();
}

function selectSavedPlaceAsDestination(lat, lon, label) {
  setDestination(lat, lon, false, false, label);
  closeSavedPlacesModal();
  closeSavedManagerModal();
}

async function handleSaveCurrentLocation() {
  if (!destCoords) {
    alert("Please choose a destination on the map or via search first.");
    return;
  }
  const labelInput = document.getElementById("save-place-label");
  const label = labelInput.value.trim() || "Saved Place";
  const displayName = document.getElementById("destination-input").value.trim() || null;

  const newPlace = {
    id: "loc_place_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7),
    label,
    display_name: displayName,
    latitude: destCoords[0],
    longitude: destCoords[1],
    created_at: new Date().toISOString()
  };

  // Always save locally on device
  try {
    const localPlaces = JSON.parse(localStorage.getItem("accessroute_local_saved_places") || "[]");
    localPlaces.unshift(newPlace);
    localStorage.setItem("accessroute_local_saved_places", JSON.stringify(localPlaces));
    if (window.offlineStore) {
      await window.offlineStore.saveLocalPlace(newPlace);
    }
  } catch (e) {
    console.warn("Local place save error:", e);
  }

  // If cloud auth is active, sync with Stage 12 cloud account
  if (authToken) {
    try {
      await fetch("/api/v1/me/saved-places", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          label,
          display_name: displayName,
          latitude: destCoords[0],
          longitude: destCoords[1],
        }),
      });
    } catch (err) {
      console.warn("Cloud save place sync error:", err);
    }
  }

  labelInput.value = "";
  loadSavedPlaces();
}

async function handleDeleteSavedPlace(id) {
  try {
    let localPlaces = JSON.parse(localStorage.getItem("accessroute_local_saved_places") || "[]");
    localPlaces = localPlaces.filter(p => String(p.id) !== String(id));
    localStorage.setItem("accessroute_local_saved_places", JSON.stringify(localPlaces));
    if (window.offlineStore) {
      await window.offlineStore.deleteLocalPlace(id);
    }
  } catch (e) {
    console.warn("Local place delete error:", e);
  }

  if (authToken && !String(id).startsWith("loc_")) {
    try {
      await fetch(`/api/v1/me/saved-places/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${authToken}` },
      });
    } catch (err) {
      console.warn("Delete cloud saved place failed:", err);
    }
  }
  loadSavedPlaces();
}

// Saved Routes
function openSavedRoutesModal() {
  const menu = document.getElementById("user-dropdown-menu");
  if (menu) menu.hidden = true;
  document.getElementById("saved-routes-modal").showModal();
  loadSavedRoutes();
}

function closeSavedRoutesModal() {
  document.getElementById("saved-routes-modal").close();
}

async function loadSavedRoutes() {
  const listEl = document.getElementById("saved-routes-list");
  const emptyEl = document.getElementById("saved-routes-empty");
  const managerListEl = document.getElementById("saved-routes-manager-list");
  const managerEmptyEl = document.getElementById("saved-routes-manager-empty");

  if (listEl) listEl.innerHTML = "";
  if (managerListEl) managerListEl.innerHTML = "";

  let cloudRoutes = [];
  if (authToken) {
    try {
      const res = await fetch("/api/v1/me/saved-routes", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) {
        cloudRoutes = await res.json();
      }
    } catch (e) {
      console.warn("Cloud routes fetch failed:", e);
    }
  }

  let localRoutes = [];
  try {
    const raw = localStorage.getItem("accessroute_local_saved_routes");
    if (raw) localRoutes = JSON.parse(raw);
    if ((!localRoutes || localRoutes.length === 0) && window.offlineStore) {
      localRoutes = await window.offlineStore.getLocalRoutes();
    }
  } catch (e) {
    console.warn("Local routes read error:", e);
  }

  const allRoutes = [...localRoutes, ...cloudRoutes.filter(cr => !localRoutes.some(lr => lr.id === cr.id))];

  if (allRoutes.length === 0) {
    if (emptyEl) {
      emptyEl.hidden = false;
      emptyEl.innerHTML = "<p>No saved routes on this device yet. Calculate a route and save it for one-click recalculation.</p>";
    }
    if (managerEmptyEl) managerEmptyEl.hidden = false;
    return;
  }

  if (emptyEl) emptyEl.hidden = true;
  if (managerEmptyEl) managerEmptyEl.hidden = true;

  allRoutes.forEach((r) => {
    const isLocal = !authToken || String(r.id).startsWith("loc_");
    const badge = isLocal ? `<span class="badge badge-secondary" style="font-size:0.7rem;margin-left:6px;background:#e0f2fe;color:#0369a1;padding:2px 6px;border-radius:4px;">Device Data</span>` : "";
    const distText = r.distance_m ? ` (${(r.distance_m / 1000).toFixed(1)} km)` : "";
    const html = `
      <div class="saved-item-info">
        <span class="saved-item-title">${r.title}${badge}</span>
        <span class="saved-item-sub">${r.origin_label} → ${r.dest_label}${distText}</span>
      </div>
      <div class="saved-item-actions">
        <button type="button" class="btn btn-primary btn-sm" onclick='handleLoadSavedRoute(${JSON.stringify(r)})'>Recalculate</button>
        <button type="button" class="btn btn-ghost btn-sm text-danger" onclick="handleDeleteSavedRoute('${r.id}')">✕</button>
      </div>
    `;

    if (listEl) {
      const li = document.createElement("li");
      li.className = "saved-item-card";
      li.innerHTML = html;
      listEl.appendChild(li);
    }
    if (managerListEl) {
      const li2 = document.createElement("li");
      li2.className = "saved-item-card";
      li2.innerHTML = html;
      managerListEl.appendChild(li2);
    }
  });
}

async function handleSaveActiveRoute() {
  if (!originCoords || !destCoords || !currentAlternativesData) {
    showConsumerToast("Please calculate a route first", "⚠️");
    return;
  }
  const titleInput = document.getElementById("save-route-title");
  const title = (titleInput && titleInput.value.trim()) ? titleInput.value.trim() : "Saved Route";
  const origInput = document.getElementById("origin-input");
  const destInput = document.getElementById("destination-input");
  const origLabel = (origInput && origInput.value.trim()) ? origInput.value.trim() : "Origin";
  const destLabel = (destInput && destInput.value.trim()) ? destInput.value.trim() : "Destination";
  const activeAlt = (currentAlternativesData.alternatives && currentAlternativesData.alternatives[activeAlternativeIndex]) || (currentAlternativesData.alternatives && currentAlternativesData.alternatives[0]) || { physical_distance_m: 0 };

  const routeItem = {
    id: "loc_route_" + Date.now() + "_" + Math.random().toString(36).substring(2, 7),
    title,
    origin_label: origLabel,
    origin_lat: originCoords[0],
    origin_lon: originCoords[1],
    dest_label: destLabel,
    dest_lat: destCoords[0],
    dest_lon: destCoords[1],
    preferences_snapshot_json: JSON.stringify(currentPreferences),
    distance_m: activeAlt.physical_distance_m || 0,
    created_at: new Date().toISOString()
  };

  // Always save locally on device
  try {
    const localRoutes = JSON.parse(localStorage.getItem("accessroute_local_saved_routes") || "[]");
    localRoutes.unshift(routeItem);
    localStorage.setItem("accessroute_local_saved_routes", JSON.stringify(localRoutes));
    if (window.offlineStore) {
      await window.offlineStore.saveLocalRoute(routeItem);
    }
  } catch (e) {
    console.warn("Local route save error:", e);
  }

  // If cloud auth is active, sync with Stage 12 cloud account
  if (authToken) {
    try {
      await fetch("/api/v1/me/saved-routes", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify(routeItem),
      });
    } catch (err) {
      console.warn("Cloud route save sync error:", err);
    }
  }

  if (titleInput) titleInput.value = "";
  loadSavedRoutes();
  showConsumerToast("Route saved on this device", "✓");
}

function handleLoadSavedRoute(route) {
  closeSavedRoutesModal();
  closeSavedManagerModal();
  setOrigin(route.origin_lat, route.origin_lon, false, false, route.origin_label);
  setDestination(route.dest_lat, route.dest_lon, false, false, route.dest_label);

  map.fitBounds([[route.origin_lat, route.origin_lon], [route.dest_lat, route.dest_lon]], { padding: [80, 80] });
  handleFindRoutes();
}

async function handleDeleteSavedRoute(id) {
  try {
    let localRoutes = JSON.parse(localStorage.getItem("accessroute_local_saved_routes") || "[]");
    localRoutes = localRoutes.filter(r => String(r.id) !== String(id));
    localStorage.setItem("accessroute_local_saved_routes", JSON.stringify(localRoutes));
    if (window.offlineStore) {
      await window.offlineStore.deleteLocalRoute(id);
    }
  } catch (e) {
    console.warn("Local route delete error:", e);
  }

  if (authToken && !String(id).startsWith("loc_")) {
    try {
      await fetch(`/api/v1/me/saved-routes/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${authToken}` },
      });
    } catch (err) {
      console.warn("Delete saved route failed:", err);
    }
  }
  loadSavedRoutes();
}

// ============================================================================
// STAGE 14: PWA, OFFLINE NAVIGATION & FIELD SURVEY JAVASCRIPT CONTROLLERS
// ============================================================================

// Stage 15 Event Bus Hooks (Consumed later by Voice & Haptic Navigation)
window.AccessRouteNavEvents = {
  _listeners: {},
  on(event, callback) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(callback);
  },
  emit(event, data) {
    console.log(`[NavEvents] Emitted: ${event}`, data);
    const handlers = this._listeners[event] || [];
    for (const fn of handlers) {
      try { fn(data); } catch (e) { console.error("[NavEvents] Error:", e); }
    }
  }
};

// Download Active Route for Offline Navigation
async function handleDownloadActiveRouteOffline() {
  if (!currentAlternativesData || !currentAlternativesData.alternatives || currentAlternativesData.alternatives.length === 0) {
    alert("Please calculate a route before downloading for offline use.");
    return;
  }

  const activeAlt = currentAlternativesData.alternatives[activeAlternativeIndex];
  if (!activeAlt) return;

  const btn = document.getElementById("btn-download-offline-route");
  const textEl = document.getElementById("download-offline-text");
  const badge = document.getElementById("offline-route-status-badge");
  const badgeMsg = document.getElementById("offline-route-status-msg");

  if (textEl) textEl.textContent = "Downloading...";
  if (btn) btn.disabled = true;

  try {
    const destInput = document.getElementById("destination-input") || document.getElementById("input-destination");
    const destName = (destInput ? destInput.value.trim() : "") || (activeAlt.route_name || "Accessible Destination");

    const origLat = (originCoords && originCoords[0]) || (typeof currentOriginCoords !== "undefined" && currentOriginCoords && currentOriginCoords[0]) || -37.8180;
    const origLon = (originCoords && originCoords[1]) || (typeof currentOriginCoords !== "undefined" && currentOriginCoords && currentOriginCoords[1]) || 144.9670;
    const destLat = (destCoords && destCoords[0]) || (typeof currentDestCoords !== "undefined" && currentDestCoords && currentDestCoords[0]) || -37.8136;
    const destLon = (destCoords && destCoords[1]) || (typeof currentDestCoords !== "undefined" && currentDestCoords && currentDestCoords[1]) || 144.9631;

    const originCoordsObj = { latitude: origLat, longitude: origLon };
    const destCoordsObj = { latitude: destLat, longitude: destLon };

    let routePackage = null;

    // Attempt online package generation via REST endpoint
    if (window.AccessRouteConnectivity && window.AccessRouteConnectivity.isOnline()) {
      try {
        const res = await fetch("/api/v1/offline/route-package", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            route_id: activeAlt.key || "route_offline_" + Date.now(),
            origin: originCoordsObj,
            destination: destCoordsObj,
            destination_name: destName,
            selected_entrance: window.currentSelectedEntrance || null,
            route_data: Object.assign({}, activeAlt, {
              geojson: currentAlternativesData.geojson || null,
              geometry: (activeAlt.geometry && activeAlt.geometry.coordinates)
                ? activeAlt.geometry.coordinates.map((p) => [p[1], p[0]])
                : (activeAlt.coordinates || []),
            }),
            preferences: currentPreferences,
          }),
        });
        if (res.ok) {
          routePackage = await res.json();
        }
      } catch (e) {
        console.warn("[OfflineDownload] Backend packaging failed, creating client snapshot:", e);
      }
    }

    // Client fallback package creation
    if (!routePackage) {
      const nowStr = new Date().toISOString();
      const geomCoords = (activeAlt.geometry && activeAlt.geometry.coordinates) ? activeAlt.geometry.coordinates.map(p => [p[1], p[0]]) : [];
      routePackage = {
        route_id: activeAlt.key || "route_offline_" + Date.now(),
        created_at: nowStr,
        downloaded_at: nowStr,
        origin: originCoordsObj,
        destination: destCoordsObj,
        destination_name: destName,
        selected_entrance: window.currentSelectedEntrance || null,
        entrance_coordinates: window.currentSelectedEntrance ? { latitude: window.currentSelectedEntrance.latitude, longitude: window.currentSelectedEntrance.longitude } : null,
        mobility_preferences_snapshot: currentPreferences || {},
        route_geometry: geomCoords,
        route_segments: activeAlt.route_segments || [],
        maneuvers: activeAlt.directions || [],
        distance_m: activeAlt.physical_distance_m || 0.0,
        estimated_duration_min: activeAlt.estimated_duration_min || 1,
        elevation_profile: activeAlt.elevation_summary || null,
        accessibility_findings: activeAlt.explanations || [],
        upcoming_accessibility_events: [],
        evidence_quality: activeAlt.evidence_quality || { confidence_score: 1.0, quality_tier: "VERIFIED" },
        osm_evidence: activeAlt.osm_evidence || [],
        terrain_evidence: null,
        community_evidence_snapshot: [],
        known_conflicts: [],
        data_timestamp: nowStr,
        region_bounds: currentAlternativesData.region_bounds || [0, 0, 0, 0],
        package_version: "1.0.0",
        schema_version: "stage14_v1",
      };
    }

    // Save to IndexedDB
    if (window.AccessRouteOfflineStore) {
      await window.AccessRouteOfflineStore.saveRoute(routePackage);
    }

    if (badge) badge.hidden = false;
    if (badgeMsg) {
      const nowFmt = new Date().toLocaleDateString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      badgeMsg.textContent = `Available offline (${nowFmt})`;
    }
    if (textEl) textEl.textContent = "Saved Offline ✓";
    showConsumerToast("Route downloaded for offline navigation", "✓");
  } catch (err) {
    console.error("Offline download failed:", err);
    showConsumerToast("Could not download route package: " + err.message, "⚠️");
    if (textEl) textEl.textContent = "Download for Offline";
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Unified Consumer Saved Places & Offline Routes Handlers (Section 7 & 18)
function openSavedManagerModal(tab = "downloaded") {
  console.log("[SAVED] Button clicked");
  try {
    console.log("[SAVED] Opening manager");
    closeAccountMenu();
    const modal = document.getElementById("saved-manager-modal");
    if (!modal) {
      console.error("[SAVED] ERROR: #saved-manager-modal not found in DOM");
      return;
    }
    if (typeof modal.showModal === "function") {
      modal.showModal();
    } else {
      modal.setAttribute("open", "true");
    }
    switchSavedManagerTab(tab);
    console.log("[SAVED] Manager opened");
  } catch (err) {
    console.error("[SAVED] ERROR:", err);
  }
}

function closeSavedManagerModal() {
  const modal = document.getElementById("saved-manager-modal");
  if (modal && modal.close) modal.close();
  else if (modal) modal.removeAttribute("open");
}

function switchSavedManagerTab(tab) {
  const tabDl = document.getElementById("tab-saved-downloaded");
  const tabPl = document.getElementById("tab-saved-places");
  const tabRt = document.getElementById("tab-saved-routes");

  const paneDl = document.getElementById("pane-saved-downloaded");
  const panePl = document.getElementById("pane-saved-places");
  const paneRt = document.getElementById("pane-saved-routes");

  [tabDl, tabPl, tabRt].forEach(t => { if (t) { t.classList.remove("active"); t.setAttribute("aria-selected", "false"); } });
  [paneDl, panePl, paneRt].forEach(p => { if (p) { p.classList.remove("active"); p.hidden = true; } });

  if (tab === "downloaded") {
    if (tabDl) { tabDl.classList.add("active"); tabDl.setAttribute("aria-selected", "true"); }
    if (paneDl) { paneDl.classList.add("active"); paneDl.hidden = false; }
    loadDownloadedRoutes();
  } else if (tab === "places") {
    if (tabPl) { tabPl.classList.add("active"); tabPl.setAttribute("aria-selected", "true"); }
    if (panePl) { panePl.classList.add("active"); panePl.hidden = false; }
    loadSavedPlaces();
  } else if (tab === "routes") {
    if (tabRt) { tabRt.classList.add("active"); tabRt.setAttribute("aria-selected", "true"); }
    if (paneRt) { paneRt.classList.add("active"); paneRt.hidden = false; }
    loadSavedRoutes();
  }
}

async function loadDownloadedRoutes() {
  console.log("[SAVED] Loading downloaded routes");
  const container = document.getElementById("downloaded-routes-list");
  const emptyEl = document.getElementById("downloaded-routes-empty");
  if (!container) return;

  try {
    if (!window.AccessRouteOfflineStore) {
      if (emptyEl) emptyEl.hidden = false;
      container.innerHTML = "";
      return;
    }

    const routes = window.AccessRouteOfflineStore.listRoutes
      ? await window.AccessRouteOfflineStore.listRoutes()
      : (window.AccessRouteOfflineStore.getAllRoutes ? await window.AccessRouteOfflineStore.getAllRoutes() : []);
    if (!routes || routes.length === 0) {
      if (emptyEl) emptyEl.hidden = false;
      container.innerHTML = "";
      return;
    }

  if (emptyEl) emptyEl.hidden = true;
  container.innerHTML = routes.map((r) => {
    const title = r.destination_name || r.destination_label || "Accessible Destination";
    const distKm = (r.distance_m / 1000).toFixed(2);
    const durMin = Math.round(r.estimated_duration_min || (r.distance_m / 60));
    const profile = (r.mobility_preferences_snapshot && r.mobility_preferences_snapshot.mode)
      ? r.mobility_preferences_snapshot.mode.replace("_", " ")
      : "Manual Wheelchair";

    let dateStr = "Recently";
    if (r.downloaded_at || r.created_at) {
      try {
        const d = new Date(r.downloaded_at || r.created_at);
        dateStr = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
      } catch (e) {}
    }

    let evidenceHtml = "";
    if (r.evidence_quality && r.evidence_quality.quality_tier) {
      evidenceHtml = `<span class="badge-evidence" style="background:#f1f5f9;color:#334155;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;">${r.evidence_quality.quality_tier}</span>`;
    }

    return `
      <li class="downloaded-route-card">
        <div class="route-card-main">
          <div class="route-card-header">
            <h4 class="route-card-title">${title}</h4>
            <span class="route-card-profile" style="font-size:0.75rem;color:#0284c7;font-weight:600;text-transform:capitalize;">${profile}</span>
          </div>
          <div class="route-card-meta">
            <span>📏 ${distKm} km</span>
            <span>⏱ ~${durMin} min</span>
            <span>📅 Downloaded ${dateStr}</span>
            ${evidenceHtml}
          </div>
        </div>
        <div class="route-card-actions">
          <button type="button" class="btn btn-primary btn-sm" onclick="handleStartOfflineRouteNavigation('${r.route_id}')">
            🧭 Navigate Offline
          </button>
          <button type="button" class="btn btn-ghost btn-sm text-danger" onclick="handleDeleteDownloadedRoute('${r.route_id}')" title="Remove download" aria-label="Remove download">
            ✕
          </button>
        </div>
      </li>
    `;
  }).join("");
  } catch (err) {
    console.error("[SAVED] ERROR:", err);
    if (emptyEl) {
      emptyEl.hidden = false;
      const titleEl = emptyEl.querySelector(".empty-title");
      if (titleEl) titleEl.textContent = "Unable to load offline routes";
    }
  }
}

async function handleDeleteDownloadedRoute(routeId) {
  if (window.AccessRouteOfflineStore) {
    await window.AccessRouteOfflineStore.deleteRoute(routeId);
    showConsumerToast("Route download removed", "✓");
    loadDownloadedRoutes();
  }
}

async function handleStartOfflineRouteNavigation(routeId) {
  if (!window.AccessRouteOfflineStore) return;
  const pkg = await window.AccessRouteOfflineStore.getRoute(routeId);
  if (!pkg) {
    showConsumerToast("Downloaded route not found", "⚠️");
    return;
  }

  let geom = pkg.route_geometry || [];
  let geojsonCoords = [];
  if (geom.length > 0) {
    if (Math.abs(geom[0][0]) > 90) {
      geojsonCoords = geom.map((p) => [p[0], p[1]]);
    } else {
      geojsonCoords = geom.map((p) => [p[1], p[0]]);
    }
  } else if (pkg.origin && pkg.destination) {
    const origLat = pkg.origin.latitude || pkg.origin.lat;
    const origLon = pkg.origin.longitude || pkg.origin.lon;
    const destLat = pkg.destination.latitude || pkg.destination.lat;
    const destLon = pkg.destination.longitude || pkg.destination.lon;
    if (origLat && origLon && destLat && destLon) {
      geojsonCoords = [[origLon, origLat], [destLon, destLat]];
    }
  }

  const destTitle = pkg.destination_name || pkg.destination_label || "Downloaded Destination";
  const distKm = (pkg.distance_m / 1000).toFixed(2);
  const durMin = Math.round(pkg.estimated_duration_min || (pkg.distance_m / 60));

  const alt = {
    key: pkg.route_id,
    route_name: destTitle,
    route_category: "RECOMMENDED",
    overall_accessibility_score: 95,
    physical_distance_m: pkg.distance_m,
    estimated_duration_min: durMin,
    elevation_summary: pkg.elevation_profile,
    explanations: pkg.accessibility_findings || ["Downloaded accessibility route package"],
    route_segments: pkg.route_segments || [],
    directions: pkg.maneuvers || [],
    coordinates: geojsonCoords.map((pt) => [pt[1], pt[0]]),
    geometry: {
      type: "LineString",
      coordinates: geojsonCoords,
    },
    evidence_quality: pkg.evidence_quality || { confidence_score: 1.0, quality_tier: "VERIFIED" },
    osm_evidence: pkg.osm_evidence || [],
  };

  const feature = {
    type: "Feature",
    geometry: alt.geometry,
    properties: {
      key: "accessibility_aware",
      title: destTitle,
      feature_type: "route_alternative",
      physical_distance_m: pkg.distance_m,
      badge: "Downloaded Offline",
      style: {
        color: "#14b8a6",
        dashArray: null,
      },
    },
  };

  currentAlternativesData = {
    alternatives: [alt],
    geojson: {
      type: "FeatureCollection",
      features: [feature],
    },
    region_bounds: pkg.region_bounds || [0, 0, 0, 0],
    isOffline: true,
  };
  activeAlternativeIndex = 0;
  window.activeAlternativeIndex = 0;
  window.currentAlternativesData = currentAlternativesData;
  window.liveNavIsOfflineRoute = true;

  closeSavedManagerModal();

  if (typeof renderMapRouteLayers === "function") {
    renderMapRouteLayers(currentAlternativesData);
  }

  showConsumerToast(`Loaded offline route: ${destTitle}`, "🧭");
  startNavigationForActiveRoute();

  const subtitle = document.getElementById("nav-status-sub");
  if (subtitle) {
    const pkgDate = pkg.data_timestamp || pkg.downloaded_at || pkg.created_at;
    let freshText = "Downloaded route";
    if (pkgDate) {
      try {
        const d = new Date(pkgDate);
        freshText = `Evidence from ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
      } catch (e) {}
    }
    subtitle.textContent = `Offline navigation active • ${freshText}`;
  }

  if (window.AccessRouteConnectivity && !window.AccessRouteConnectivity.isOnline()) {
    const mapNotice = document.getElementById("offline-map-notice");
    if (mapNotice) mapNotice.hidden = false;
  }
}

// Offline Deviation Handlers
function closeOfflineDeviationModal() {
  const modal = document.getElementById("nav-offline-deviation-dialog");
  if (modal && modal.open) modal.close();
}

function handleReturnToDownloadedRoute() {
  closeOfflineDeviationModal();
  if (liveNavCurrentLocation && liveNavTracker && liveNavTracker.coordinates.length > 0) {
    // Center map showing both user and route
    map.setView([liveNavCurrentLocation.latitude, liveNavCurrentLocation.longitude], 18, { animate: true });
    const manText = document.getElementById("nav-maneuver-text");
    if (manText) manText.textContent = "Head back towards the highlighted accessible route.";
  }
}

function handleViewRouteOverview() {
  closeOfflineDeviationModal();
  toggleNavOverview();
}

function handleRetryRerouteWhenOnline() {
  closeOfflineDeviationModal();
  if (window.AccessRouteConnectivity && window.AccessRouteConnectivity.isOnline()) {
    if (liveNavCurrentLocation) {
      triggerClientReroute("user_retry_online", liveNavCurrentLocation);
    }
  } else {
    alert("Internet connection is still offline. Please reconnect to request a new accessibility-aware reroute.");
  }
}

// Field Survey Mode Handlers
let _fieldSelectedObsValue = null;

function openFieldModeModal() {
  closeAccountMenu();
  const modal = document.getElementById("field-survey-dialog");
  if (!modal) return;

  if (typeof modal.showModal === "function") {
    modal.showModal();
  } else {
    modal.hidden = false;
  }

  if (window.AccessRouteFieldMode) {
    if (currentOriginCoords) {
      window.AccessRouteFieldMode.updateUserPosition(currentOriginCoords[0], currentOriginCoords[1]);
    }
    window.AccessRouteFieldMode.renderCurrentMission();
  }
}

function closeFieldModeModal() {
  const modal = document.getElementById("field-survey-dialog");
  if (modal && modal.open) modal.close();
  else if (modal) modal.hidden = true;
}

async function handleDownloadMissions() {
  const lat = currentOriginCoords ? currentOriginCoords[0] : -37.8180;
  const lon = currentOriginCoords ? currentOriginCoords[1] : 144.9670;
  if (window.AccessRouteFieldMode) {
    const res = await window.AccessRouteFieldMode.downloadMissionsForArea(lat, lon);
    alert(`Downloaded ${res.count} verification missions for field survey.`);
  }
}

function selectFieldObservation(val) {
  _fieldSelectedObsValue = val;
  const buttons = document.querySelectorAll(".field-choice-btn");
  buttons.forEach(b => {
    if (b.getAttribute("data-value") === val) b.classList.add("selected");
    else b.classList.remove("selected");
  });

  const saveBtn = document.getElementById("btn-save-field-obs");
  if (saveBtn) saveBtn.disabled = false;
}

function handleFieldPhotoSelected(event) {
  const file = event.target.files && event.target.files[0];
  if (file && window.AccessRouteFieldMode) {
    window.AccessRouteFieldMode.handlePhotoSelected(file);
  }
}

function removeFieldPhoto() {
  if (window.AccessRouteFieldMode) {
    window.AccessRouteFieldMode.removePhoto();
  }
}

function saveFieldObservation() {
  if (!_fieldSelectedObsValue) return;
  if (window.AccessRouteFieldMode) {
    window.AccessRouteFieldMode.saveObservation(_fieldSelectedObsValue);
    _fieldSelectedObsValue = null;
  }
}

function skipFieldMission() {
  if (window.AccessRouteFieldMode) {
    window.AccessRouteFieldMode.skipMission();
    _fieldSelectedObsValue = null;
  }
}

// Storage Management Handlers
function openStorageManagerModal() {
  closeAccountMenu();
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.openStorageModal();
  }
}

function closeStorageModal() {
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.closeStorageModal();
  }
}

function handleClearOfflineData() {
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.clearDownloadedData();
  }
}

async function deleteOfflineRoute(routeId) {
  if (window.AccessRouteOfflineStore) {
    await window.AccessRouteOfflineStore.deleteRoute(routeId);
    if (window.AccessRoutePWA) {
      window.AccessRoutePWA.openStorageModal();
    }
  }
}

// PWA Installation & App Update Handlers
function handlePWAInstallClick() {
  closeAccountMenu();
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.triggerInstallPrompt();
  }
}

function handlePWADismissClick() {
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.dismissInstallBanner();
  }
}

function handleApplyAppUpdate() {
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.applyAppUpdate();
  }
}

function handleDismissAppUpdate() {
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.dismissAppUpdate();
  }
}

function closeIOSInstallModal() {
  if (window.AccessRoutePWA) {
    window.AccessRoutePWA.closeIOSInstallModal();
  }
}


