"""
API v1 router with all endpoints.
"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    users,
    organizations,
    projects,
    conversations,
    messages,
    files,
    knowledge_bases,
    agents,
    workflows,
    billing,
    subscriptions,
    api_keys,
    webhooks,
    notifications,
    audit_logs,
    health,
    search,
    voice,
    vision,
    admin,
)

api_router = APIRouter()

# Authentication
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Users
api_router.include_router(users.router, prefix="/users", tags=["Users"])

# Organizations
api_router.include_router(organizations.router, prefix="/organizations", tags=["Organizations"])
api_router.include_router(organizations.alias_router, prefix="/organization", tags=["Organizations"])

# Projects
api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])

# Conversations
api_router.include_router(conversations.router, prefix="/conversations", tags=["Conversations"])

# Messages
api_router.include_router(messages.router, prefix="/messages", tags=["Messages"])

# Files
api_router.include_router(files.router, prefix="/files", tags=["Files"])

# Knowledge Bases
api_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["Knowledge Bases"])

# Agents
api_router.include_router(agents.router, prefix="/agents", tags=["Agents"])

# Workflows
api_router.include_router(workflows.router, prefix="/workflows", tags=["Workflows"])

# Billing
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"])

# Subscriptions
api_router.include_router(subscriptions.router, prefix="/subscriptions", tags=["Subscriptions"])

# API Keys
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["API Keys"])

# Webhooks
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])

# Notifications
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])

# Audit Logs
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["Audit Logs"])

# Health
api_router.include_router(health.router, prefix="/health", tags=["Health"])

# Search
api_router.include_router(search.router, prefix="/search", tags=["Search"])

# Voice
api_router.include_router(voice.router, prefix="/voice", tags=["Voice"])

# Vision
api_router.include_router(vision.router, prefix="/vision", tags=["Vision"])

# Admin
api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])