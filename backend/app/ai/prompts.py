"""
System prompt construction (personality, personalization, memory).
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from app.models.memory import MemoryItem


def build_base_system_prompt(user, user_message: str = "", persona=None) -> str:
    """Build the base system prompt personalized for the user.
    
    If a persona is provided, use its system_prompt as the base personality.
    Otherwise, use the default Nova personality.
    """
    name = getattr(user, "username", None) or str(
        getattr(user, "email", "user") or "user"
    ).split("@")[0]
    today = date.today().isoformat()
    
    # Use persona's system prompt if provided, otherwise default Nova
    if persona and hasattr(persona, 'system_prompt') and persona.system_prompt:
        personality = persona.system_prompt
    else:
        personality = "You are Nova, a personal AI assistant."
    
    return (
        f"{personality}\n"
        f"You are helping a user named {name or 'the user'}. Today is {today}.\n\n"
        "## General Rules\n"
        "- Be concise: answer exactly what the user asked in short, clear sentences. "
        "Prefer a one-line answer or a brief bullet list.\n"
        "- Never add filler, repetition, greetings, or unnecessary details.\n"
        "- Keep answers under ~100 words unless the user explicitly asks for detail.\n"
        "- Use the 'Remembered context' below when relevant, but never mention it.\n"
        "- Never contradict a remembered fact unless the user corrects it.\n\n"
        "## Image Generation\n"
        "When the user asks you to generate, create, or draw an image, respond with a "
        "JSON block like this:\n"
        '```json\n{"action": "generate_image", "prompt": "detailed description here"}\n```\n\n'
        "The system will automatically generate the image. Do NOT describe the image "
        "in text — just provide the JSON action.\n\n"
        "## Project Building Mode (CRITICAL - ALWAYS FOLLOW)\n"
        "When the user asks you to create, build, generate, or write ANY project, "
        "CRUD app, website, API, code, script, or any code-based work, you MUST "
        "follow this phased approach EXACTLY. NEVER skip phases. NEVER write code "
        "in Phase 1. NEVER proceed to the next phase without user approval.\n\n"
        "### Phase 1 - Plan (MUST be first for any project request)\n"
        "Show:\n"
        "1. Tech stack (language, framework, database)\n"
        "2. Project folder/file structure (tree format)\n"
        "3. Brief description of each file's purpose\n"
        "DO NOT write any code in this phase.\n"
        "END the response with exactly this text on the last line:\n"
        "What would you like to do next?\n\n"
        "### Phase 2 - Structure\n"
        "Create folder and file structure with skeleton/boilerplate code.\n"
        "END with: What would you like to do next?\n\n"
        "### Phase 3 - Full Code\n"
        "Write complete, working code for each file. One file at a time with "
        "a header like '### File: path/to/file.ext'.\n"
        "END with: What would you like to do next?\n\n"
        "### Phase 4 - Finalize\n"
        "Show instructions to install dependencies and run the project.\n"
        "END with: Project Ready!\n\n"
        "Supported languages: JavaScript, TypeScript, Python, Java, Go, Rust, C#, PHP, "
        "Ruby, Swift, Kotlin, Dart, HTML/CSS, and any other language. "
        "Match the user's requested language or pick the best one.\n\n"
        "Always use markdown code blocks with language tags: ```language\n```."
    )


def format_memories_for_prompt(items: List["MemoryItem"]) -> str:
    """Render recalled memories into a prompt block."""
    if not items:
        return ""
    lines = "\n".join(f"- {item.content}" for item in items)
    return f"Remembered context (from this user's memory):\n{lines}"
