"""
Billing service: Stripe integration for subscriptions, checkout and webhooks.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.models.billing import Subscription, SubscriptionStatus

logger = get_logger("services.billing")


def _stripe() -> Optional[Any]:
    """Return the Stripe client if configured, else None."""
    if not settings.STRIPE_SECRET_KEY:
        return None
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


async def create_checkout_session(
    *,
    organization_id: UUID,
    plan_stripe_price_id: str,
    customer_email: Optional[str] = None,
    success_url: str,
    cancel_url: str,
    quantity: int = 1,
) -> Optional[Dict[str, Any]]:
    """Create a Stripe Checkout session for a subscription."""
    stripe = _stripe()
    if not stripe:
        logger.warning("Stripe is not configured; checkout unavailable")
        return None

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": plan_stripe_price_id, "quantity": quantity}],
        customer_email=customer_email,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"organization_id": str(organization_id)},
        subscription_data={"metadata": {"organization_id": str(organization_id)}},
    )
    return {"id": session.id, "url": session.url}


async def create_portal_session(organization_id: UUID, customer_id: str, return_url: str) -> Optional[Dict[str, Any]]:
    """Create a Stripe billing portal session."""
    stripe = _stripe()
    if not stripe:
        logger.warning("Stripe is not configured; portal unavailable")
        return None

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
        metadata={"organization_id": str(organization_id)},
    )
    return {"id": session.id, "url": session.url}


async def construct_webhook_event(payload: bytes, signature_header: str) -> Any:
    """Verify and construct a Stripe webhook event."""
    stripe = _stripe()
    if not stripe or not settings.STRIPE_WEBHOOK_SECRET:
        raise ValueError("Stripe webhook handling is not configured")
    return stripe.Webhook.construct_event(
        payload,
        signature_header,
        settings.STRIPE_WEBHOOK_SECRET,
    )


async def handle_stripe_event(event: Any, db) -> Dict[str, str]:
    """Dispatch a verified Stripe webhook event against local rows."""
    from sqlalchemy import select

    from app.models.billing import Plan, Subscription, SubscriptionStatus

    etype = event.type
    data = event.data.object

    if etype == "checkout.session.completed":
        metadata = data.get("metadata", {}) or {}
        org_id = metadata.get("organization_id")
        plan_id = metadata.get("plan_id")
        if not org_id:
            return {"status": "skipped"}

        sub = (
            await db.execute(
                select(Subscription).where(Subscription.organization_id == UUID(org_id))
            )
        ).scalar_one_or_none()

        if sub is None:
            plan = None
            if plan_id:
                plan = (
                    await db.execute(select(Plan).where(Plan.id == UUID(plan_id)))
                ).scalar_one_or_none()
            if plan is None:
                return {"status": "skipped"}
            now = datetime.utcnow()
            sub = Subscription(
                organization_id=UUID(org_id),
                plan_id=plan.id,
                status=SubscriptionStatus.ACTIVE,
                interval=plan.interval,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
                stripe_subscription_id=data.get("subscription"),
                stripe_customer_id=data.get("customer"),
            )
            db.add(sub)
        else:
            sub.status = SubscriptionStatus.ACTIVE
            if plan_id:
                sub.plan_id = UUID(plan_id)
            sub.stripe_subscription_id = data.get("subscription") or sub.stripe_subscription_id
            sub.stripe_customer_id = data.get("customer") or sub.stripe_customer_id

        await db.commit()
        await db.refresh(sub)
        return {"status": "ok", "id": str(sub.id)}

    if etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        stripe_sub = data
        stripe_sub_id = stripe_sub.get("id")
        org_id = (stripe_sub.get("metadata", {}) or {}).get("organization_id")

        subscription = None
        if stripe_sub_id:
            subscription = (
                await db.execute(
                    select(Subscription).where(
                        Subscription.stripe_subscription_id == stripe_sub_id
                    )
                )
            ).scalar_one_or_none()
        if subscription is None and org_id:
            subscription = (
                await db.execute(
                    select(Subscription).where(
                        Subscription.organization_id == UUID(org_id)
                    )
                )
            ).scalar_one_or_none()
        if subscription is None:
            return {"status": "skipped"}

        raw_status = stripe_sub.get("status", "active")
        status = (
            SubscriptionStatus(raw_status)
            if raw_status in SubscriptionStatus._value2member_map_
            else SubscriptionStatus.ACTIVE
        )
        subscription.status = status
        subscription.stripe_subscription_id = stripe_sub_id or subscription.stripe_subscription_id
        subscription.current_period_start = datetime.fromtimestamp(
            stripe_sub.get("current_period_start", 0)
        )
        subscription.current_period_end = datetime.fromtimestamp(
            stripe_sub.get("current_period_end", 0)
        )
        subscription.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end", False))

        if etype == "customer.subscription.deleted":
            subscription.status = SubscriptionStatus.CANCELED
            subscription.canceled_at = datetime.utcnow()

        await db.commit()
        await db.refresh(subscription)
        return {"status": "ok", "id": str(subscription.id)}

    return {"status": "ignored", "type": etype}


async def sync_subscription_from_stripe(event: Any) -> Optional[Dict[str, Any]]:
    """Apply a Stripe subscription event to the local Subscription row."""
    from sqlalchemy import select

    from app.db.session import get_session_factory

    stripe_sub = event.data.object
    org_id = stripe_sub.metadata.get("organization_id")
    if not org_id:
        return None

    session_factory = get_session_factory()
    async with session_factory() as db:
        subscription = (
            await db.execute(
                select(Subscription).where(Subscription.organization_id == UUID(org_id))
            )
        ).scalar_one_or_none()
        if not subscription:
            return None

        status = stripe_sub.get("status", subscription.status.value if hasattr(subscription.status, "value") else subscription.status)
        subscription.status = SubscriptionStatus(status) if status in SubscriptionStatus._value2member_map_ else SubscriptionStatus.ACTIVE
        subscription.stripe_subscription_id = stripe_sub.get("id")
        subscription.current_period_start = datetime.fromtimestamp(stripe_sub.get("current_period_start", 0))
        subscription.current_period_end = datetime.fromtimestamp(stripe_sub.get("current_period_end", 0))
        subscription.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end", False))

        if event.type == "customer.subscription.deleted":
            subscription.status = SubscriptionStatus.CANCELED
            subscription.canceled_at = datetime.utcnow()

        await db.commit()
        await db.refresh(subscription)
        return {"id": str(subscription.id), "status": subscription.status}
