"""
Billing and subscription management endpoints.
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_active_user, require_permission
from app.core.config import settings
from app.db.session import get_db, get_session_factory
from app.models.user import User
from app.models.organization import Organization
from app.models.billing import Subscription, Plan, Invoice, PaymentMethod, BillingInterval
from app.services.billing import construct_webhook_event, handle_stripe_event


router = APIRouter()


# Request/Response Models
class PlanResponse(BaseModel):
    """Plan response model."""
    id: UUID
    name: str
    description: Optional[str]
    price: int  # in cents
    currency: str
    interval: str
    features: list
    limits: dict
    is_active: bool
    is_popular: bool
    sort_order: int
    
    class Config:
        from_attributes = True


class PlanListResponse(BaseModel):
    """Plan list response model."""
    plans: List[PlanResponse]


class SubscriptionCreate(BaseModel):
    """Subscription create model."""
    plan_id: UUID
    organization_id: UUID
    payment_method_id: Optional[UUID] = None
    trial_days: int = 0


class SubscriptionUpdate(BaseModel):
    """Subscription update model."""
    plan_id: Optional[UUID] = None
    quantity: Optional[int] = Field(None, ge=1)
    cancel_at_period_end: Optional[bool] = None


class SubscriptionResponse(BaseModel):
    """Subscription response model."""
    id: UUID
    organization_id: UUID
    plan_id: UUID
    status: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    canceled_at: Optional[datetime]
    trial_start: Optional[datetime]
    trial_end: Optional[datetime]
    quantity: int
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    plan: Optional[PlanResponse] = None
    
    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    """Invoice response model."""
    id: UUID
    subscription_id: UUID
    organization_id: UUID
    amount: int
    currency: str
    status: str
    invoice_number: str
    invoice_url: Optional[str]
    pdf_url: Optional[str]
    period_start: datetime
    period_end: datetime
    paid_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class InvoiceListResponse(BaseModel):
    """Invoice list response model."""
    invoices: List[InvoiceResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class PaymentMethodCreate(BaseModel):
    """Payment method create model."""
    type: str = "card"
    token: str  # Stripe payment method ID or similar
    set_as_default: bool = False


class PaymentMethodResponse(BaseModel):
    """Payment method response model."""
    id: UUID
    organization_id: UUID
    type: str
    brand: Optional[str]
    last4: Optional[str]
    exp_month: Optional[int]
    exp_year: Optional[int]
    is_default: bool
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    
    class Config:
        from_attributes = True


class PaymentMethodListResponse(BaseModel):
    """Payment method list response model."""
    payment_methods: List[PaymentMethodResponse]


class CheckoutSessionRequest(BaseModel):
    """Checkout session request model."""
    plan_id: UUID
    organization_id: UUID
    success_url: str
    cancel_url: str
    trial_days: int = 0


class CheckoutSessionResponse(BaseModel):
    """Checkout session response model."""
    session_id: str
    url: str


class BillingPortalRequest(BaseModel):
    """Billing portal request model."""
    organization_id: UUID
    return_url: str


class BillingPortalResponse(BaseModel):
    """Billing portal response model."""
    url: str


class BillingConfigResponse(BaseModel):
    """Billing configuration exposed to clients."""
    enabled: bool = False
    publishable_key: Optional[str] = None
    currency: str = "USD"


# Endpoints
@router.get("/plans", response_model=PlanListResponse, summary="List available plans")
async def list_plans(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all available subscription plans."""
    result = await db.execute(
        select(Plan).where(Plan.is_active == True).order_by(Plan.sort_order)
    )
    plans = result.scalars().all()
    
    return PlanListResponse(plans=[PlanResponse.model_validate(p) for p in plans])


@router.get("/plans/{plan_id}", response_model=PlanResponse, summary="Get plan")
async def get_plan(
    plan_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get plan by ID."""
    result = await db.execute(
        select(Plan).where(Plan.id == plan_id)
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    return PlanResponse.model_validate(plan)


@router.get("/organizations/{organization_id}/subscription", response_model=SubscriptionResponse, summary="Get organization subscription")
async def get_organization_subscription(
    organization_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get organization's current subscription."""
    # Check organization membership
    from app.models.organization import OrganizationMember
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    
    result = await db.execute(
        select(Subscription).where(
            Subscription.organization_id == organization_id,
            Subscription.status.in_(["active", "trialing", "past_due", "canceled"]),
        ).order_by(desc(Subscription.created_at))
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found",
        )
    
    # Load plan
    await db.refresh(subscription, ["plan"])
    
    return SubscriptionResponse.model_validate(subscription)


@router.post("/organizations/{organization_id}/subscription", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED, summary="Create subscription")
async def create_subscription(
    organization_id: UUID,
    subscription_data: SubscriptionCreate,
    current_user: User = Depends(require_permission("billing:subscription:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new subscription for an organization."""
    # Check organization admin access
    from app.models.organization import OrganizationMember, OrganizationRole
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage billing for this organization",
        )
    
    # Check if organization already has active subscription
    result = await db.execute(
        select(Subscription).where(
            Subscription.organization_id == organization_id,
            Subscription.status.in_(["active", "trialing"]),
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization already has an active subscription",
        )
    
    # Get plan
    result = await db.execute(
        select(Plan).where(Plan.id == subscription_data.plan_id)
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    # TODO: Create subscription via Stripe/Payment provider
    # This is a placeholder
    
    from datetime import datetime, timedelta
    
    now = datetime.utcnow()
    trial_end = None
    if subscription_data.trial_days > 0:
        trial_end = now + timedelta(days=subscription_data.trial_days)
    
    period_end = now + timedelta(days=30)  # Monthly for now
    
    subscription = Subscription(
        organization_id=organization_id,
        plan_id=plan.id,
        status="trialing" if trial_end else "active",
        current_period_start=now,
        current_period_end=period_end,
        trial_start=now if trial_end else None,
        trial_end=trial_end,
        quantity=1,
        metadata_={},
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    
    return SubscriptionResponse.model_validate(subscription)


@router.patch("/organizations/{organization_id}/subscription", response_model=SubscriptionResponse, summary="Update subscription")
async def update_subscription(
    organization_id: UUID,
    subscription_data: SubscriptionUpdate,
    current_user: User = Depends(require_permission("billing:subscription:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update organization subscription."""
    # Check organization admin access
    from app.models.organization import OrganizationMember, OrganizationRole
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage billing for this organization",
        )
    
    result = await db.execute(
        select(Subscription).where(
            Subscription.organization_id == organization_id,
            Subscription.status.in_(["active", "trialing", "past_due"]),
        ).order_by(desc(Subscription.created_at))
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found",
        )
    
    update_data = subscription_data.model_dump(exclude_unset=True)
    
    # Handle plan change
    if "plan_id" in update_data:
        new_plan_id = update_data.pop("plan_id")
        result = await db.execute(
            select(Plan).where(Plan.id == new_plan_id)
        )
        new_plan = result.scalar_one_or_none()
        if not new_plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found",
            )
        subscription.plan_id = new_plan_id
        # TODO: Handle proration via Stripe
    
    for field, value in update_data.items():
        setattr(subscription, field, value)
    
    await db.commit()
    await db.refresh(subscription)
    
    return SubscriptionResponse.model_validate(subscription)


@router.delete("/organizations/{organization_id}/subscription", status_code=status.HTTP_204_NO_CONTENT, summary="Cancel subscription")
async def cancel_subscription(
    organization_id: UUID,
    immediately: bool = Query(False),
    current_user: User = Depends(require_permission("billing:subscription:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Cancel organization subscription."""
    # Check organization admin access
    from app.models.organization import OrganizationMember, OrganizationRole
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage billing for this organization",
        )
    
    result = await db.execute(
        select(Subscription).where(
            Subscription.organization_id == organization_id,
            Subscription.status.in_(["active", "trialing", "past_due"]),
        ).order_by(desc(Subscription.created_at))
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found",
        )
    
    if immediately:
        subscription.status = "canceled"
        subscription.canceled_at = datetime.utcnow()
    else:
        subscription.cancel_at_period_end = True
    
    await db.commit()


# Invoice endpoints
@router.get("/organizations/{organization_id}/invoices", response_model=InvoiceListResponse, summary="List invoices")
async def list_invoices(
    organization_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List organization invoices."""
    # Check organization membership
    from app.models.organization import OrganizationMember
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    
    query = select(Invoice).where(Invoice.organization_id == organization_id)
    
    if status_filter:
        query = query.where(Invoice.status == status_filter)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(desc(Invoice.created_at))
    
    result = await db.execute(query)
    invoices = result.scalars().all()
    
    return InvoiceListResponse(
        invoices=[InvoiceResponse.model_validate(i) for i in invoices],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/organizations/{organization_id}/invoices/{invoice_id}", response_model=InvoiceResponse, summary="Get invoice")
async def get_invoice(
    organization_id: UUID,
    invoice_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get invoice by ID."""
    # Check organization membership
    from app.models.organization import OrganizationMember
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.organization_id == organization_id,
        )
    )
    invoice = result.scalar_one_or_none()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found",
        )
    
    return InvoiceResponse.model_validate(invoice)


# Payment method endpoints
@router.get("/organizations/{organization_id}/payment-methods", response_model=PaymentMethodListResponse, summary="List payment methods")
async def list_payment_methods(
    organization_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List organization payment methods."""
    # Check organization admin access
    from app.models.organization import OrganizationMember, OrganizationRole
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view payment methods for this organization",
        )
    
    result = await db.execute(
        select(PaymentMethod).where(
            PaymentMethod.organization_id == organization_id,
        ).order_by(desc(PaymentMethod.is_default), desc(PaymentMethod.created_at))
    )
    payment_methods = result.scalars().all()
    
    return PaymentMethodListResponse(
        payment_methods=[PaymentMethodResponse.model_validate(pm) for pm in payment_methods]
    )


@router.post("/organizations/{organization_id}/payment-methods", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED, summary="Add payment method")
async def add_payment_method(
    organization_id: UUID,
    payment_method_data: PaymentMethodCreate,
    current_user: User = Depends(require_permission("billing:payment_method:create")),
    db: AsyncSession = Depends(get_db),
):
    """Add a payment method to organization."""
    # Check organization admin access
    from app.models.organization import OrganizationMember, OrganizationRole
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage payment methods for this organization",
        )
    
    # TODO: Attach payment method via Stripe
    # This is a placeholder
    
    # If setting as default, unset other defaults
    if payment_method_data.set_as_default:
        result = await db.execute(
            select(PaymentMethod).where(
                PaymentMethod.organization_id == organization_id,
                PaymentMethod.is_default == True,
            )
        )
        for pm in result.scalars().all():
            pm.is_default = False
    
    payment_method = PaymentMethod(
        organization_id=organization_id,
        type=payment_method_data.type,
        brand="Visa",  # Would come from Stripe
        last4="4242",  # Would come from Stripe
        exp_month=12,
        exp_year=2025,
        is_default=payment_method_data.set_as_default,
        metadata_={"stripe_payment_method_id": payment_method_data.token},
    )
    db.add(payment_method)
    await db.commit()
    await db.refresh(payment_method)
    
    return PaymentMethodResponse.model_validate(payment_method)


@router.delete("/organizations/{organization_id}/payment-methods/{payment_method_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete payment method")
async def delete_payment_method(
    organization_id: UUID,
    payment_method_id: UUID,
    current_user: User = Depends(require_permission("billing:payment_method:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a payment method."""
    # Check organization admin access
    from app.models.organization import OrganizationMember, OrganizationRole
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage payment methods for this organization",
        )
    
    result = await db.execute(
        select(PaymentMethod).where(
            PaymentMethod.id == payment_method_id,
            PaymentMethod.organization_id == organization_id,
        )
    )
    payment_method = result.scalar_one_or_none()
    
    if not payment_method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found",
        )
    
    # TODO: Detach from Stripe
    
    await db.delete(payment_method)
    await db.commit()


# Checkout endpoints
@router.post("/checkout", response_model=CheckoutSessionResponse, summary="Create checkout session")
async def create_checkout_session(
    request: CheckoutSessionRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe checkout session for subscription."""
    # Check organization admin access
    from app.models.organization import OrganizationMember, OrganizationRole
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == request.organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage billing for this organization",
        )
    
    # Get plan
    result = await db.execute(
        select(Plan).where(Plan.id == request.plan_id)
    )
    plan = result.scalar_one_or_none()
    
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found",
        )
    
    if plan.price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This plan is free; no checkout is required",
        )
    
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured on this server",
        )
    
    import stripe as stripe_module

    stripe_module.api_key = settings.STRIPE_SECRET_KEY
    
    interval_map = {"monthly": "month", "yearly": "year", "weekly": "week", "daily": "day"}
    raw_interval = plan.interval.value if hasattr(plan.interval, "value") else plan.interval
    interval = interval_map.get(str(raw_interval).lower(), "month")
    
    session = stripe_module.checkout.Session.create(
        mode="subscription",
        line_items=[
            {
                "price_data": {
                    "currency": (plan.currency or "USD").lower(),
                    "unit_amount": plan.price,
                    "product_data": {"name": plan.display_name or plan.name},
                    "recurring": {"interval": interval},
                },
                "quantity": 1,
            }
        ],
        customer_email=current_user.email,
        success_url=request.success_url,
        cancel_url=request.cancel_url,
        metadata={
            "organization_id": str(request.organization_id),
            "plan_id": str(plan.id),
        },
        subscription_data={
            "metadata": {
                "organization_id": str(request.organization_id),
                "plan_id": str(plan.id),
            }
        },
    )
    
    return CheckoutSessionResponse(session_id=session.id, url=session.url)


@router.get("/config", response_model=BillingConfigResponse, summary="Get billing configuration")
async def get_billing_config(
    current_user: User = Depends(get_current_active_user),
):
    """Return public billing configuration for the client."""
    return BillingConfigResponse(
        enabled=bool(settings.STRIPE_SECRET_KEY),
        publishable_key=settings.STRIPE_PUBLISHABLE_KEY,
    )


@router.post("/webhook", summary="Stripe webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (public, signature-verified)."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured",
        )
    
    try:
        event = await construct_webhook_event(payload, signature)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid webhook signature: {exc}",
        )
    
    async with get_session_factory() as db:
        await handle_stripe_event(event, db)
    
    return {"received": True, "type": event.type}


@router.post("/billing-portal", response_model=BillingPortalResponse, summary="Create billing portal session")
async def create_billing_portal_session(
    request: BillingPortalRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe billing portal session."""
    # Check organization admin access
    from app.models.organization import OrganizationMember, OrganizationRole
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == request.organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access billing portal for this organization",
        )
    
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured on this server",
        )
    
    # Look up the organization's Stripe customer id
    result = await db.execute(
        select(Subscription).where(
            Subscription.organization_id == request.organization_id
        )
    )
    subscription = result.scalar_one_or_none()
    customer_id = subscription.stripe_customer_id if subscription else None
    
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer linked yet — complete a checkout first",
        )
    
    import stripe as stripe_module

    stripe_module.api_key = settings.STRIPE_SECRET_KEY
    session = stripe_module.billing_portal.Session.create(
        customer=customer_id,
        return_url=request.return_url,
    )
    
    return BillingPortalResponse(url=session.url)