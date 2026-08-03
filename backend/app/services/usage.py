"""
Usage metering service: records usage events and rolls up aggregates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from app.core.logging import get_logger
from app.models.usage import UsageAggregate, UsageRecord, UsageType

logger = get_logger("services.usage")


def _period(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


async def record_usage(
    *,
    organization_id: UUID,
    type: UsageType,
    quantity: float = 1.0,
    unit: str = "count",
    cost: float = 0.0,
    currency: str = "USD",
    user_id: Optional[UUID] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[UUID] = None,
    model: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> UsageRecord:
    """Record a single metered usage event."""
    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    record = UsageRecord(
        organization_id=organization_id,
        user_id=user_id,
        type=type,
        quantity=quantity,
        unit=unit,
        cost=cost,
        currency=currency,
        reference_type=reference_type,
        reference_id=reference_id,
        model=model,
        metadata_=metadata or {},
    )
    async with session_factory() as db:
        db.add(record)
        await db.commit()
        await db.refresh(record)
    return record


async def aggregate_usage() -> int:
    """Roll up usage records into monthly aggregates for billing."""
    from sqlalchemy import func, literal, select, String

    from app.db.session import get_session_factory

    # Inline literals keep the GROUP BY expression free of bind parameters;
    # Postgres cannot match parameterized expressions between SELECT/GROUP BY
    # when using the extended (prepared) query protocol.
    period_expr = func.substr(func.cast(UsageRecord.created_at, String), literal(1), literal(7))

    session_factory = get_session_factory()
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(
                    UsageRecord.organization_id,
                    UsageRecord.type,
                    period_expr.label("period"),
                    func.sum(UsageRecord.quantity),
                    func.sum(UsageRecord.cost),
                )
                .group_by(UsageRecord.organization_id, UsageRecord.type, period_expr)
            )
        ).all()

        updated = 0
        for org_id, usage_type, period, total_qty, total_cost in rows:
            existing = (
                await db.execute(
                    select(UsageAggregate).where(
                        UsageAggregate.organization_id == org_id,
                        UsageAggregate.period == period,
                        UsageAggregate.type == usage_type,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.total_quantity = total_qty or 0
                existing.total_cost = total_cost or 0
            else:
                db.add(
                    UsageAggregate(
                        organization_id=org_id,
                        period=period,
                        type=usage_type,
                        total_quantity=total_qty or 0,
                        total_cost=total_cost or 0,
                    )
                )
            updated += 1
        await db.commit()
    logger.info("Aggregated usage into %d monthly rows", updated)
    return updated


async def get_org_usage(
    organization_id: UUID,
    period: Optional[str] = None,
    type: Optional[UsageType] = None,
    limit: int = 100,
    offset: int = 0,
) -> list:
    """Return recent usage records for an organization."""
    from sqlalchemy import desc, select

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as db:
        query = select(UsageRecord).where(UsageRecord.organization_id == organization_id)
        if period:
            query = query.where(UsageRecord.created_at >= datetime.strptime(period + "-01", "%Y-%m-%d"))
        if type:
            query = query.where(UsageRecord.type == type)
        records = (
            await db.execute(query.order_by(desc(UsageRecord.created_at)).limit(limit).offset(offset))
        ).scalars().all()
    return [
        {
            "id": str(r.id),
            "type": r.type.value if hasattr(r.type, "value") else str(r.type),
            "quantity": r.quantity,
            "unit": r.unit,
            "cost": r.cost,
            "currency": r.currency,
            "model": r.model,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
