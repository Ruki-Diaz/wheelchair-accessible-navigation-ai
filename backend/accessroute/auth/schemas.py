"""Pydantic schemas for authentication, accounts, saved places, and preference sync."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class UserRegister(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)


class UserLogin(BaseModel):
    email: str
    password: str


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: Optional[str] = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


class SavedPlaceCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=128)
    display_name: Optional[str] = Field(None, max_length=512)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    place_type: Optional[str] = Field(None, max_length=64)
    preferred_entrance_id: Optional[str] = Field(None, max_length=64)
    preferred_entrance_name: Optional[str] = Field(None, max_length=256)


class SavedPlaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    display_name: Optional[str] = None
    latitude: float
    longitude: float
    place_type: Optional[str] = None
    preferred_entrance_id: Optional[str] = None
    preferred_entrance_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SavedRouteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    origin_label: str = Field(..., min_length=1, max_length=256)
    origin_lat: float = Field(..., ge=-90.0, le=90.0)
    origin_lon: float = Field(..., ge=-180.0, le=180.0)
    dest_label: str = Field(..., min_length=1, max_length=256)
    dest_lat: float = Field(..., ge=-90.0, le=90.0)
    dest_lon: float = Field(..., ge=-180.0, le=180.0)
    preferences_snapshot_json: str
    distance_m: float = Field(..., ge=0.0)


class SavedRouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    origin_label: str
    origin_lat: float
    origin_lon: float
    dest_label: str
    dest_lat: float
    dest_lon: float
    preferences_snapshot_json: str
    distance_m: float
    created_at: datetime
    updated_at: datetime


class UserPreferencesSync(BaseModel):
    preset_name: str = Field("manual_wheelchair", max_length=64)
    preferences_json: str
    version: Optional[int] = 1


class UserPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    preset_name: str
    preferences_json: str
    version: int
    updated_at: datetime
