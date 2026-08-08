"""
Authentication endpoints.
"""
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import email_service
from app.core.logging import get_logger
from app.core.security import (
    verify_password,
    get_password_hash,
    create_token_pair,
    verify_token,
    generate_verification_token,
    generate_reset_token,
    hash_token,
    get_current_user,
    get_current_active_user,
    rate_limiter,
    get_client_ip,
)
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus, AuthProvider
from app.models.user_session import OAuthAccount
from app.models.organization import Organization, OrganizationMember, OrganizationRole


router = APIRouter()


# Request/Response Models
class LoginRequest(BaseModel):
    """Login request model."""
    email: EmailStr
    password: str
    remember_me: bool = False
    organization_id: Optional[UUID] = None


class RegisterRequest(BaseModel):
    """Register request model."""
    email: EmailStr
    username: Optional[str] = Field(None, min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=100)
    organization_name: Optional[str] = Field(None, max_length=100)


class TokenResponse(BaseModel):
    """Token response model."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserResponse"


class RefreshTokenRequest(BaseModel):
    """Refresh token request model."""
    refresh_token: str


class VerifyEmailRequest(BaseModel):
    """Verify email request model."""
    token: str


class ResendVerificationRequest(BaseModel):
    """Resend verification request model."""
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    """Forgot password request model."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password request model.

    Accepts either `password` (API clients) or `new_password` +
    `confirm_password` (web UI).
    """
    token: str
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    new_password: Optional[str] = Field(None, min_length=8, max_length=128)
    confirm_password: Optional[str] = None

    @model_validator(mode="after")
    def _validate_passwords(self) -> "ResetPasswordRequest":
        if self.new_password is not None or self.confirm_password is not None:
            if not self.new_password or not self.confirm_password:
                raise ValueError("new_password and confirm_password are both required")
            if self.new_password != self.confirm_password:
                raise ValueError("new_password and confirm_password do not match")
        elif self.password is None:
            raise ValueError("password is required")
        return self

    @property
    def resolved_password(self) -> str:
        return self.new_password or self.password


class ChangePasswordRequest(BaseModel):
    """Change password request model."""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class CreateOrganizationRequest(BaseModel):
    """Create organization request model (auth-scoped)."""
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = Field(None, max_length=500)
    logo_url: Optional[str] = None
    settings: Optional[dict] = None


class UserResponse(BaseModel):
    """User response model."""
    id: UUID
    email: str
    username: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    role: str
    status: str
    email_verified: bool
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class OrganizationResponse(BaseModel):
    """Organization response model."""
    id: UUID
    name: str
    slug: str
    description: Optional[str]
    logo_url: Optional[str]
    owner_id: UUID
    settings: dict
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    """Auth response with user and organization."""
    user: UserResponse
    organization: Optional[OrganizationResponse]
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# Helper functions
logger = get_logger("api.auth")

async def send_verification_email(email: str, token: str) -> None:
    """Send email verification email."""
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    body_text = (
        f"Welcome to Nova AI!\n\n"
        f"Please verify your email by clicking the link below:\n{verify_url}\n\n"
        f"If you did not sign up, you can ignore this email."
    )
    body_html = (
        f"<p>Welcome to <strong>Nova AI</strong>!</p>"
        f"<p>Please verify your email by clicking the link below:</p>"
        f'<p><a href="{verify_url}">Verify your email</a></p>'
        f"<p>If you did not sign up, you can ignore this email.</p>"
    )
    try:
        await email_service.send_email(
            email,
            "Verify your Nova AI email",
            body_text=body_text,
            body_html=body_html,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send verification email to %s: %s", email, exc)


async def send_password_reset_email(email: str, token: str) -> None:
    """Send password reset email."""
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    body_text = (
        f"You requested a password reset for your Nova AI account.\n\n"
        f"Click the link below to reset your password (valid for "
        f"{settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS} hours):\n{reset_url}\n\n"
        f"If you did not request this, you can ignore this email."
    )
    body_html = (
        f"<p>You requested a password reset for your <strong>Nova AI</strong> account.</p>"
        f"<p>Click the link below to reset your password (valid for "
        f"{settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS} hours):</p>"
        f'<p><a href="{reset_url}">Reset your password</a></p>'
        f"<p>If you did not request this, you can ignore this email.</p>"
    )
    try:
        await email_service.send_email(
            email,
            "Reset your Nova AI password",
            body_text=body_text,
            body_html=body_html,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send reset email to %s: %s", email, exc)


async def send_welcome_email(email: str, username: str) -> None:
    """Send welcome email."""
    body_text = (
        f"Hi {username},\n\n"
        f"Welcome to Nova AI! Your account has been created successfully.\n"
        f"Get started by logging in at {settings.FRONTEND_URL}."
    )
    body_html = (
        f"<p>Hi <strong>{username}</strong>,</p>"
        f"<p>Welcome to <strong>Nova AI</strong>! Your account has been created successfully.</p>"
        f'<p>Get started by <a href="{settings.FRONTEND_URL}">logging in</a>.</p>'
    )
    try:
        await email_service.send_email(
            email,
            "Welcome to Nova AI",
            body_text=body_text,
            body_html=body_html,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send welcome email to %s: %s", email, exc)


# Endpoints
@router.post("/login", response_model=AuthResponse, summary="User login")
async def login(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return access tokens.

    Accepts both application/x-www-form-urlencoded (username/password, OAuth2)
    and JSON bodies (email/username + password).
    """
    # Rate limiting for login
    client_ip = get_client_ip(request)
    if not rate_limiter.is_allowed(
        f"login:{client_ip}",
        settings.RATE_LIMIT_LOGIN_REQUESTS,
        settings.RATE_LIMIT_LOGIN_WINDOW,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )
    
    # Parse credentials from either form data or JSON
    content_type = request.headers.get("content-type", "")
    username: Optional[str] = None
    password: Optional[str] = None
    organization_id: Optional[UUID] = None
    
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            body = {}
        username = body.get("email") or body.get("username")
        password = body.get("password")
        organization_id = body.get("organization_id")
    else:
        form = await request.form()
        username = form.get("username") or form.get("email")
        password = form.get("password")
        organization_id = form.get("organization_id")
    
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="username and password are required",
        )
    
    if organization_id:
        try:
            organization_id = UUID(str(organization_id))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid organization_id",
            )
    
    # Find user by email
    result = await db.execute(
        select(User).where(User.email == username)
    )
    user = result.scalar_one_or_none()
    
    if not user or not user.hashed_password or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active or user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive or suspended",
        )
    
    # Get user's organization
    org_id = None
    if organization_id:
        # Verify user is member of this organization
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.status == "active",
            )
        )
        member = result.scalar_one_or_none()
        if member:
            org_id = organization_id
    else:
        # Get first active organization
        result = await db.execute(
            select(OrganizationMember.organization_id).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == "active",
            )
        )
        org_id = result.scalars().first()
    
    # Create tokens
    token_pair = create_token_pair(user, org_id)
    
    # Set refresh token as httpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=token_pair.refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    
    # Get organization if exists
    organization = None
    if org_id:
        result = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        organization = result.scalar_one_or_none()
    
    return AuthResponse(
        user=UserResponse.model_validate(user),
        organization=OrganizationResponse.model_validate(organization) if organization else None,
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in=token_pair.expires_in,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED, summary="User registration")
async def register(
    request: Request,
    response: Response,
    user_data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user."""
    # Rate limiting for registration
    client_ip = get_client_ip(request)
    if not rate_limiter.is_allowed(
        f"register:{client_ip}",
        settings.RATE_LIMIT_REGISTER_REQUESTS,
        settings.RATE_LIMIT_REGISTER_WINDOW,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later.",
        )
    
    # Check if email already exists
    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Check if username already exists
    username = user_data.username
    if not username:
        username = re.sub(r"[^a-zA-Z0-9_-]", "", (user_data.email.split("@")[0] or "user")) or "user"
        while True:
            existing = await db.scalar(select(User.id).where(User.username == username))
            if not existing:
                break
            username = f"{username[:40]}{uuid.uuid4().hex[:4]}"
    result = await db.execute(
        select(User).where(User.username == username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )
    
    # Create user
    user = User(
        email=user_data.email,
        username=username,
        full_name=user_data.full_name,
        hashed_password=get_password_hash(user_data.password),
       role=UserRole.USER,
        status=UserStatus.ACTIVE,
        auth_provider=AuthProvider.LOCAL,
        email_verified=not settings.FIRST_SUPERUSER_EMAIL,  # Auto-verify if not first superuser
    )
    db.add(user)
    await db.flush()
    
    # Create organization if provided
    organization = None
    if user_data.organization_name:
        base_slug = user_data.organization_name.lower().replace(" ", "-")
        slug = base_slug
        counter = 2
        while await db.scalar(select(Organization.id).where(Organization.slug == slug)):
            slug = f"{base_slug}-{counter}"
            counter += 1

        org = Organization(
            name=user_data.organization_name,
            slug=slug,
            description=f"Organization for {user_data.full_name or username}",
            owner_id=user.id,
        )
        db.add(org)
        await db.flush()
        
        # Add user as owner
        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role="owner",
            status="active",
        )
        db.add(member)
        organization = org
    else:
        # Create personal organization
        org = Organization(
            name=f"{user.username}'s Workspace",
            slug=f"{user.username}-workspace",
            description=f"Personal workspace for {user.username}",
            owner_id=user.id,
        )
        db.add(org)
        await db.flush()
        
        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role="owner",
            status="active",
        )
        db.add(member)
        organization = org
    
    await db.commit()
    
    # Send verification email if needed
    if not user.email_verified:
        token = generate_verification_token()
        user.verification_token = hash_token(token)
        await db.commit()
        await send_verification_email(user.email, token)
    
    # Send welcome email
    await send_welcome_email(user.email, user.username)
    
    # Create tokens
    token_pair = create_token_pair(user, organization.id)
    
    # Set refresh token cookie
    response.set_cookie(
        key="refresh_token",
        value=token_pair.refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    
    return AuthResponse(
        user=UserResponse.model_validate(user),
        organization=OrganizationResponse.model_validate(organization),
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in=token_pair.expires_in,
    )


@router.post("/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED, summary="Create organization")
async def create_organization(
    org_data: CreateOrganizationRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an organization owned by the authenticated user.

    Mirrors POST /api/v1/organizations so clients that create an
    organization under the auth namespace (POST /api/v1/auth/organizations)
    get the same behavior instead of a 404.
    """
    # Check if slug is taken
    result = await db.execute(
        select(Organization).where(Organization.slug == org_data.slug)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug already taken",
        )

    # Create organization
    org = Organization(
        name=org_data.name,
        slug=org_data.slug,
        description=org_data.description,
        logo_url=org_data.logo_url,
        owner_id=current_user.id,
        settings=org_data.settings or {},
    )
    db.add(org)
    await db.flush()

    # Add creator as owner
    member = OrganizationMember(
        organization_id=org.id,
        user_id=current_user.id,
        role=OrganizationRole.OWNER,
        status="active",
    )
    db.add(member)

    await db.commit()
    await db.refresh(org)

    return OrganizationResponse.model_validate(org)


@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_token(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token."""
    # Get refresh token from cookie or body
    if not refresh_token:
        refresh_token = request.cookies.get("refresh_token")
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not provided",
        )
    
    # Verify refresh token
    try:
        token_data = verify_token(refresh_token, "refresh")
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    # Get user
    result = await db.execute(
        select(User).where(User.id == UUID(token_data.sub))
    )
    user = result.scalar_one_or_none()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    # Get organization
    org_id = UUID(token_data.org_id) if token_data.org_id else None
    
    # Create new token pair
    token_pair = create_token_pair(user, org_id)
    
    # Set new refresh token cookie
    response.set_cookie(
        key="refresh_token",
        value=token_pair.refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    
    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in=token_pair.expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", summary="User logout")
async def logout(
    response: Response,
    current_user: User = Depends(get_current_active_user),
):
    """Logout user by clearing refresh token cookie."""
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse, summary="Get current user")
async def get_me(
    current_user: User = Depends(get_current_active_user),
):
    """Get current authenticated user."""
    return UserResponse.model_validate(current_user)


@router.post("/verify-email", summary="Verify email address")
async def verify_email(
    request: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify user's email address."""
    token_hash = hash_token(request.token)
    
    result = await db.execute(
        select(User).where(User.verification_token == token_hash)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )
    
    user.email_verified = True
    user.verification_token = None
    await db.commit()
    
    return {"message": "Email verified successfully"}


@router.post("/resend-verification", summary="Resend verification email")
async def resend_verification(
    request: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resend email verification."""
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        # Don't reveal if email exists
        return {"message": "If the email exists, a verification email has been sent"}
    
    if user.email_verified:
        return {"message": "Email is already verified"}
    
    token = generate_verification_token()
    user.verification_token = hash_token(token)
    await db.commit()
    
    await send_verification_email(user.email, token)
    
    return {"message": "If the email exists, a verification email has been sent"}


@router.post("/forgot-password", summary="Request password reset")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request password reset email."""
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        # Don't reveal if email exists
        return {"message": "If the email exists, a password reset email has been sent"}
    
    token = generate_reset_token()
    user.reset_token = hash_token(token)
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
    await db.commit()
    
    await send_password_reset_email(user.email, token)
    
    return {"message": "If the email exists, a password reset email has been sent"}


@router.post("/reset-password", summary="Reset password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset user password."""
    token_hash = hash_token(request.token)
    
    result = await db.execute(
        select(User).where(User.reset_token == token_hash)
    )
    user = result.scalar_one_or_none()
    
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    
    user.hashed_password = get_password_hash(request.resolved_password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()
    
    return {"message": "Password reset successfully"}


@router.post("/change-password", summary="Change password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Change user password."""
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    
    current_user.hashed_password = get_password_hash(request.new_password)
    await db.commit()
    
    return {"message": "Password changed successfully"}


@router.post("/switch-organization", response_model=TokenResponse, summary="Switch organization")
async def switch_organization(
    organization_id: UUID,
    response: Response,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch current organization and get new tokens."""
    # Verify user is member of organization
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == "active",
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    
    # Create new token pair with new organization
    token_pair = create_token_pair(current_user, organization_id)
    
    # Set new refresh token cookie
    response.set_cookie(
        key="refresh_token",
        value=token_pair.refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    
    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        expires_in=token_pair.expires_in,
        user=UserResponse.model_validate(current_user),
    )


# OAuth endpoints
OAUTH_STATE_COOKIE = "oauth_state"


def _oauth_redirect_uri(provider: str) -> str:
    """Build the OAuth redirect URI for the given provider.

    The callback lives on the API and is served on the same origin as the
    frontend (nginx proxies /api/v1), so it is derived from FRONTEND_URL.
    """
    return f"{settings.FRONTEND_URL}/api/v1/auth/oauth/callback/{provider}"


def _oauth_enabled(provider: str) -> bool:
    if provider == "google":
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    if provider == "github":
        return bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET)
    return False


def _oauth_credentials(provider: str) -> tuple[str, str]:
    if provider == "google":
        return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    if provider == "github":
        return settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported OAuth provider",
    )


@router.get("/oauth/config", summary="OAuth provider availability")
async def oauth_config() -> dict:
    """Return which OAuth providers are configured and enabled."""
    return {
        "google": _oauth_enabled("google"),
        "github": _oauth_enabled("github"),
    }


async def _start_oauth(provider: str, request: Request) -> RedirectResponse:
    if not _oauth_enabled(provider):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{provider.title()} OAuth is not configured",
        )
    client_id, _ = _oauth_credentials(provider)
    state = secrets.token_urlsafe(32)
    redirect_uri = _oauth_redirect_uri(provider)

    if provider == "google":
        # prompt=select_account always shows Google's account chooser so the
        # user can pick any of the Google accounts signed in on this machine.
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            + urlencode(
                {
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile",
                    "state": state,
                    "prompt": "select_account",
                    "access_type": "online",
                }
            )
        )
    else:
        auth_url = (
            "https://github.com/login/oauth/authorize?"
            + urlencode(
                {
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "scope": "read:user user:email",
                    "state": state,
                }
            )
        )

    response = RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/oauth/google", summary="Google OAuth login")
async def google_oauth(request: Request):
    """Initiate Google OAuth flow."""
    return await _start_oauth("google", request)


@router.get("/oauth/github", summary="GitHub OAuth login")
async def github_oauth(request: Request):
    """Initiate GitHub OAuth flow."""
    return await _start_oauth("github", request)


async def _exchange_code(provider: str, code: str, redirect_uri: str) -> dict:
    """Exchange the authorization code for access tokens."""
    client_id, client_secret = _oauth_credentials(provider)
    async with httpx.AsyncClient(timeout=20) as client:
        if provider == "google":
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        else:
            resp = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                },
            )
    if resp.status_code != 200:
        logger.warning("OAuth token exchange failed for %s: HTTP %s", provider, resp.status_code)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OAuth token exchange failed ({provider})",
        )
    data = resp.json()
    if not data.get("access_token"):
        logger.warning("OAuth token exchange missing access_token for %s", provider)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OAuth token exchange failed ({provider})",
        )
    return data


async def _fetch_profile(provider: str, access_token: str) -> dict:
    """Fetch the provider's profile for the authenticated user."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        if provider == "google":
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo", headers=headers
            )
        else:
            resp = await client.get("https://api.github.com/user", headers=headers)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Could not fetch {provider} profile",
            )
        profile = resp.json()
        if provider == "github":
            # GitHub only returns an email if it is public; fall back to the
            # verified primary email from the /user/emails endpoint.
            if not profile.get("email"):
                email_resp = await client.get(
                    "https://api.github.com/user/emails", headers=headers
                )
                if email_resp.status_code == 200:
                    for entry in email_resp.json():
                        if entry.get("primary") and entry.get("verified"):
                            profile["email"] = entry.get("email")
                            break
    return profile


async def _unique_username(db: AsyncSession, base: str) -> str:
    """Generate a unique username from a base string."""
    username = re.sub(r"[^a-zA-Z0-9_-]", "", base) or "user"
    username = username[:40] or "user"
    if username[0].isdigit():
        username = f"u_{username}"
    while True:
        if not await db.scalar(select(User.id).where(User.username == username)):
            return username
        username = f"{username[:36]}{uuid.uuid4().hex[:4]}"


async def _find_or_create_oauth_user(
    db: AsyncSession,
    provider: str,
    profile: dict,
    token_info: dict,
) -> User:
    """Find or create a user linked to an OAuth provider account."""
    provider_user_id = str(profile.get("sub") or profile.get("id") or "").strip()
    if not provider_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider did not return a user id ({provider})",
        )

    email = (profile.get("email") or "").strip().lower() or None
    name = profile.get("name")
    if not name and provider == "github":
        name = profile.get("login")
    avatar_url = profile.get("picture") or profile.get("avatar_url")

    now = datetime.utcnow()
    expires_in = token_info.get("expires_in")

    def _make_oauth_record(user_id) -> OAuthAccount:
        return OAuthAccount(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=email,
            access_token=token_info.get("access_token"),
            refresh_token=token_info.get("refresh_token"),
            token_expires_at=now + timedelta(seconds=expires_in) if expires_in else None,
            avatar_url=avatar_url,
            profile=profile,
        )

    # 1) Existing OAuth link
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    oauth = result.scalar_one_or_none()
    if oauth:
        user = await db.get(User, oauth.user_id)
        if user is None or not user.is_active or user.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is inactive or suspended",
            )
        oauth.access_token = token_info.get("access_token")
        oauth.refresh_token = token_info.get("refresh_token")
        if expires_in:
            oauth.token_expires_at = now + timedelta(seconds=expires_in)
        oauth.avatar_url = avatar_url
        oauth.profile = profile
        await db.commit()
        return user

    # 2) Existing user with the same email -> link the provider account
    user = None
    if email:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
    if user is not None:
        db.add(_make_oauth_record(user.id))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        return user

    # 3) Create a new user with a personal workspace
    username = await _unique_username(db, email.split("@")[0] if email else provider_user_id)
    user = User(
        email=email or f"{provider_user_id}@{provider}.nova.local",
        username=username,
        full_name=name,
        avatar_url=avatar_url,
        auth_provider=AuthProvider(provider),
        email_verified=True,
        email_verified_at=now,
        is_active=True,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    await db.flush()

    org = Organization(
        name=f"{username}'s Workspace",
        slug=f"{username}-workspace",
        description=f"Personal workspace for {username}",
        owner_id=user.id,
    )
    db.add(org)
    await db.flush()

    db.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.OWNER,
            status="active",
        )
    )
    db.add(_make_oauth_record(user.id))
    await db.commit()
    logger.info("Created user %s via %s OAuth", user.email, provider)
    return user


@router.get("/oauth/callback/{provider}", summary="OAuth callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback from the provider."""
    frontend_url = settings.FRONTEND_URL
    fail_redirect = f"{frontend_url}/?oauth_error=oauth_failed"

    if provider not in ("google", "github"):
        return RedirectResponse(
            f"{frontend_url}/?oauth_error=unsupported_provider",
            status_code=status.HTTP_302_FOUND,
        )
    if error:
        return RedirectResponse(
            f"{frontend_url}/?oauth_error=provider_denied",
            status_code=status.HTTP_302_FOUND,
        )
    if not code:
        return RedirectResponse(
            f"{frontend_url}/?oauth_error=missing_code",
            status_code=status.HTTP_302_FOUND,
        )

    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not expected_state or not state or not secrets.compare_digest(state, expected_state):
        return RedirectResponse(
            f"{frontend_url}/?oauth_error=invalid_state",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        token_info = await _exchange_code(provider, code, _oauth_redirect_uri(provider))
        profile = await _fetch_profile(provider, token_info["access_token"])
        user = await _find_or_create_oauth_user(db, provider, profile, token_info)
    except HTTPException as exc:
        logger.warning("OAuth callback error for %s: %s", provider, exc.detail)
        return RedirectResponse(fail_redirect)
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected OAuth callback error for %s", provider)
        return RedirectResponse(fail_redirect)

    # Get the user's first active organization
    result = await db.execute(
        select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
    )
    org_id = result.scalars().first()

    token_pair = create_token_pair(user, org_id)

    redirect = RedirectResponse(
        f"{frontend_url}/auth/callback",
        status_code=status.HTTP_302_FOUND,
    )
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    redirect.set_cookie(
        key="refresh_token",
        value=token_pair.refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    return redirect


# Import datetime at the end to avoid circular imports
from datetime import datetime