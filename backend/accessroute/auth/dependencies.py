"""Authentication and authorization dependencies for FastAPI endpoints."""

from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from accessroute.auth.security import decode_access_token
from accessroute.database.models import User
from accessroute.database.session import get_db

security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency that strictly requires a valid JWT token.

    Raises HTTP 401 if missing, invalid, or user not found.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Dependency for endpoints supporting both anonymous and authenticated users.

    Returns the User if a valid Bearer token is provided, else returns None.
    Does NOT throw 401 if token is absent or invalid (graceful fallback).
    """
    if not credentials or not credentials.credentials:
        return None

    payload = decode_access_token(credentials.credentials)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    return user


def get_derived_contributor_id(
    user: Optional[User] = Depends(get_optional_user),
    client_contributor_id: Optional[str] = None,
) -> str:
    """Derive contributor ID to prevent spoofing.

    If the user is authenticated, the contributor ID is ALWAYS server-derived:
    `usr_<user.id>`. The client cannot spoof another contributor ID.
    If anonymous, an anonymous session prefix is enforced.
    """
    if user:
        return f"usr_{user.id}"
    
    if client_contributor_id and client_contributor_id.strip():
        cid = client_contributor_id.strip()
        if cid.startswith("usr_"):
            # Anonymous client attempting to use an authenticated format is forced to anon prefix
            return f"anon_{cid.replace('usr_', '')}"
        return cid
    
    return "anon_community_member"
