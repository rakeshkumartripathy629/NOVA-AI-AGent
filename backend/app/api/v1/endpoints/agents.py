"""
AI Agent management endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import generate_slug, get_current_organization
from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.agent import Agent, AgentExecution, AgentStatus, AgentType
from app.models.conversation import ConversationMember
from app.models.organization import Organization, OrganizationMember
from app.models.project import ProjectMember
from app.models.user import User

router = APIRouter()


# Request/Response Models
class AgentCreate(BaseModel):
    """Agent create model."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    type: AgentType = AgentType.CHAT
    project_id: Optional[UUID] = None
    model: str = "gpt-4"
    model_provider: str = "openai"
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1, le=100000)
    system_prompt: Optional[str] = None
    tools: Optional[List[dict]] = None
    knowledge_base_ids: Optional[List[UUID]] = None
    settings: Optional[dict] = None


class AgentUpdate(BaseModel):
    """Agent update model."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    type: Optional[AgentType] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1, le=100000)
    system_prompt: Optional[str] = None
    tools: Optional[List[dict]] = None
    knowledge_base_ids: Optional[List[UUID]] = None
    settings: Optional[dict] = None
    status: Optional[AgentStatus] = None


class AgentResponse(BaseModel):
    """Agent response model."""
    id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    type: str
    status: str
    project_id: Optional[UUID] = None
    organization_id: UUID
    owner_id: UUID
    model: str
    model_provider: str
    temperature: float
    max_tokens: Optional[int] = None
    system_prompt: Optional[str] = None
    tools: List[dict] = []
    knowledge_base_ids: List[UUID] = []
    execution_count: int = 0
    total_tokens: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentListResponse(BaseModel):
    """Agent list response model."""
    agents: List[AgentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class AgentExecutionCreate(BaseModel):
    """Agent execution create model."""
    input: dict
    conversation_id: Optional[UUID] = None


class AgentExecutionResponse(BaseModel):
    """Agent execution response model."""
    id: UUID
    agent_id: UUID
    user_id: UUID
    organization_id: UUID
    conversation_id: Optional[UUID] = None
    input: dict
    output: Optional[dict] = None
    status: str
    error: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgentExecutionListResponse(BaseModel):
    """Agent execution list response model."""
    executions: List[AgentExecutionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


async def _get_agent(db: AsyncSession, agent_id: UUID) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.is_deleted.is_(False))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


async def _require_agent_access(db: AsyncSession, agent: Agent, user: User) -> None:
    """Raise 403 unless the user can access the agent."""
    if agent.owner_id == user.id:
        return
    if agent.organization_id:
        member = (
            await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == agent.organization_id,
                    OrganizationMember.user_id == user.id,
                    OrganizationMember.status == "active",
                )
            )
        ).scalar_one_or_none()
        if member:
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this agent")


# Endpoints
@router.get("", response_model=AgentListResponse, summary="List agents")
async def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[UUID] = Query(None),
    type_filter: Optional[AgentType] = Query(None, alias="type"),
    status_filter: Optional[AgentStatus] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List agents in the organization."""
    query = select(Agent).where(
        Agent.organization_id == organization.id,
        Agent.is_deleted.is_(False),
    )

    if current_user.role.value != "super_admin":
        query = query.where(
            or_(
                Agent.owner_id == current_user.id,
                Agent.project_id.in_(
                    select(ProjectMember.project_id).where(
                        ProjectMember.user_id == current_user.id,
                        ProjectMember.project_id.is_not(None),
                    )
                ),
            )
        )

    if project_id:
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this project")
        query = query.where(Agent.project_id == project_id)

    if type_filter:
        query = query.where(Agent.type == type_filter)

    if status_filter:
        query = query.where(Agent.status == status_filter)

    if search:
        query = query.where(
            or_(
                Agent.name.ilike(f"%{search}%"),
                Agent.description.ilike(f"%{search}%"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(query.subquery()))

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(desc(Agent.updated_at))
    agents = (await db.execute(query)).scalars().all()

    return AgentListResponse(
        agents=[AgentResponse.model_validate(a) for a in agents],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED, summary="Create agent")
async def create_agent(
    agent_data: AgentCreate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent."""
    if agent_data.project_id:
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == agent_data.project_id,
                ProjectMember.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this project")

    base_slug = generate_slug(agent_data.name)
    slug = base_slug
    counter = 1
    while (
        await db.execute(
            select(Agent.id).where(
                Agent.slug == slug,
                Agent.organization_id == organization.id,
            )
        )
    ).scalar_one_or_none():
        counter += 1
        slug = f"{base_slug}-{counter}"

    agent = Agent(
        name=agent_data.name,
        slug=slug,
        description=agent_data.description,
        type=agent_data.type,
        project_id=agent_data.project_id,
        owner_id=current_user.id,
        organization_id=organization.id,
        model=agent_data.model,
        model_provider=agent_data.model_provider,
        temperature=agent_data.temperature,
        max_tokens=agent_data.max_tokens,
        system_prompt=agent_data.system_prompt or "You are a helpful AI assistant.",
        tools=agent_data.tools or [],
        knowledge_base_ids=agent_data.knowledge_base_ids or [],
        status=AgentStatus.ACTIVE,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    return AgentResponse.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentResponse, summary="Get agent")
async def get_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agent by ID."""
    agent = await _get_agent(db, agent_id)
    await _require_agent_access(db, agent, current_user)
    return AgentResponse.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentResponse, summary="Update agent")
async def update_agent(
    agent_id: UUID,
    agent_data: AgentUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update agent."""
    agent = await _get_agent(db, agent_id)
    if agent.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this agent")

    for field, value in agent_data.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete agent")
async def delete_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete agent (owner only)."""
    agent = await _get_agent(db, agent_id)
    if agent.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can delete the agent")

    agent.is_deleted = True
    agent.deleted_at = datetime.utcnow()
    await db.commit()


# Execution endpoints
@router.post("/{agent_id}/execute", response_model=AgentExecutionResponse, status_code=status.HTTP_201_CREATED, summary="Execute agent")
async def execute_agent(
    agent_id: UUID,
    execution_data: AgentExecutionCreate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Execute an agent."""
    agent = await _get_agent(db, agent_id)
    await _require_agent_access(db, agent, current_user)

    if agent.status != AgentStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent is not active")

    if execution_data.conversation_id:
        result = await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == execution_data.conversation_id,
                ConversationMember.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this conversation")

    execution = AgentExecution(
        agent_id=agent_id,
        agent_version=agent.version,
        user_id=current_user.id,
        organization_id=organization.id,
        conversation_id=execution_data.conversation_id,
        input=execution_data.input,
        status="pending",
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    # TODO: Execute agent asynchronously via Celery

    return AgentExecutionResponse.model_validate(execution)


@router.get("/{agent_id}/executions", response_model=AgentExecutionListResponse, summary="List agent executions")
async def list_agent_executions(
    agent_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List executions for an agent."""
    agent = await _get_agent(db, agent_id)
    await _require_agent_access(db, agent, current_user)

    query = select(AgentExecution).where(AgentExecution.agent_id == agent_id)

    if status_filter:
        query = query.where(AgentExecution.status == status_filter)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(desc(AgentExecution.created_at))
    executions = (await db.execute(query)).scalars().all()

    return AgentExecutionListResponse(
        executions=[AgentExecutionResponse.model_validate(e) for e in executions],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.get("/{agent_id}/executions/{execution_id}", response_model=AgentExecutionResponse, summary="Get agent execution")
async def get_agent_execution(
    agent_id: UUID,
    execution_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get agent execution by ID."""
    agent = await _get_agent(db, agent_id)
    await _require_agent_access(db, agent, current_user)

    result = await db.execute(
        select(AgentExecution).where(
            AgentExecution.id == execution_id,
            AgentExecution.agent_id == agent_id,
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    return AgentExecutionResponse.model_validate(execution)
