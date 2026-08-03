"""
Workflow management and execution endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import generate_slug, get_current_organization
from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.organization import Organization
from app.models.user import User
from app.models.workflow import Workflow, WorkflowExecution, WorkflowStatus, WorkflowTriggerType

router = APIRouter()


class WorkflowCreate(BaseModel):
    """Workflow create model."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    definition: dict = Field(default_factory=dict)
    trigger_type: WorkflowTriggerType = WorkflowTriggerType.MANUAL
    trigger_config: dict = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    """Workflow update model."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    definition: Optional[dict] = None
    trigger_type: Optional[WorkflowTriggerType] = None
    trigger_config: Optional[dict] = None
    status: Optional[WorkflowStatus] = None


class WorkflowRunRequest(BaseModel):
    """Workflow run request model."""
    input: dict = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    """Workflow response model."""
    id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    definition: dict = {}
    trigger_type: str = "manual"
    trigger_config: dict = {}
    status: str = "draft"
    version: int = 1
    is_template: bool = False
    execution_count: int = 0
    success_count: int = 0
    error_count: int = 0
    last_executed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    """Paginated workflow list."""
    workflows: List[WorkflowResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ExecutionResponse(BaseModel):
    """Workflow execution response model."""
    id: UUID
    workflow_id: UUID
    status: str
    input: dict = {}
    output: Optional[dict] = None
    error: Optional[str] = None
    steps: list = []
    current_step: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    cost: float = 0.0
    created_at: datetime

    class Config:
        from_attributes = True


class ExecutionListResponse(BaseModel):
    """Paginated execution list."""
    executions: List[ExecutionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


async def _get_workflow(db: AsyncSession, workflow_id: UUID, organization: Organization) -> Workflow:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.organization_id == organization.id,
            Workflow.status != WorkflowStatus.ARCHIVED,
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow


@router.get("", response_model=WorkflowListResponse, summary="List workflows")
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[WorkflowStatus] = Query(None, alias="status"),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List workflows in the current organization."""
    query = select(Workflow).where(Workflow.organization_id == organization.id)
    if status_filter:
        query = query.where(Workflow.status == status_filter)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(desc(Workflow.updated_at)).offset((page - 1) * page_size).limit(page_size)
    workflows = (await db.execute(query)).scalars().all()

    return WorkflowListResponse(
        workflows=[WorkflowResponse.model_validate(w) for w in workflows],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED, summary="Create workflow")
async def create_workflow(
    workflow_data: WorkflowCreate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Create a new workflow."""
    base_slug = generate_slug(workflow_data.name)
    slug = base_slug
    counter = 1
    while (
        await db.execute(
            select(Workflow.id).where(Workflow.organization_id == organization.id, Workflow.slug == slug)
        )
    ).scalar_one_or_none():
        counter += 1
        slug = f"{base_slug}-{counter}"

    workflow = Workflow(
        name=workflow_data.name,
        slug=slug,
        description=workflow_data.description,
        definition=workflow_data.definition,
        trigger_type=workflow_data.trigger_type,
        trigger_config=workflow_data.trigger_config,
        status=WorkflowStatus.DRAFT,
        organization_id=organization.id,
        owner_id=current_user.id,
    )
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)
    return WorkflowResponse.model_validate(workflow)


@router.get("/{workflow_id}", response_model=WorkflowResponse, summary="Get workflow")
async def get_workflow(
    workflow_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Get a single workflow."""
    workflow = await _get_workflow(db, workflow_id, organization)
    return WorkflowResponse.model_validate(workflow)


@router.patch("/{workflow_id}", response_model=WorkflowResponse, summary="Update workflow")
async def update_workflow(
    workflow_id: UUID,
    workflow_data: WorkflowUpdate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Update a workflow (bumps version if definition changed)."""
    workflow = await _get_workflow(db, workflow_id, organization)
    update_data = workflow_data.model_dump(exclude_unset=True)
    if "definition" in update_data:
        workflow.version += 1
    for field, value in update_data.items():
        setattr(workflow, field, value)
    await db.commit()
    await db.refresh(workflow)
    return WorkflowResponse.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Archive workflow")
async def delete_workflow(
    workflow_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Archive a workflow."""
    workflow = await _get_workflow(db, workflow_id, organization)
    workflow.status = WorkflowStatus.ARCHIVED
    await db.commit()


@router.post("/{workflow_id}/run", response_model=ExecutionResponse, status_code=status.HTTP_201_CREATED, summary="Run workflow")
async def run_workflow(
    workflow_id: UUID,
    run_request: WorkflowRunRequest,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a workflow execution."""
    workflow = await _get_workflow(db, workflow_id, organization)
    if workflow.status == WorkflowStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workflow must be active to run")

    execution = WorkflowExecution(
        workflow_id=workflow.id,
        status="pending",
        input=run_request.input,
        organization_id=organization.id,
        user_id=current_user.id,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    try:
        from app.workers.tasks import run_workflow as run_workflow_task

        run_workflow_task.delay(str(workflow.id), str(execution.id), str(current_user.id), run_request.input)
    except Exception:  # noqa: BLE001
        execution.status = "queued"
        await db.commit()
        await db.refresh(execution)

    return ExecutionResponse.model_validate(execution)


@router.get("/{workflow_id}/executions", response_model=ExecutionListResponse, summary="List workflow executions")
async def list_executions(
    workflow_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List executions for a workflow."""
    await _get_workflow(db, workflow_id, organization)

    query = select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)
    if status_filter:
        query = query.where(WorkflowExecution.status == status_filter)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(desc(WorkflowExecution.created_at)).offset((page - 1) * page_size).limit(page_size)
    executions = (await db.execute(query)).scalars().all()

    return ExecutionListResponse(
        executions=[ExecutionResponse.model_validate(e) for e in executions],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse, summary="Get workflow execution")
async def get_execution(
    execution_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Get a single workflow execution."""
    result = await db.execute(
        select(WorkflowExecution).where(
            WorkflowExecution.id == execution_id,
            WorkflowExecution.organization_id == organization.id,
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return ExecutionResponse.model_validate(execution)
