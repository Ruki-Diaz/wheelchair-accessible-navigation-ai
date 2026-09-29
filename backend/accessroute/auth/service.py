"""User account, saved places, saved routes, and preference sync service."""

from datetime import datetime, timezone
import json
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from accessroute.auth.schemas import (
    SavedPlaceCreate,
    SavedRouteCreate,
    UserLogin,
    UserPreferencesSync,
    UserRegister,
)
from accessroute.auth.security import hash_password, verify_password
from accessroute.database.models import (
    SavedPlace,
    SavedRoute,
    User,
    UserPreferencesModel,
)


class AccountService:
    """Encapsulates business logic for user accounts and synchronized data."""

    @staticmethod
    def register_user(db: Session, req: UserRegister) -> User:
        """Register a new user account with hashed password."""
        email = req.email.strip().lower()
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists",
            )

        hashed = hash_password(req.password)
        user = User(
            email=email,
            hashed_password=hashed,
            full_name=req.full_name.strip() if req.full_name else None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate_user(db: Session, req: UserLogin) -> User:
        """Authenticate user by email and password."""
        email = req.email.strip().lower()
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(req.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )
        return user

    @staticmethod
    def get_user_preferences(db: Session, user_id: str) -> Optional[UserPreferencesModel]:
        """Fetch saved cloud preferences for a user."""
        return db.query(UserPreferencesModel).filter(UserPreferencesModel.user_id == user_id).first()

    @staticmethod
    def sync_user_preferences(db: Session, user_id: str, req: UserPreferencesSync) -> UserPreferencesModel:
        """Synchronize mobility preferences using deterministic timestamp/version resolution."""
        # Validate that preferences_json is valid JSON
        try:
            json.loads(req.preferences_json)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="preferences_json must be valid JSON",
            )

        pref = db.query(UserPreferencesModel).filter(UserPreferencesModel.user_id == user_id).first()
        now = datetime.now(timezone.utc)
        if pref:
            pref.preset_name = req.preset_name
            pref.preferences_json = req.preferences_json
            pref.version = (pref.version or 1) + 1
            pref.updated_at = now
        else:
            pref = UserPreferencesModel(
                user_id=user_id,
                preset_name=req.preset_name,
                preferences_json=req.preferences_json,
                version=1,
                updated_at=now,
            )
            db.add(pref)

        db.commit()
        db.refresh(pref)
        return pref

    @staticmethod
    def list_saved_places(db: Session, user_id: str) -> List[SavedPlace]:
        """List all saved places for the authenticated user, ordered by label."""
        return (
            db.query(SavedPlace)
            .filter(SavedPlace.user_id == user_id)
            .order_by(SavedPlace.label.asc())
            .all()
        )

    @staticmethod
    def create_saved_place(db: Session, user_id: str, req: SavedPlaceCreate) -> SavedPlace:
        """Save a new place for the authenticated user."""
        place = SavedPlace(
            user_id=user_id,
            label=req.label.strip(),
            display_name=req.display_name.strip() if req.display_name else None,
            latitude=req.latitude,
            longitude=req.longitude,
            place_type=req.place_type,
            preferred_entrance_id=req.preferred_entrance_id,
            preferred_entrance_name=req.preferred_entrance_name,
        )
        db.add(place)
        db.commit()
        db.refresh(place)
        return place

    @staticmethod
    def update_saved_place_preferred_entrance(
        db: Session,
        user_id: str,
        place_id: str,
        entrance_id: Optional[str],
        entrance_name: Optional[str],
    ) -> Optional[SavedPlace]:
        """Update preferred entrance for a saved place."""
        place = (
            db.query(SavedPlace)
            .filter(SavedPlace.id == place_id, SavedPlace.user_id == user_id)
            .first()
        )
        if not place:
            return None
        place.preferred_entrance_id = entrance_id
        place.preferred_entrance_name = entrance_name
        place.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(place)
        return place

    @staticmethod
    def delete_saved_place(db: Session, user_id: str, place_id: str) -> bool:
        """Delete a saved place belonging to the user."""
        place = (
            db.query(SavedPlace)
            .filter(SavedPlace.id == place_id, SavedPlace.user_id == user_id)
            .first()
        )
        if not place:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Saved place not found or unauthorized",
            )
        db.delete(place)
        db.commit()
        return True

    @staticmethod
    def list_saved_routes(db: Session, user_id: str) -> List[SavedRoute]:
        """List all saved routes for the authenticated user."""
        return (
            db.query(SavedRoute)
            .filter(SavedRoute.user_id == user_id)
            .order_by(SavedRoute.created_at.desc())
            .all()
        )

    @staticmethod
    def create_saved_route(db: Session, user_id: str, req: SavedRouteCreate) -> SavedRoute:
        """Save a route template with origin, destination, and preference snapshot."""
        route = SavedRoute(
            user_id=user_id,
            title=req.title.strip(),
            origin_label=req.origin_label.strip(),
            origin_lat=req.origin_lat,
            origin_lon=req.origin_lon,
            dest_label=req.dest_label.strip(),
            dest_lat=req.dest_lat,
            dest_lon=req.dest_lon,
            preferences_snapshot_json=req.preferences_snapshot_json,
            distance_m=req.distance_m,
        )
        db.add(route)
        db.commit()
        db.refresh(route)
        return route

    @staticmethod
    def delete_saved_route(db: Session, user_id: str, route_id: str) -> bool:
        """Delete a saved route belonging to the user."""
        route = (
            db.query(SavedRoute)
            .filter(SavedRoute.id == route_id, SavedRoute.user_id == user_id)
            .first()
        )
        if not route:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Saved route not found or unauthorized",
            )
        db.delete(route)
        db.commit()
        return True
