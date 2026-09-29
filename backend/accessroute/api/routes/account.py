"""Account endpoints for synchronized mobility preferences, saved places, and saved routes."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from accessroute.auth.dependencies import get_current_user
from accessroute.auth.schemas import (
    SavedPlaceCreate,
    SavedPlaceResponse,
    SavedRouteCreate,
    SavedRouteResponse,
    UserPreferencesResponse,
    UserPreferencesSync,
    UserProfile,
)
from accessroute.auth.service import AccountService
from accessroute.database.models import User
from accessroute.database.session import get_db

router = APIRouter(prefix="/me", tags=["account"])


@router.get("", response_model=UserProfile)
def get_me(current_user: User = Depends(get_current_user)):
    """Return profile of the current authenticated user."""
    return UserProfile.model_validate(current_user)


# ---------------------------------------------------------
# Synchronized Mobility Preferences
# ---------------------------------------------------------

@router.get("/preferences", response_model=UserPreferencesResponse)
def get_preferences(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetch user's cloud mobility preferences."""
    pref = AccountService.get_user_preferences(db, current_user.id)
    if not pref:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No cloud mobility preferences found for this account",
        )
    return UserPreferencesResponse.model_validate(pref)


@router.put("/preferences", response_model=UserPreferencesResponse)
def sync_preferences(
    req: UserPreferencesSync,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save or update user's cloud mobility preferences."""
    pref = AccountService.sync_user_preferences(db, current_user.id, req)
    return UserPreferencesResponse.model_validate(pref)


# ---------------------------------------------------------
# Saved Places
# ---------------------------------------------------------

@router.get("/saved-places", response_model=List[SavedPlaceResponse])
def list_saved_places(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List private saved places (Home, Work, etc.) for the authenticated user."""
    places = AccountService.list_saved_places(db, current_user.id)
    return [SavedPlaceResponse.model_validate(p) for p in places]


@router.post("/saved-places", response_model=SavedPlaceResponse, status_code=status.HTTP_201_CREATED)
def create_saved_place(
    req: SavedPlaceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a private place for the authenticated user."""
    place = AccountService.create_saved_place(db, current_user.id, req)
    return SavedPlaceResponse.model_validate(place)


@router.delete("/saved-places/{place_id}")
def delete_saved_place(
    place_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a saved place belonging to the user."""
    AccountService.delete_saved_place(db, current_user.id, place_id)
    return {"ok": True, "deleted_id": place_id}


# ---------------------------------------------------------
# Saved Routes
# ---------------------------------------------------------

@router.get("/saved-routes", response_model=List[SavedRouteResponse])
def list_saved_routes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List saved route templates for the authenticated user."""
    routes = AccountService.list_saved_routes(db, current_user.id)
    return [SavedRouteResponse.model_validate(r) for r in routes]


@router.post("/saved-routes", response_model=SavedRouteResponse, status_code=status.HTTP_201_CREATED)
def create_saved_route(
    req: SavedRouteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a route template with origin, destination, and preferences."""
    route = AccountService.create_saved_route(db, current_user.id, req)
    return SavedRouteResponse.model_validate(route)


@router.delete("/saved-routes/{route_id}")
def delete_saved_route(
    route_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a saved route belonging to the user."""
    AccountService.delete_saved_route(db, current_user.id, route_id)
    return {"ok": True, "deleted_id": route_id}
