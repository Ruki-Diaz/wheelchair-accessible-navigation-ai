"""Authentication, user accounts, and synchronization package."""

from accessroute.auth.dependencies import (
    get_current_user,
    get_derived_contributor_id,
    get_optional_user,
)
from accessroute.auth.schemas import (
    SavedPlaceCreate,
    SavedPlaceResponse,
    SavedRouteCreate,
    SavedRouteResponse,
    TokenResponse,
    UserLogin,
    UserPreferencesResponse,
    UserPreferencesSync,
    UserProfile,
    UserRegister,
)
from accessroute.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from accessroute.auth.service import AccountService

__all__ = [
    "AccountService",
    "SavedPlaceCreate",
    "SavedPlaceResponse",
    "SavedRouteCreate",
    "SavedRouteResponse",
    "TokenResponse",
    "UserLogin",
    "UserPreferencesResponse",
    "UserPreferencesSync",
    "UserProfile",
    "UserRegister",
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "get_derived_contributor_id",
    "get_optional_user",
    "hash_password",
    "verify_password",
]
