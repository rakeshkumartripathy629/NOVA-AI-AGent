"""
Billing models: plans, subscriptions, invoices and payment methods.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class BillingInterval(str, enum.Enum):
    """Billing cadence."""
    MONTHLY = "monthly"
    YEARLY = "yearly"
    WEEKLY = "weekly"
    DAILY = "daily"


class SubscriptionStatus(str, enum.Enum):
    """Subscription lifecycle status."""
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    UNPAID = "unpaid"
    PAUSED = "paused"


class Plan(BaseModel):
    """Pricing plan offered to organizations."""

    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    interval: Mapped[BillingInterval] = mapped_column(default=BillingInterval.MONTHLY, nullable=False)
    features: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    limits: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    is_public: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_popular: Mapped[bool] = mapped_column(default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    trial_days: Mapped[int] = mapped_column(default=0, nullable=False)
    stripe_price_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    stripe_product_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="plan", lazy="select")

    __table_args__ = (Index("ix_plans_active_interval", "is_active", "interval"),)

    def __repr__(self) -> str:
        return f"<Plan(id={self.id}, name={self.name})>"


class Subscription(BaseModel):
    """An organization's active subscription to a plan."""

    __tablename__ = "subscriptions"

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        default=SubscriptionStatus.INCOMPLETE, nullable=False, index=True
    )
    interval: Mapped[BillingInterval] = mapped_column(default=BillingInterval.MONTHLY, nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(nullable=False, index=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False, nullable=False)
    canceled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    trial_start: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    trial_end: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    quantity: Mapped[int] = mapped_column(default=1, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True, index=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="subscriptions", lazy="selectin")
    plan: Mapped["Plan"] = relationship("Plan", back_populates="subscriptions", lazy="selectin")
    invoices: Mapped[List["Invoice"]] = relationship("Invoice", back_populates="subscription", lazy="select")

    __table_args__ = (
        Index("ix_subscriptions_org_status", "organization_id", "status"),
        Index("ix_subscriptions_period_end", "current_period_end"),
    )

    def __repr__(self) -> str:
        return f"<Subscription(id={self.id}, status={self.status})>"


class Invoice(BaseModel):
    """Billing invoice issued to an organization."""

    __tablename__ = "invoices"

    subscription_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    invoice_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    period_start: Mapped[datetime] = mapped_column(nullable=False)
    period_end: Mapped[datetime] = mapped_column(nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    payment_method_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payment_methods.id", ondelete="SET NULL"), nullable=True
    )
    stripe_invoice_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    subscription: Mapped["Subscription"] = relationship("Subscription", back_populates="invoices", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="invoices", lazy="selectin")
    payment_method: Mapped[Optional["PaymentMethod"]] = relationship("PaymentMethod", lazy="selectin")

    __table_args__ = (
        Index("ix_invoices_org_status", "organization_id", "status"),
        Index("ix_invoices_subscription_period", "subscription_id", "period_start"),
    )

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, number={self.invoice_number})>"


class PaymentMethod(BaseModel):
    """Saved payment method for an organization."""

    __tablename__ = "payment_methods"

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), default="card", nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    exp_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exp_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    stripe_payment_method_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True, index=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="payment_methods", lazy="selectin")

    __table_args__ = (Index("ix_payment_methods_org_default", "organization_id", "is_default"),)

    def __repr__(self) -> str:
        return f"<PaymentMethod(id={self.id}, brand={self.brand}, last4={self.last4})>"
