"""
Self-service subscription endpoints for the current organization.

Complements the org-scoped billing router with organization-context endpoints.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_organization
from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.billing import BillingInterval, Plan, Subscription, SubscriptionStatus
from app.models.organization import Organization, OrganizationMember
from app.models.user import User

router = APIRouter()


class PlanResponse(BaseModel):
    """Public plan response model."""
    id: UUID
    name: str
    display_name: str
    description: Optional[str] = None
    price: int = 0
    currency: str = "USD"
    interval: str = "monthly"
    features: list = []
    is_popular: bool = False
    trial_days: int = 0
    sort_order: int = 0

    class Config:
        from_attributes = True


class SubscriptionResponse(BaseModel):
    """Subscription response model."""
    id: UUID
    organization_id: UUID
    plan_id: UUID
    status: str
    interval: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool = False
    trial_end: Optional[datetime] = None
    quantity: int = 1
    plan: Optional[PlanResponse] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChangePlanRequest(BaseModel):
    """Change plan request model."""
    plan_id: UUID
    quantity: int = Field(1, ge=1)


class UsageSummary(BaseModel):
    """Usage summary item."""
    type: str
    total_quantity: float = 0.0
    total_cost: float = 0.0


async def _require_org_admin(db: AsyncSession, organization: Organization, user: User) -> None:
    if organization.owner_id == user.id:
        return
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == user.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member or member.role.value not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization admin access required")


@router.get("/plans", response_model=List[PlanResponse], summary="List public plans")
async def list_plans(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List active public plans."""
    result = await db.execute(
        select(Plan)
        .where(Plan.is_active.is_(True), Plan.is_public.is_(True))
        .order_by(Plan.sort_order)
    )
    return [PlanResponse.model_validate(p) for p in result.scalars().all()]


@router.get("/current", response_model=SubscriptionResponse, summary="Get current subscription")
async def get_current_subscription(
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Get the active subscription for the current organization."""
    result = await db.execute(
        select(Subscription)
        .where(Subscription.organization_id == organization.id)
        .order_by(desc(Subscription.created_at))
        .limit(1)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No subscription found")

    plan_result = await db.execute(select(Plan).where(Plan.id == subscription.plan_id))
    subscription.plan = plan_result.scalar_one_or_none()
    return SubscriptionResponse.model_validate(subscription)


@router.post("/change", response_model=SubscriptionResponse, summary="Change subscription plan")
async def change_plan(
    request: ChangePlanRequest,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Switch the current organization's subscription to another plan."""
    await _require_org_admin(db, organization, current_user)

    plan = (
        await db.execute(select(Plan).where(Plan.id == request.plan_id, Plan.is_active.is_(True)))
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    result = await db.execute(
        select(Subscription)
        .where(Subscription.organization_id == organization.id)
        .order_by(desc(Subscription.created_at))
        .limit(1)
    )
    subscription = result.scalar_one_or_none()

    now = datetime.utcnow()
    if subscription:
        subscription.plan_id = request.plan_id
        subscription.quantity = request.quantity
        subscription.current_period_start = now
        subscription.current_period_end = now + timedelta(days=30)
    else:
        subscription = Subscription(
            organization_id=organization.id,
            plan_id=request.plan_id,
            status=SubscriptionStatus.TRIALING if plan.trial_days else SubscriptionStatus.ACTIVE,
            interval=plan.interval,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            quantity=request.quantity,
        )
        if plan.trial_days:
            subscription.trial_end = now + timedelta(days=plan.trial_days)
        db.add(subscription)

    await db.commit()
    await db.refresh(subscription)
    subscription.plan = plan
    return SubscriptionResponse.model_validate(subscription)


@router.post("/cancel", response_model=SubscriptionResponse, summary="Cancel subscription")
async def cancel_subscription(
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Cancel the subscription at the end of the current period."""
    await _require_org_admin(db, organization, current_user)

    result = await db.execute(
        select(Subscription)
        .where(
            Subscription.organization_id == organization.id,
            Subscription.status.in_(
                [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE]
            ),
        )
        .order_by(desc(Subscription.created_at))
        .limit(1)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active subscription found")

    subscription.cancel_at_period_end = True
    await db.commit()
    await db.refresh(subscription)
    return SubscriptionResponse.model_validate(subscription)


@router.post("/resume", response_model=SubscriptionResponse, summary="Resume subscription")
async def resume_subscription(
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Resume a subscription that was set to cancel at period end."""
    await _require_org_admin(db, organization, current_user)

    result = await db.execute(
        select(Subscription)
        .where(
            Subscription.organization_id == organization.id,
            Subscription.cancel_at_period_end.is_(True),
        )
        .order_by(desc(Subscription.created_at))
        .limit(1)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No canceling subscription found")

    subscription.cancel_at_period_end = False
    await db.commit()
    await db.refresh(subscription)
    return SubscriptionResponse.model_validate(subscription)


@router.get("/usage", summary="Get usage summary")
async def get_usage(
    period: str = Query(None, description="YYYY-MM"),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Return usage aggregates for the current organization."""
    from app.models.usage import UsageAggregate

    query = select(UsageAggregate).where(UsageAggregate.organization_id == organization.id)
    if period:
        query = query.where(UsageAggregate.period == period)

    aggregates = (await db.execute(query.order_by(UsageAggregate.period))).scalars().all()
    return {
        "period": period or "all",
        "items": [UsageSummary.model_validate(a) for a in aggregates],
    }
