"""SQLAlchemy ORM models for production database platform.

Covers accounts, synchronized user mobility preferences, saved places,
saved routes, community observations, interactions, verification events,
and evidence conflicts.
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from accessroute.database.session import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """User account entity for optional authenticated capabilities."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    preferences = relationship("UserPreferencesModel", back_populates="user", uselist=False, cascade="all, delete-orphan")
    saved_places = relationship("SavedPlace", back_populates="user", cascade="all, delete-orphan")
    saved_routes = relationship("SavedRoute", back_populates="user", cascade="all, delete-orphan")


class UserPreferencesModel(Base):
    """Synchronized user mobility preferences stored in the cloud."""

    __tablename__ = "user_preferences"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    preset_name = Column(String(64), nullable=False, default="manual_wheelchair")
    preferences_json = Column(Text, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="preferences")


class SavedPlace(Base):
    """User-saved favorite or frequently visited geographic location."""

    __tablename__ = "saved_places"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(128), nullable=False)  # e.g. "Home", "Work", "University"
    display_name = Column(String(512), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    place_type = Column(String(64), nullable=True)
    preferred_entrance_id = Column(String(64), nullable=True)
    preferred_entrance_name = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="saved_places")

    __table_args__ = (
        Index("ix_saved_places_user_label", "user_id", "label"),
    )


class VenueEntranceModel(Base):
    """Database-persisted entrance records for destination venues."""

    __tablename__ = "venue_entrances"

    id = Column(String(64), primary_key=True)
    venue_id = Column(String(64), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    entrance_type = Column(String(32), default="main", nullable=False)
    wheelchair = Column(String(32), default="unknown", nullable=False)
    step_free = Column(Boolean, nullable=True)
    steps_count = Column(Integer, nullable=True)
    ramp = Column(String(32), default="unknown", nullable=False)
    automatic_door = Column(Boolean, nullable=True)
    door_type = Column(String(32), default="unknown", nullable=False)
    door_width_m = Column(Float, nullable=True)
    source = Column(String(64), default="openstreetmap", nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class SavedRoute(Base):
    """User-saved route template with recalculation metadata."""

    __tablename__ = "saved_routes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    origin_label = Column(String(256), nullable=False)
    origin_lat = Column(Float, nullable=False)
    origin_lon = Column(Float, nullable=False)
    dest_label = Column(String(256), nullable=False)
    dest_lat = Column(Float, nullable=False)
    dest_lon = Column(Float, nullable=False)
    preferences_snapshot_json = Column(Text, nullable=False)
    distance_m = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="saved_routes")


class CommunityObservationModel(Base):
    """Community-reported physical infrastructure finding."""

    __tablename__ = "community_observations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    category = Column(String(64), nullable=False, index=True)
    value = Column(String(64), nullable=False)
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    osm_element_type = Column(String(16), nullable=True)
    osm_element_id = Column(String(64), nullable=True, index=True)
    contributor_id = Column(String(64), nullable=False, index=True)
    source_type = Column(String(32), default="community_contributor", nullable=False)
    is_temporary = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    verification_status = Column(String(32), default="unverified", nullable=False, index=True)
    confirmations_count = Column(Integer, default=1, nullable=False)
    disputes_count = Column(Integer, default=0, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    interactions = relationship("CommunityInteractionModel", back_populates="observation", cascade="all, delete-orphan")
    verification_events = relationship("VerificationEventModel", back_populates="observation", cascade="all, delete-orphan")
    conflicts = relationship("EvidenceConflictModel", back_populates="observation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_obs_lat_lon", "latitude", "longitude"),
        Index("ix_obs_status_category", "verification_status", "category"),
    )


class CommunityInteractionModel(Base):
    """Confirmations and disputes recorded for an observation."""

    __tablename__ = "community_interactions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    observation_id = Column(String(36), ForeignKey("community_observations.id", ondelete="CASCADE"), nullable=False, index=True)
    contributor_id = Column(String(64), nullable=False, index=True)
    interaction_type = Column(String(16), nullable=False)  # "confirm" | "dispute"
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    observation = relationship("CommunityObservationModel", back_populates="interactions")

    __table_args__ = (
        UniqueConstraint("observation_id", "contributor_id", name="uq_obs_contributor_interaction"),
    )


class VerificationEventModel(Base):
    """Audit log of status transition and verification changes."""

    __tablename__ = "verification_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    observation_id = Column(String(36), ForeignKey("community_observations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(32), nullable=False)
    previous_status = Column(String(32), nullable=False)
    new_status = Column(String(32), nullable=False)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    observation = relationship("CommunityObservationModel", back_populates="verification_events")


class EvidenceConflictModel(Base):
    """Recorded conflicts between community reports and OpenStreetMap tags."""

    __tablename__ = "evidence_conflicts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    observation_id = Column(String(36), ForeignKey("community_observations.id", ondelete="CASCADE"), nullable=False, index=True)
    osm_element_type = Column(String(16), nullable=False)
    osm_element_id = Column(String(64), nullable=False, index=True)
    conflict_type = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(32), default="open", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    observation = relationship("CommunityObservationModel", back_populates="conflicts")
