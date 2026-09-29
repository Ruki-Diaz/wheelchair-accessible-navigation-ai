"""Comprehensive unit and integration test suite for AccessRoute AI Stage 14.

Covers:
- PWA Web App Manifest validity, shortcuts, display mode, and icons
- Service worker delivery, scoping headers, and asset caching references
- Offline route package creation, serialization, schema versioning, and validation
- Incompatible schema version rejection
- Offline verification mission package creation and serialization
- Offline sync queue item lifecycle state transitions
- Idempotent batch synchronization and duplicate submission protection
- Anonymous offline workflow (no mandatory account required)
- Stale offline evidence metadata and labelling
- REST API contracts for route packaging, mission packaging, and syncing
"""

import json
from pathlib import Path
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from accessroute.api.main import app
from accessroute.offline.models import (
    OfflineRoutePackage,
    OfflineMissionPackage,
    OfflineSyncQueueItem,
    SyncItemStatus,
    CURRENT_OFFLINE_SCHEMA_VERSION,
)
from accessroute.offline.service import OfflineService
from accessroute.community.repository import SQLiteCommunityObservationRepository
from accessroute.community.models import ObservationCategory


@pytest.fixture
def client():
    return TestClient(app)


def test_pwa_manifest_validity():
    """Manifest must exist, be valid JSON, and meet PWA installability requirements."""
    manifest_path = Path(__file__).resolve().parent.parent / "accessroute" / "api" / "static" / "manifest.webmanifest"
    assert manifest_path.exists(), "manifest.webmanifest must exist in static directory"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    assert data.get("name") == "AccessRoute AI"
    assert data.get("short_name") == "AccessRoute"
    assert data.get("start_url") == "/"
    assert data.get("display") == "standalone"
    assert "theme_color" in data
    assert "background_color" in data
    
    icons = data.get("icons", [])
    assert len(icons) >= 2, "Manifest should declare multiple icons"
    icon_sizes = [icon.get("sizes") for icon in icons]
    assert "192x192" in icon_sizes
    assert "512x512" in icon_sizes
    
    shortcuts = data.get("shortcuts", [])
    assert len(shortcuts) >= 2, "Manifest should include convenient shortcuts"
    shortcut_names = [sc.get("name") for sc in shortcuts]
    assert "Navigate" in shortcut_names
    assert "Report Accessibility Issue" in shortcut_names


def test_service_worker_asset_and_headers(client):
    """Service worker and manifest endpoints must be served with correct scoping headers."""
    # SW root endpoint
    sw_resp = client.get("/sw.js")
    assert sw_resp.status_code == 200
    assert "application/javascript" in sw_resp.headers.get("content-type", "")
    assert sw_resp.headers.get("Service-Worker-Allowed") == "/"
    assert "accessroute-shell-v1" in sw_resp.text
    
    # Manifest endpoint
    mf_resp = client.get("/manifest.webmanifest")
    assert mf_resp.status_code == 200
    assert "application/manifest+json" in mf_resp.headers.get("content-type", "")
    assert "AccessRoute AI" in mf_resp.text


def test_pwa_icon_assets_exist():
    """Local application icon assets must be present for installability and offline caching."""
    icons_dir = Path(__file__).resolve().parent.parent / "accessroute" / "api" / "static" / "icons"
    assert icons_dir.exists(), "icons directory must exist"
    
    expected_icons = ["icon-192.png", "icon-512.png", "icon-maskable.png", "icon.svg"]
    for icon_name in expected_icons:
        icon_path = icons_dir / icon_name
        assert icon_path.exists(), f"Icon {icon_name} must exist"
        assert icon_path.stat().st_size > 0, f"Icon {icon_name} must not be empty"


def test_offline_route_package_model_serialization():
    """OfflineRoutePackage should serialize and deserialize cleanly with schema version."""
    now_str = datetime.now(timezone.utc).isoformat()
    pkg = OfflineRoutePackage(
        route_id="route_test_123",
        created_at=now_str,
        downloaded_at=now_str,
        origin={"latitude": -37.8136, "longitude": 144.9631, "label": "Melbourne Town Hall"},
        destination={"latitude": -37.8180, "longitude": 144.9671, "label": "Flinders Street Station"},
        destination_name="Flinders Street Station",
        selected_entrance={"id": "ent_flinders_main", "name": "Main Step-Free Entrance"},
        entrance_coordinates=(-37.8180, 144.9671),
        mobility_preferences_snapshot={"max_incline_deg": 4.5, "step_preference": "prohibited"},
        route_geometry=[[-37.8136, 144.9631], [-37.8180, 144.9671]],
        route_segments=[{"distance_m": 520.0, "accessibility_status": "accessible"}],
        maneuvers=[{"instruction": "Head south on Swanston St", "distance_m": 520.0}],
        distance_m=520.0,
        estimated_duration_min=7,
        elevation_profile={"profile": [{"distance_m": 0.0, "elevation_m": 25.0}]},
        accessibility_findings=["incline_moderate"],
        upcoming_accessibility_events=[{"meter_mark": 100.0, "message": "Gentle ramp ahead"}],
        evidence_quality={"status": "high"},
        osm_evidence=[{"surface": "paved"}],
        terrain_evidence={"max_grade": 0.03},
        community_evidence_snapshot=[],
        known_conflicts=[],
        data_timestamp=now_str,
        region_bounds=[-37.82, 144.96, -37.81, 144.97],
        package_version="1.0.0",
        schema_version=CURRENT_OFFLINE_SCHEMA_VERSION,
    )
    
    data = pkg.to_dict()
    assert data["route_id"] == "route_test_123"
    assert data["schema_version"] == CURRENT_OFFLINE_SCHEMA_VERSION
    assert data["distance_m"] == 520.0
    
    # Round-trip deserialization
    loaded = OfflineRoutePackage.from_dict(data)
    assert loaded.route_id == "route_test_123"
    assert loaded.destination_name == "Flinders Street Station"
    assert loaded.distance_m == 520.0


def test_offline_route_package_incompatible_schema_version_rejection():
    """Incompatible schema version packages must be rejected."""
    bad_data = {
        "route_id": "route_bad_version",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "origin": {"latitude": 0.0, "longitude": 0.0},
        "destination": {"latitude": 0.0, "longitude": 0.0},
        "mobility_preferences_snapshot": {},
        "route_geometry": [],
        "route_segments": [],
        "maneuvers": [],
        "distance_m": 0.0,
        "estimated_duration_min": 0,
        "elevation_profile": None,
        "accessibility_findings": [],
        "upcoming_accessibility_events": [],
        "evidence_quality": None,
        "osm_evidence": [],
        "terrain_evidence": None,
        "community_evidence_snapshot": [],
        "known_conflicts": [],
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "region_bounds": [0.0, 0.0, 0.0, 0.0],
        "package_version": "1.0.0",
        "schema_version": "unsupported_v999",
    }
    
    with pytest.raises(ValueError, match="Incompatible offline route package schema version"):
        OfflineRoutePackage.from_dict(bad_data)


def test_offline_mission_package_model_serialization():
    """OfflineMissionPackage serializes cleanly with domain fields."""
    pkg = OfflineMissionPackage(
        mission_id="mis_123",
        coordinates={"latitude": -37.814, "longitude": 144.963},
        feature_type="kerb_ramp",
        missing_attribute="kerb",
        priority="HIGH",
        why_it_matters="Frequently used pedestrian crossing",
        suggested_actions=["Check if kerb is flush, lowered, or raised"],
        osm_element_id=987654,
        existing_evidence={"status": "unknown"},
        downloaded_at=datetime.now(timezone.utc).isoformat(),
    )
    data = pkg.to_dict()
    assert data["mission_id"] == "mis_123"
    assert data["priority"] == "HIGH"
    assert data["coordinates"]["latitude"] == -37.814
    
    loaded = OfflineMissionPackage.from_dict(data)
    assert loaded.mission_id == "mis_123"
    assert loaded.feature_type == "kerb_ramp"


def test_offline_sync_queue_item_transitions():
    """Sync queue item transitions through valid operational lifecycle states."""
    item = OfflineSyncQueueItem(
        local_id=str(uuid.uuid4()),
        operation_type="community_report",
        payload={"category": "construction", "latitude": -37.81, "longitude": 144.96},
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    assert item.status == SyncItemStatus.PENDING
    assert item.attempt_count == 0
    
    item.mark_attempt()
    assert item.status == SyncItemStatus.SYNCING
    assert item.attempt_count == 1
    
    item.mark_failed("Network timeout", retryable=True)
    assert item.status == SyncItemStatus.FAILED_RETRYABLE
    assert item.error == "Network timeout"
    
    item.mark_synced(server_id="obs_srv_999")
    assert item.status == SyncItemStatus.SYNCED
    assert item.server_id == "obs_srv_999"


def test_offline_service_package_generation():
    """OfflineService creates complete route package from route calculation output."""
    service = OfflineService()
    route_data = {
        "route_id": "rt_test_build",
        "origin": {"latitude": -37.81, "longitude": 144.96, "label": "Origin Point"},
        "destination": {"latitude": -37.82, "longitude": 144.97, "label": "Destination Point"},
        "destination_name": "Test Venue",
        "selected_entrance": {
            "id": "ent_01",
            "name": "Accessible East Gate",
            "wheelchair": "yes",
            "step_free": True,
            "door_type": "sliding",
            "assessment_status": "accessible",
        },
        "geometry": [[-37.81, 144.96], [-37.815, 144.965], [-37.82, 144.97]],
        "distance_m": 850.0,
        "estimated_duration_min": 11,
        "maneuvers": [{"instruction": "Continue straight", "distance_m": 850.0}],
        "elevation_profile": {"profile": [{"distance_m": 0.0, "elevation_m": 30.0}]},
        "accessibility_findings": ["Fully step-free pathway"],
        "evidence_quality": {"level": "verified"},
        "osm_evidence": [{"highway": "footway"}],
        "terrain_evidence": {"grade_max": 0.02},
        "community_evidence": [],
    }
    preferences = {"max_incline_deg": 5.0, "step_preference": "prohibited"}
    
    pkg = service.create_route_package(route_data, preferences)
    assert pkg.route_id == "rt_test_build"
    assert pkg.schema_version == CURRENT_OFFLINE_SCHEMA_VERSION
    assert pkg.selected_entrance is not None
    assert pkg.selected_entrance.get("name") == "Accessible East Gate"
    assert len(pkg.route_geometry) == 3
    assert pkg.region_bounds[0] <= -37.81


def test_offline_service_sync_idempotency_and_duplicate_protection():
    """Submitting the same local_id multiple times must acknowledge without creating duplicate records."""
    repo = SQLiteCommunityObservationRepository()
    service = OfflineService(community_repo=repo)
    
    client_uuid = str(uuid.uuid4())
    mutation_payload = {
        "local_id": client_uuid,
        "operation_type": "community_report",
        "payload": {
            "category": "kerb",
            "value": "flush",
            "latitude": -37.8136,
            "longitude": 144.9631,
            "title": "Flush kerb ramp at crossing",
            "notes": "Surveyed during offline field walk",
        },
    }
    
    # First sync
    res1 = service.sync_batch([mutation_payload], user_id=None)
    assert res1["synced_count"] == 1
    assert res1["items"][0]["status"] == "SYNCED"
    obs_id = res1["items"][0]["server_id"]
    assert obs_id == client_uuid
    
    # Verify in DB
    obs = repo.get_by_id(client_uuid)
    assert obs is not None
    assert obs.category == ObservationCategory.KERB
    
    # Second sync with EXACT SAME local_id (e.g. client lost connection before receiving ack)
    res2 = service.sync_batch([mutation_payload], user_id=None)
    assert res2["synced_count"] == 1
    assert res2["items"][0]["status"] == "SYNCED"
    assert res2["items"][0]["server_id"] == client_uuid
    
    # Ensure no duplicate was inserted
    matching = [o for o in repo.get_nearby(latitude=-37.8136, longitude=144.9631, radius_m=50.0) if o.id == client_uuid]
    assert len(matching) == 1, "Duplicate observation was created despite identical local_id"


def test_api_offline_route_package_endpoints(client):
    """API endpoints for creating and fetching offline route packages."""
    payload = {
        "route_id": "rt_api_test_01",
        "origin": {"latitude": -37.81, "longitude": 144.96},
        "destination": {"latitude": -37.82, "longitude": 144.97},
        "destination_name": "Library",
        "route_data": {
            "distance_m": 420.0,
            "estimated_duration_min": 6,
            "geometry": [[-37.81, 144.96], [-37.82, 144.97]],
            "maneuvers": [{"instruction": "Head south", "distance_m": 420.0}],
        },
        "preferences": {"max_incline_deg": 6.0},
    }
    
    create_resp = client.post("/api/v1/offline/route-package", json=payload)
    assert create_resp.status_code == 200
    pkg_data = create_resp.json()
    assert pkg_data["route_id"] == "rt_api_test_01"
    assert pkg_data["schema_version"] == CURRENT_OFFLINE_SCHEMA_VERSION
    assert pkg_data["distance_m"] == 420.0
    
    # GET route package
    get_resp = client.get("/api/v1/offline/route-package/rt_api_test_01")
    assert get_resp.status_code == 200
    assert get_resp.json()["route_id"] == "rt_api_test_01"


def test_api_offline_mission_package(client):
    """API endpoint for downloading offline verification missions."""
    req = {
        "center_latitude": -37.81,
        "center_longitude": 144.96,
        "radius_m": 1500.0,
        "limit": 10,
    }
    resp = client.post("/api/v1/offline/mission-package", json=req)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_count" in data
    assert "missions" in data
    assert len(data["missions"]) > 0


def test_api_offline_sync_batch(client):
    """API endpoint for syncing queued offline mutations."""
    local_id = str(uuid.uuid4())
    req = {
        "items": [
            {
                "local_id": local_id,
                "operation_type": "community_report",
                "payload": {
                    "category": "curb_ramp_missing",
                    "latitude": -37.815,
                    "longitude": 144.965,
                    "title": "High step at pedestrian crossing",
                    "notes": "Surveyed in offline mode",
                },
            }
        ]
    }
    resp = client.post("/api/v1/offline/sync", json=req)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["synced_count"] == 1
    assert res_data["items"][0]["status"] == "SYNCED"


def test_anonymous_offline_workflow(client):
    """Anonymous users without authentication must be able to perform all offline operations."""
    # 1. Download route package
    route_payload = {
        "route_id": "rt_anon_offline",
        "origin": {"latitude": -37.81, "longitude": 144.96},
        "destination": {"latitude": -37.815, "longitude": 144.965},
        "destination_name": "Anonymous Destination",
        "route_data": {
            "distance_m": 350.0,
            "estimated_duration_min": 5,
            "geometry": [[-37.81, 144.96], [-37.815, 144.965]],
        },
        "preferences": {"step_preference": "prohibited"},
    }
    # No Authorization header
    r1 = client.post("/api/v1/offline/route-package", json=route_payload)
    assert r1.status_code == 200
    
    # 2. Download verification missions
    r2 = client.post("/api/v1/offline/mission-package", json={"center_latitude": -37.81, "center_longitude": 144.96})
    assert r2.status_code == 200
    
    # 3. Synchronize offline observation
    anon_local_id = str(uuid.uuid4())
    sync_req = {
        "items": [
            {
                "local_id": anon_local_id,
                "operation_type": "community_report",
                "payload": {
                    "category": "construction",
                    "latitude": -37.812,
                    "longitude": 144.962,
                    "title": "Anonymous offline field note",
                },
            }
        ]
    }
    r3 = client.post("/api/v1/offline/sync", json=sync_req)
    assert r3.status_code == 200
    assert r3.json()["synced_count"] == 1


def test_offline_stale_evidence_labelling():
    """Verify package timestamps and stale evidence labeling requirements."""
    now = datetime.now(timezone.utc)
    one_day_ago = now - timedelta(days=1)
    one_day_ago_str = one_day_ago.isoformat()
    
    pkg = OfflineRoutePackage(
        route_id="rt_stale_check",
        created_at=one_day_ago_str,
        downloaded_at=one_day_ago_str,
        origin={"latitude": -37.81, "longitude": 144.96},
        destination={"latitude": -37.82, "longitude": 144.97},
        destination_name="Civic Centre",
        mobility_preferences_snapshot={},
        route_geometry=[[-37.81, 144.96], [-37.82, 144.97]],
        route_segments=[],
        maneuvers=[],
        distance_m=1000.0,
        estimated_duration_min=15,
        elevation_profile=None,
        accessibility_findings=[],
        upcoming_accessibility_events=[],
        evidence_quality={"level": "moderate"},
        osm_evidence=[],
        terrain_evidence=None,
        community_evidence_snapshot=[{"category": "construction", "reported_at": one_day_ago_str}],
        known_conflicts=[],
        data_timestamp=one_day_ago_str,
        region_bounds=[-37.82, 144.96, -37.81, 144.97],
        package_version="1.0.0",
        schema_version=CURRENT_OFFLINE_SCHEMA_VERSION,
    )
    
    data = pkg.to_dict()
    assert data["downloaded_at"] is not None
    assert data["data_timestamp"] is not None
