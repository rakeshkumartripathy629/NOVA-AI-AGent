"""
First-run database seeding: superuser, default organization, plans, free
subscription and sample prompt templates.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import (
    AuthProvider,
    Organization,
    OrganizationMember,
    OrganizationRole,
    Plan,
    Prompt,
    PromptVisibility,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
    UserStatus,
)

logger = logging.getLogger(__name__)


async def seed_superuser(db: AsyncSession) -> User:
    """Create the initial superuser if none exists."""
    result = await db.execute(
        select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    user = User(
        email=settings.FIRST_SUPERUSER_EMAIL,
        username=settings.FIRST_SUPERUSER_USERNAME,
        full_name="Super Admin",
        hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
        role=UserRole.SUPER_ADMIN,
        status=UserStatus.ACTIVE,
        auth_provider=AuthProvider.LOCAL,
        email_verified=True,
        is_active=True,
        is_superuser=True,
    )
    db.add(user)
    await db.flush()
    logger.info("Created superuser %s", user.email)
    return user


async def seed_default_organization(db: AsyncSession, owner: User) -> Organization:
    """Create the default organization and owner membership."""
    result = await db.execute(
        select(Organization).where(Organization.slug == "nova-ai")
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    org = Organization(
        name="Nova AI",
        slug="nova-ai",
        description="Default organization for Nova AI platform",
        owner_id=owner.id,
        settings={
            "allow_public_signup": True,
            "require_email_verification": True,
            "default_role": OrganizationRole.MEMBER.value,
        },
    )
    db.add(org)
    await db.flush()

    db.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=owner.id,
            role=OrganizationRole.OWNER,
            status="active",
        )
    )
    logger.info("Created default organization")
    return org


async def seed_plans(db: AsyncSession) -> None:
    """Seed the pricing plans."""
    plans = [
        {
            "name": "free",
            "display_name": "Free",
            "description": "Perfect for individuals getting started",
            "price": 0,
            "currency": "USD",
            "interval": "monthly",
            "trial_days": 0,
            "features": ["5 projects", "100 messages / month", "Basic models", "1GB storage"],
            "limits": {
                "projects": 5,
                "messages_per_month": 100,
                "storage_gb": 1,
                "team_members": 1,
                "knowledge_bases": 1,
                "agents": 3,
                "workflows": 1,
                "api_calls_per_month": 1000,
            },
            "is_active": True,
            "is_public": True,
            "sort_order": 0,
        },
        {
            "name": "pro",
            "display_name": "Pro",
            "description": "For professionals who need more power",
            "price": 2900,
            "currency": "USD",
            "interval": "monthly",
            "trial_days": 14,
            "features": ["Unlimited projects", "Unlimited messages", "All models", "50GB storage", "Custom agents", "API access"],
            "limits": {
                "projects": -1,
                "messages_per_month": -1,
                "storage_gb": 50,
                "team_members": 10,
                "knowledge_bases": 10,
                "agents": 50,
                "workflows": 20,
                "api_calls_per_month": 100000,
            },
            "is_active": True,
            "is_public": True,
            "is_popular": True,
            "sort_order": 1,
        },
        {
            "name": "team",
            "display_name": "Team",
            "description": "For teams collaborating on AI projects",
            "price": 9900,
            "currency": "USD",
            "interval": "monthly",
            "trial_days": 14,
            "features": ["Everything in Pro", "Unlimited members", "Audit logs", "Advanced permissions"],
            "limits": {
                "projects": -1,
                "messages_per_month": -1,
                "storage_gb": 500,
                "team_members": -1,
                "knowledge_bases": 50,
                "agents": 200,
                "workflows": 100,
                "api_calls_per_month": 1000000,
            },
            "is_active": True,
            "is_public": True,
            "sort_order": 2,
        },
        {
            "name": "enterprise",
            "display_name": "Enterprise",
            "description": "For large organizations with custom needs",
            "price": 0,
            "currency": "USD",
            "interval": "monthly",
            "trial_days": 30,
            "features": ["Everything in Team", "Custom limits", "On-premise", "24/7 support"],
            "limits": {k: -1 for k in ("projects", "messages_per_month", "storage_gb", "team_members", "knowledge_bases", "agents", "workflows", "api_calls_per_month")},
            "is_active": True,
            "is_public": False,
            "sort_order": 3,
        },
    ]

    for data in plans:
        result = await db.execute(select(Plan).where(Plan.name == data["name"]))
        if result.scalar_one_or_none():
            continue
        db.add(Plan(**data))
    logger.info("Seeded pricing plans")


async def seed_free_subscription(db: AsyncSession, org: Organization) -> None:
    """Attach the free plan subscription to the default organization."""
    result = await db.execute(
        select(Subscription).where(Subscription.organization_id == org.id)
    )
    if result.scalar_one_or_none():
        return

    result = await db.execute(select(Plan).where(Plan.name == "free"))
    free_plan = result.scalar_one_or_none()
    if not free_plan:
        return

    now = datetime.utcnow()
    db.add(
        Subscription(
            organization_id=org.id,
            plan_id=free_plan.id,
            status=SubscriptionStatus.ACTIVE,
            interval="monthly",
            quantity=1,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
    )
    logger.info("Attached free plan to default organization")


async def seed_prompts(db: AsyncSession, owner: User, org: Organization) -> None:
    """Seed a small library of starter prompt templates."""
    templates = [
        {
            "name": "Summarize",
            "slug": "summarize",
            "content": "Please summarize the following content in a clear, concise way:\n\n{{content}}",
            "variables": ["content"],
            "type": "template",
        },
        {
            "name": "Rewrite",
            "slug": "rewrite",
            "content": "Rewrite the text below to be more {{tone}} while preserving meaning:\n\n{{content}}",
            "variables": ["content", "tone"],
            "type": "template",
        },
        {
            "name": "Analyze",
            "slug": "analyze",
            "content": "Analyze the following data/text and provide key insights, strengths and risks:\n\n{{content}}",
            "variables": ["content"],
            "type": "template",
        },
        {
            "name": "Brainstorm",
            "slug": "brainstorm",
            "content": "Brainstorm {{count}} creative ideas related to: {{topic}}",
            "variables": ["topic", "count"],
            "type": "template",
        },
        {
            "name": "Code Review",
            "slug": "code-review",
            "content": "Review the following code for bugs, security issues and style:\n\n```\n{{code}}\n```",
            "variables": ["code"],
            "type": "template",
        },
    ]
    for data in templates:
        result = await db.execute(
            select(Prompt).where(Prompt.slug == data["slug"], Prompt.owner_id == owner.id)
        )
        if result.scalar_one_or_none():
            continue
        db.add(
            Prompt(
                **data,
                description=data["content"][:80],
                visibility=PromptVisibility.PUBLIC,
                organization_id=org.id,
                owner_id=owner.id,
            )
        )
    logger.info("Seeded starter prompt templates")


async def seed_all() -> None:
    """Run all seed routines inside a single session."""
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        try:
            superuser = await seed_superuser(db)
            org = await seed_default_organization(db, superuser)
            await seed_plans(db)
            await db.flush()
            await seed_free_subscription(db, org)
            await seed_prompts(db, superuser, org)
            await db.commit()
            logger.info("Database seed complete")
        except Exception:
            await db.rollback()
            logger.exception("Database seeding failed")
            raise
