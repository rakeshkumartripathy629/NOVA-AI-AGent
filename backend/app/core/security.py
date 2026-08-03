"""
Security utilities for authentication and authorization.
"""
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, List
from uuid import UUID

from jose import jwt, JWTError
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus


# Password hashing (direct bcrypt; passlib 1.7.4 is incompatible with bcrypt>=4.1)
import bcrypt as _bcrypt

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    """Token payload data."""
    sub: str  # user id
    email: str
    role: str
    org_id: Optional[str] = None
    permissions: List[str] = []
    type: str = "access"
    exp: int
    iat: int
    jti: str


class Token(BaseModel):
    """Token response model."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash."""
    try:
        return _bcrypt.checkpw(
            plain_password.encode("utf-8")[:72], hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """Hash a password with bcrypt."""
    return _bcrypt.hashpw(password.encode("utf-8")[:72], _bcrypt.gensalt()).decode("utf-8")


def generate_token_id() -> str:
    """Generate a unique token ID."""
    return secrets.token_urlsafe(32)


def create_access_token(
    user: User,
    organization_id: Optional[UUID] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create JWT access token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Get user permissions based on role
    permissions = get_role_permissions(user.role)
    
    to_encode = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "org_id": str(organization_id) if organization_id else None,
        "permissions": permissions,
        "type": "access",
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "jti": generate_token_id(),
    }
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(
    user: User,
    organization_id: Optional[UUID] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create JWT refresh token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "org_id": str(organization_id) if organization_id else None,
        "type": "refresh",
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "jti": generate_token_id(),
    }
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_token_pair(
    user: User,
    organization_id: Optional[UUID] = None,
) -> Token:
    """Create access and refresh token pair."""
    access_token = create_access_token(user, organization_id)
    refresh_token = create_refresh_token(user, organization_id)
    
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def decode_token(token: str) -> TokenData:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        return TokenData(**payload)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def verify_token(token: str, token_type: str = "access") -> TokenData:
    """Verify token and check type."""
    token_data = decode_token(token)
    
    if token_data.type != token_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type. Expected {token_type}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return token_data


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user from token."""
    from sqlalchemy import select

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token_data = verify_token(token, "access")
    
    result = await db.execute(
        select(User).where(User.id == UUID(token_data.sub))
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active or user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current superuser."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user


def get_role_permissions(role: UserRole) -> List[str]:
    """Get permissions for a role."""
    permissions_map = {
        UserRole.SUPER_ADMIN: [
            "*",  # All permissions
        ],
        UserRole.ADMIN: [
            "organization:read",
            "organization:update",
            "organization:delete",
            "organization:manage_members",
            "organization:manage_billing",
            "organization:manage_settings",
            "project:create",
            "project:read",
            "project:update",
            "project:delete",
            "project:manage_members",
            "conversation:create",
            "conversation:read",
            "conversation:update",
            "conversation:delete",
            "conversation:share",
            "message:create",
            "message:read",
            "message:update",
            "message:delete",
            "file:create",
            "file:read",
            "file:update",
            "file:delete",
            "knowledge_base:create",
            "knowledge_base:read",
            "knowledge_base:update",
            "knowledge_base:delete",
            "agent:create",
            "agent:read",
            "agent:update",
            "agent:delete",
            "agent:execute",
            "workflow:create",
            "workflow:read",
            "workflow:update",
            "workflow:delete",
            "workflow:execute",
            "api_key:create",
            "api_key:read",
            "api_key:update",
            "api_key:delete",
            "webhook:create",
            "webhook:read",
            "webhook:update",
            "webhook:delete",
            "audit_log:read",
            "billing:read",
            "billing:manage",
        ],
        UserRole.USER: [
            "organization:read",
            "project:create",
            "project:read",
            "project:update",
            "conversation:create",
            "conversation:read",
            "conversation:update",
            "conversation:share",
            "message:create",
            "message:read",
            "message:update",
            "file:create",
            "file:read",
            "file:update",
            "file:delete",
            "knowledge_base:create",
            "knowledge_base:read",
            "knowledge_base:update",
            "agent:create",
            "agent:read",
            "agent:update",
            "agent:execute",
            "workflow:create",
            "workflow:read",
            "workflow:update",
            "workflow:execute",
            "api_key:create",
            "api_key:read",
            "api_key:update",
            "api_key:delete",
        ],
        UserRole.VIEWER: [
            "organization:read",
            "project:read",
            "conversation:read",
            "message:read",
            "file:read",
            "knowledge_base:read",
            "agent:read",
            "workflow:read",
        ],
        UserRole.GUEST: [
            "conversation:read",
            "message:read",
            "file:read",
        ],
    }
    
    return permissions_map.get(role, [])


def check_permission(user: User, permission: str, organization_id: Optional[UUID] = None) -> bool:
    """Check if user has a specific permission."""
    # Super admin has all permissions
    if user.role == UserRole.SUPER_ADMIN:
        return True
    
    # Check if user belongs to the organization
    if organization_id:
        # This would need to check organization membership
        # For now, we'll assume the user has access if they're in the org
        pass
    
    permissions = get_role_permissions(user.role)
    
    # Check for wildcard permission
    if "*" in permissions:
        return True
    
    return permission in permissions


def require_permission(permission: str):
    """Dependency to require a specific permission."""
    async def permission_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if not check_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}"
            )
        return current_user
    
    return permission_checker


def require_role(*roles: UserRole):
    """Dependency to require specific role(s)."""
    async def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {[r.value for r in roles]}"
            )
        return current_user
    
    return role_checker


def generate_api_key() -> tuple[str, str]:
    """Generate API key and its hash."""
    # Format: nv_<random>
    key = f"nv_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return key, key_hash


def verify_api_key(key: str, key_hash: str) -> bool:
    """Verify API key against its hash."""
    computed_hash = hashlib.sha256(key.encode()).hexdigest()
    return hmac.compare_digest(computed_hash, key_hash)


def generate_reset_token() -> str:
    """Generate password reset token."""
    return secrets.token_urlsafe(32)


def generate_verification_token() -> str:
    """Generate email verification token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Verify webhook signature."""
    expected_signature = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(f"sha256={expected_signature}", signature)


class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self):
        self._requests: dict[str, list[float]] = {}
    
    def is_allowed(
        self,
        key: str,
        limit: int,
        window: int,
    ) -> bool:
        """Check if request is allowed."""
        import time
        now = time.time()
        
        if key not in self._requests:
            self._requests[key] = []
        
        # Remove old requests outside window
        self._requests[key] = [
            req_time for req_time in self._requests[key]
            if now - req_time < window
        ]
        
        if len(self._requests[key]) >= limit:
            return False
        
        self._requests[key].append(now)
        return True
    
    def get_remaining(self, key: str, limit: int, window: int) -> int:
        """Get remaining requests."""
        import time
        now = time.time()
        
        if key not in self._requests:
            return limit
        
        self._requests[key] = [
            req_time for req_time in self._requests[key]
            if now - req_time < window
        ]
        
        return max(0, limit - len(self._requests[key]))


# Global rate limiter instance
rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """Get client IP address from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"