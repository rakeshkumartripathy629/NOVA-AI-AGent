"""
System prompt construction (personality, personalization, memory).
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from app.models.memory import MemoryItem


def build_base_system_prompt(user, user_message: str = "") -> str:
    """Build the base system prompt personalized for the user."""
    name = getattr(user, "username", None) or str(
        getattr(user, "email", "user") or "user"
    ).split("@")[0]
    today = date.today().isoformat()
    return (
        "You are Nova, a personal AI assistant.\n"
        f"You are helping a user named {name or 'the user'}. Today is {today}.\n"
        "Be concise: answer exactly what the user asked in short, clear sentences. "
        "Prefer a one-line answer or a brief bullet list. "
        "Never add filler, repetition, greetings, or unnecessary details. "
        "Keep answers under ~100 words unless the user explicitly asks for a long or "
        "detailed explanation.\n"
        "Use the 'Remembered context' below when it is relevant, but do not mention it "
        "or list it back. Never contradict a remembered fact unless the user corrects it."
    )


def format_memories_for_prompt(items: List["MemoryItem"]) -> str:
    """Render recalled memories into a prompt block."""
    if not items:
        return ""
    lines = "\n".join(f"- {item.content}" for item in items)
    return f"Remembered context (from this user's memory):\n{lines}"
