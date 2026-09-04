"""
Training Prompts endpoints — list, get, and apply training prompts.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.core.security import get_current_active_user
from app.models.user import User

router = APIRouter()


class TrainingPromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    description: str
    system_prompt: str
    response_style: str
    temperature: float
    tags: list[str]


@router.get("/", response_model=list[TrainingPromptResponse], summary="List all training prompts")
async def list_prompts(
    category: Optional[str] = Query(default=None),
    user: User = Depends(get_current_active_user),
):
    """List all available training prompts."""
    from app.ai.training_prompts import list_all_prompts, get_training_by_category

    if category:
        prompts = get_training_by_category(category)
    else:
        prompts = list_all_prompts()

    return [TrainingPromptResponse.model_validate(p) for p in prompts]


@router.get("/categories", summary="List prompt categories")
async def list_categories(user: User = Depends(get_current_active_user)):
    """Get all training prompt categories."""
    from app.ai.training_prompts import get_all_categories, list_all_prompts

    categories = {}
    for p in list_all_prompts():
        if p.category not in categories:
            categories[p.category] = 0
        categories[p.category] += 1

    return [{"category": k, "count": v} for k, v in categories.items()]


@router.get("/{prompt_id}", response_model=TrainingPromptResponse, summary="Get training prompt")
async def get_prompt(
    prompt_id: str,
    user: User = Depends(get_current_active_user),
):
    """Get a specific training prompt by ID."""
    from app.ai.training_prompts import get_training_prompt

    prompt = get_training_prompt(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Training prompt not found")
    return TrainingPromptResponse.model_validate(prompt)


@router.get("/default/system-prompt", summary="Get default system prompt")
async def get_default_system_prompt(user: User = Depends(get_current_active_user)):
    """Get the default system prompt used for all conversations."""
    from app.ai.training_prompts import DEFAULT_TRAINING

    return {
        "id": DEFAULT_TRAINING.id,
        "name": DEFAULT_TRAINING.name,
        "system_prompt": DEFAULT_TRAINING.system_prompt,
        "temperature": DEFAULT_TRAINING.temperature,
    }
