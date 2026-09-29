"""Authentication endpoints for user registration, login, and profile."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from accessroute.auth.dependencies import get_current_user
from accessroute.auth.schemas import (
    TokenResponse,
    UserLogin,
    UserProfile,
    UserRegister,
)
from accessroute.auth.security import create_access_token
from accessroute.auth.service import AccountService
from accessroute.database.models import User
from accessroute.database.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: UserRegister, db: Session = Depends(get_db)):
    """Register a new user account and return an access token."""
    user = AccountService.register_user(db, req)
    token = create_access_token(data={"sub": user.id, "email": user.email})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserProfile.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(req: UserLogin, db: Session = Depends(get_db)):
    """Authenticate with email and password, returning an access token."""
    user = AccountService.authenticate_user(db, req)
    token = create_access_token(data={"sub": user.id, "email": user.email})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserProfile.model_validate(user),
    )


@router.get("/me", response_model=UserProfile)
def get_my_profile(current_user: User = Depends(get_current_user)):
    """Retrieve profile of the currently authenticated user."""
    return UserProfile.model_validate(current_user)
