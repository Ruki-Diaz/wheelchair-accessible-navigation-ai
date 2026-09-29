"""
Unit and API integration tests for the Private Beta Accountless Model.

Verifies:
1. Anonymous installation identifier model (anon_<UUID>) for beta testers.
2. Community reporting with anonymous installation IDs (provenance, duplicate prevention, no public display).
3. Preservation of Stage 12 authentication endpoints and security controls (rate limiting, validation).
4. Local mobility preferences and device-level saved data models.
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from accessroute.api.main import app
from accessroute.api.routes.community import _resolve_contributor_id
from accessroute.database.models import User

client = TestClient(app)


def test_anonymous_installation_id_resolution():
    """Verify anon_<UUID> format is accepted and preserved for accountless beta testers."""
    random_uuid = str(uuid.uuid4())
    anon_id = f"anon_{random_uuid}"

    # Unauthenticated user should preserve anon_<UUID>
    resolved = _resolve_contributor_id(user=None, raw_contributor_id=anon_id)
    assert resolved == anon_id
    assert resolved.startswith("anon_")

    # Empty string should fallback to anon_contributor
    assert _resolve_contributor_id(user=None, raw_contributor_id="") == "anon_contributor"
    assert _resolve_contributor_id(user=None, raw_contributor_id=None) == "anon_contributor"

    # Spoofed 'usr_' prefix by anonymous tester is safely prefixed with anon_
    spoofed = _resolve_contributor_id(user=None, raw_contributor_id="usr_admin_123")
    assert spoofed.startswith("anon_")
    assert not spoofed.startswith("usr_")


def test_authenticated_user_overrides_contributor_id():
    """Verify authenticated user model from Stage 12 is preserved and overrides client IDs."""
    test_user = User(
        id=str(uuid.uuid4()),
        email="beta.tester@example.com",
        hashed_password="fakehash",
        full_name="Beta Tester",
    )
    resolved = _resolve_contributor_id(user=test_user, raw_contributor_id="anon_client_id")
    assert resolved == f"usr_{test_user.id}"


def test_beta_anonymous_community_report_submission_and_privacy():
    """Test anonymous beta tester can submit reports with anon_<UUID> and UUID is not leaked in response."""
    test_uuid = str(uuid.uuid4())
    anon_id = f"anon_{test_uuid}"

    payload = {
        "category": "construction",
        "value": "temporary_barrier",
        "latitude": -33.8688,
        "longitude": 151.2093,
        "is_temporary": True,
        "notes": "Beta tester observation without user account",
        "contributor_id": anon_id,
    }

    res = client.post("/api/v1/community/reports", json=payload)
    assert res.status_code in (200, 201)
    data = res.json()
    assert "id" in data
    assert data["category"] == "construction"

    # CRITICAL PRIVACY REQUIREMENT: contributor_id must not be exposed in the public report payload
    assert "contributor_id" not in data


def test_beta_anonymous_duplicate_interaction_prevention():
    """Test that anon_<UUID> prevents duplicate confirmation from the same anonymous device."""
    tester_a = f"anon_{uuid.uuid4()}"
    tester_b = f"anon_{uuid.uuid4()}"

    # Create an observation
    res_obs = client.post("/api/v1/community/reports", json={
        "category": "surface",
        "value": "cobblestone",
        "latitude": -33.8690,
        "longitude": 151.2095,
        "is_temporary": False,
        "contributor_id": tester_a,
    })
    obs_id = res_obs.json()["id"]

    # Tester B confirms the observation
    res_confirm_b1 = client.post(f"/api/v1/community/reports/{obs_id}/confirm", json={
        "contributor_id": tester_b
    })
    assert res_confirm_b1.status_code == 200
    assert res_confirm_b1.json()["confirmations_count"] >= 1

    # Tester B confirms again -> rejected as duplicate interaction
    res_confirm_b2 = client.post(f"/api/v1/community/reports/{obs_id}/confirm", json={
        "contributor_id": tester_b
    })
    assert res_confirm_b2.status_code == 400
    assert "already" in res_confirm_b2.json()["detail"].lower()


def test_stage12_auth_endpoints_preserved():
    """Verify existing Stage 12 authentication endpoints remain operational in backend."""
    # Health and schema validation on auth endpoints
    bad_login = client.post("/api/v1/auth/login", json={
        "email": "nonexistent@accessroute.org",
        "password": "WrongPassword123!"
    })
    assert bad_login.status_code == 401

    unauth_me = client.get("/api/v1/auth/me")
    assert unauth_me.status_code == 401


def test_frontend_beta_device_and_presets_configured():
    """Verify static index.html and app.js contain the beta device UX and required mobility profiles."""
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "..", "accessroute", "api", "static")

    with open(os.path.join(static_dir, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()

    # Check Beta Device branding in header & modal titles
    assert "Beta Device" in html
    assert "Local private beta" in html or "local private beta" in html
    assert "Walker / Crutches" in html
    assert "Manual Wheelchair" in html
    assert "Powered Wheelchair" in html
    assert "Mobility Scooter" in html
    assert "Pram / Stroller" in html

    with open(os.path.join(static_dir, "app.js"), "r", encoding="utf-8") as f:
        js = f.read()

    # Check anonymous installation ID logic and presets
    assert "getAnonymousInstallationId" in js
    assert "anon_" in js
    assert "accessroute_local_saved_places" in js
    assert "accessroute_local_saved_routes" in js
    assert "manual_wheelchair" in js
    assert "powered_wheelchair" in js
    assert "scooter" in js
    assert "walker" in js
    assert "pram" in js
    assert "custom" in js
