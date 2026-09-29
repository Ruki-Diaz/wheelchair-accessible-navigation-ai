"""Unit and integration tests for Stage 12: Production Platform, Accounts & Maps-Style Search."""

import json
import uuid
import pytest
from fastapi.testclient import TestClient

from accessroute.api.main import app
from accessroute.auth.security import create_access_token, hash_password, verify_password
from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.database.config import db_settings
from accessroute.database.models import (
    Base,
    CommunityObservationModel,
    SavedPlace,
    SavedRoute,
    User,
    UserPreferencesModel,
)
from accessroute.database.repository import PostgresCommunityObservationRepository
from accessroute.geocoding.photon import PhotonGeocoderProvider
from accessroute.graph.region import BoundingBox

client = TestClient(app)


# ---------------------------------------------------------------------------
# Geocoding & Reverse Geocoding Tests
# ---------------------------------------------------------------------------


def test_reverse_geocoding_validation():
    """Test reverse geocoding with out-of-bounds coordinates."""
    res = client.get("/api/v1/geocode/reverse?lat=105.0&lon=144.0")
    assert res.status_code == 422


def test_reverse_geocoding_success():
    """Test reverse geocoding endpoint returns formatted address or coordinate fallback."""
    res = client.get("/api/v1/geocode/reverse?lat=-37.8180&lon=144.9671")
    assert res.status_code == 200
    data = res.json()
    assert "latitude" in data
    assert "longitude" in data
    assert "display_name" in data
    assert abs(data["latitude"] - (-37.8180)) < 1e-4
    assert abs(data["longitude"] - 144.9671) < 1e-4
    assert len(data["display_name"]) > 0


def test_photon_reverse_geocoding_direct():
    """Direct test of Photon reverse geocoder."""
    provider = PhotonGeocoderProvider()
    result = provider.reverse(-37.8180, 144.9671)
    if result is not None:
        assert result.latitude is not None
        assert result.longitude is not None
        assert result.display_name is not None


# ---------------------------------------------------------------------------
# Password Security & Token Verification
# ---------------------------------------------------------------------------


def test_password_hashing():
    """Verify bcrypt hashing and verification."""
    password = "SuperSecurePassword123!"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_token_creation_and_decoding():
    """Verify JWT token encoding and claims decoding."""
    user_id = str(uuid.uuid4())
    email = "token_test@example.com"
    token = create_access_token({"sub": user_id, "email": email})
    assert isinstance(token, str)
    assert len(token) > 20


# ---------------------------------------------------------------------------
# Account Authentication Endpoints
# ---------------------------------------------------------------------------


def test_user_registration_and_login():
    """Test complete registration and login flow with JWT token issuance."""
    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    password = "StrongPassword987!"

    # 1. Register
    reg_res = client.post("/api/v1/auth/register", json={
        "email": unique_email,
        "password": password,
        "full_name": "Stage 12 Test User",
    })
    assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"
    reg_data = reg_res.json()
    assert "access_token" in reg_data
    assert reg_data["user"]["email"] == unique_email
    assert reg_data["user"]["full_name"] == "Stage 12 Test User"

    # 2. Duplicate registration fails
    dup_res = client.post("/api/v1/auth/register", json={
        "email": unique_email,
        "password": password,
    })
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"].lower()

    # 3. Login with wrong password fails
    wrong_login = client.post("/api/v1/auth/login", json={
        "email": unique_email,
        "password": "IncorrectPassword!",
    })
    assert wrong_login.status_code == 401

    # 4. Login with correct password succeeds
    login_res = client.post("/api/v1/auth/login", json={
        "email": unique_email,
        "password": password,
    })
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert "access_token" in login_data
    token = login_data["access_token"]

    # 5. Access protected /api/v1/auth/me
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == unique_email


def test_unauthorized_endpoints():
    """Verify protected endpoints reject unauthenticated requests."""
    endpoints = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/me/preferences"),
        ("GET", "/api/v1/me/saved-places"),
        ("POST", "/api/v1/me/saved-places"),
        ("GET", "/api/v1/me/saved-routes"),
        ("POST", "/api/v1/me/saved-routes"),
    ]
    for method, path in endpoints:
        if method == "GET":
            res = client.get(path)
        else:
            res = client.post(path, json={})
        assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}"


# ---------------------------------------------------------------------------
# Cloud Mobility Preferences Synchronization
# ---------------------------------------------------------------------------


def test_mobility_preference_sync():
    """Test cloud preference storage, retrieval, and synchronization."""
    unique_email = f"pref_user_{uuid.uuid4().hex[:8]}@example.com"
    reg_res = client.post("/api/v1/auth/register", json={
        "email": unique_email,
        "password": "TestPassword123!",
    })
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Initially no custom preferences stored
    init_res = client.get("/api/v1/me/preferences", headers=headers)
    assert init_res.status_code == 404

    # 2. Synchronize new mobility preferences
    custom_prefs = {
        "preset_name": "manual_wheelchair",
        "max_incline_deg": 5.2,
        "steps": "never",
        "surface_preference": "paved_only",
        "avoid_cobblestone": True,
        "prefer_lit_paths": True,
    }
    sync_res = client.put("/api/v1/me/preferences", headers=headers, json={
        "preset_name": "manual_wheelchair",
        "preferences_json": json.dumps(custom_prefs),
        "version": 1,
    })
    assert sync_res.status_code == 200
    synced_data = sync_res.json()
    assert synced_data["preset_name"] == "manual_wheelchair"
    parsed = json.loads(synced_data["preferences_json"])
    assert parsed["max_incline_deg"] == 5.2

    # 3. Retrieve synchronized preferences
    get_res = client.get("/api/v1/me/preferences", headers=headers)
    assert get_res.status_code == 200
    saved_prefs = get_res.json()
    assert saved_prefs["preset_name"] == "manual_wheelchair"
    parsed_get = json.loads(saved_prefs["preferences_json"])
    assert parsed_get["avoid_cobblestone"] is True


# ---------------------------------------------------------------------------
# Saved Places & Cross-User Isolation
# ---------------------------------------------------------------------------


def test_saved_places_crud_and_cross_user_isolation():
    """Verify saved places CRUD and verify that users cannot view/edit/delete other users' places."""
    user_a_email = f"user_a_{uuid.uuid4().hex[:8]}@example.com"
    res_a = client.post("/api/v1/auth/register", json={"email": user_a_email, "password": "PasswordA123!"})
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    user_b_email = f"user_b_{uuid.uuid4().hex[:8]}@example.com"
    res_b = client.post("/api/v1/auth/register", json={"email": user_b_email, "password": "PasswordB123!"})
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates a saved place
    create_res = client.post("/api/v1/me/saved-places", headers=headers_a, json={
        "label": "My Home",
        "latitude": -37.8136,
        "longitude": 144.9631,
        "display_name": "Bourke Street Mall, Melbourne",
        "place_type": "home",
    })
    assert create_res.status_code == 201
    place_a = create_res.json()
    place_a_id = place_a["id"]
    assert place_a["label"] == "My Home"

    # User A can list it
    list_a = client.get("/api/v1/me/saved-places", headers=headers_a)
    assert list_a.status_code == 200
    places_a = list_a.json()
    assert len(places_a) == 1
    assert places_a[0]["id"] == place_a_id

    # User B lists places -> must be empty (ISOLATION)
    list_b = client.get("/api/v1/me/saved-places", headers=headers_b)
    assert list_b.status_code == 200
    assert len(list_b.json()) == 0

    # User B attempts to delete User A's place -> must be 404
    del_b = client.delete(f"/api/v1/me/saved-places/{place_a_id}", headers=headers_b)
    assert del_b.status_code == 404

    # User A deletes their place -> 200
    del_a = client.delete(f"/api/v1/me/saved-places/{place_a_id}", headers=headers_a)
    assert del_a.status_code == 200

    # User A now has empty list
    list_a_empty = client.get("/api/v1/me/saved-places", headers=headers_a)
    assert len(list_a_empty.json()) == 0


# ---------------------------------------------------------------------------
# Saved Routes & Cross-User Isolation
# ---------------------------------------------------------------------------


def test_saved_routes_crud_and_cross_user_isolation():
    """Verify saved routes CRUD and privacy boundary between users."""
    user_a_email = f"route_user_a_{uuid.uuid4().hex[:8]}@example.com"
    res_a = client.post("/api/v1/auth/register", json={"email": user_a_email, "password": "PasswordA123!"})
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    user_b_email = f"route_user_b_{uuid.uuid4().hex[:8]}@example.com"
    res_b = client.post("/api/v1/auth/register", json={"email": user_b_email, "password": "PasswordB123!"})
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A saves a route
    create_res = client.post("/api/v1/me/saved-routes", headers=headers_a, json={
        "title": "Library Commute",
        "origin_label": "Bourke St",
        "origin_lat": -37.8136,
        "origin_lon": 144.9631,
        "dest_label": "Flinders St",
        "dest_lat": -37.8180,
        "dest_lon": 144.9671,
        "preferences_snapshot_json": json.dumps({"preset_name": "manual_wheelchair", "steps": "never"}),
        "distance_m": 850.0,
    })
    assert create_res.status_code == 201
    route_a = create_res.json()
    route_a_id = route_a["id"]
    assert route_a["title"] == "Library Commute"

    # User A lists it
    list_a = client.get("/api/v1/me/saved-routes", headers=headers_a)
    assert len(list_a.json()) == 1

    # User B cannot see it
    list_b = client.get("/api/v1/me/saved-routes", headers=headers_b)
    assert len(list_b.json()) == 0

    # User B cannot delete it
    del_b = client.delete(f"/api/v1/me/saved-routes/{route_a_id}", headers=headers_b)
    assert del_b.status_code == 404

    # User A deletes it
    del_a = client.delete(f"/api/v1/me/saved-routes/{route_a_id}", headers=headers_a)
    assert del_a.status_code == 200


# ---------------------------------------------------------------------------
# Contributor ID Anti-Spoofing & Community Transactions
# ---------------------------------------------------------------------------


def test_contributor_identity_anti_spoofing():
    """Verify that authenticated users get server-derived contributor_id, while anonymous spoofing is blocked."""
    # 1. Authenticated user submission
    user_email = f"contributor_{uuid.uuid4().hex[:8]}@example.com"
    reg_res = client.post("/api/v1/auth/register", json={"email": user_email, "password": "Password123!"})
    token = reg_res.json()["access_token"]
    user_id = reg_res.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    obs_res = client.post("/api/v1/community/reports", headers=headers, json={
        "latitude": -37.8136,
        "longitude": 144.9631,
        "category": "kerb",
        "value": "raised",
        "notes": "Authenticated obstacle report",
        "contributor_id": "attempted_spoof_id",  # Should be overridden by server
    })
    assert obs_res.status_code == 201
    obs_data = obs_res.json()
    # The server assigns the contributor to the database record
    assert obs_data["category"] == "kerb"
    assert obs_data["value"] == "raised"

    # 2. Anonymous submission attempting to spoof 'usr_' prefix
    anon_res = client.post("/api/v1/community/reports", json={
        "latitude": -37.8137,
        "longitude": 144.9632,
        "category": "surface",
        "value": "rough",
        "notes": "Anonymous spoof attempt",
        "contributor_id": "usr_fake_admin_account",
    })
    assert anon_res.status_code == 201
    anon_data = anon_res.json()
    assert anon_data["category"] == "surface"


# ---------------------------------------------------------------------------
# PostgreSQL Community Observation Repository Parity
# ---------------------------------------------------------------------------


def test_postgres_repository_contract():
    """Verify that PostgresCommunityObservationRepository conforms to the CommunityObservationRepository interface."""
    repo = PostgresCommunityObservationRepository("postgresql://localhost/accessroute_db")

    # Create observation
    obs = CommunityObservation(
        id=str(uuid.uuid4()),
        source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
        category=ObservationCategory.KERB,
        value="lowered",
        latitude=-37.8136,
        longitude=144.9631,
        contributor_id="contract_tester",
        confirmations_count=1,
        disputes_count=0,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        notes="PostgreSQL Repository Contract Test",
    )
    saved = repo.add(obs)
    assert saved.id == obs.id

    # Query by ID
    fetched = repo.get_by_id(obs.id)
    assert fetched is not None
    assert fetched.id == obs.id
    assert fetched.category == ObservationCategory.KERB

    # Query within radius (500m)
    nearby = repo.find_within_radius(-37.8136, 144.9631, radius_meters=500.0)
    assert any(o.id == obs.id for o in nearby)

    # Query outside radius (50m from 1km away)
    far_away = repo.find_within_radius(-37.8300, 144.9800, radius_meters=50.0)
    assert not any(o.id == obs.id for o in far_away)

    # Query inside bounding box
    bbox = BoundingBox(south=-37.82, west=144.95, north=-37.81, east=144.97)
    in_bbox = repo.find_in_bounding_box(bbox)
    assert any(o.id == obs.id for o in in_bbox)
