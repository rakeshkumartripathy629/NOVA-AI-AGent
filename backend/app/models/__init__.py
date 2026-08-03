"""
Database models package.

Importing this package registers every model with the shared SQLAlchemy
metadata so that ``Base.metadata.create_all`` and Alembic autogenerate work.
"""
from app.models.base import (
    Base,
    BaseModel,
    MetadataModel,
    SoftDeletableModel,
    SoftDeleteMixin,
    TaggedModel,
    TimestampMixin,
    UUIDMixin,
)
from app.models.user import User, UserRole, UserStatus, AuthProvider
from app.models.organization import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
    OrganizationStatus,
)
from app.models.project import Folder, Project, ProjectMember, ProjectRole, ProjectType
from app.models.conversation import (
    Conversation,
    ConversationBranch,
    ConversationMember,
    ConversationRole,
    ConversationStatus,
)
from app.models.message import Message, MessageRole, MessageStatus, MessageType
from app.models.file import File, FileStatus, FileType
from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseDocument,
    KnowledgeBaseMember,
    KnowledgeBaseRole,
)
from app.models.agent import Agent, AgentExecution, AgentStatus, AgentType
from app.models.workflow import (
    Workflow,
    WorkflowExecution,
    WorkflowStatus,
    WorkflowTriggerType,
)
from app.models.prompt import Prompt, PromptType, PromptVisibility
from app.models.billing import (
    BillingInterval,
    Invoice,
    PaymentMethod,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.models.api_key import APIKey, APIKeyStatus
from app.models.webhook import Webhook, WebhookDelivery, WebhookEvent
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationStatus,
    NotificationType,
)
from app.models.audit_log import AuditAction, AuditLog
from app.models.user_session import OAuthAccount, SessionStatus, UserSession
from app.models.usage import UsageAggregate, UsageRecord, UsageType
from app.models.plugin import Plugin, PluginCategory, PluginInstallation, PluginStatus

__all__ = [
    "Base",
    "BaseModel",
    "MetadataModel",
    "SoftDeletableModel",
    "SoftDeleteMixin",
    "TaggedModel",
    "TimestampMixin",
    "UUIDMixin",
    "User",
    "UserRole",
    "UserStatus",
    "AuthProvider",
    "Organization",
    "OrganizationInvitation",
    "OrganizationMember",
    "OrganizationRole",
    "OrganizationStatus",
    "Folder",
    "Project",
    "ProjectMember",
    "ProjectRole",
    "ProjectType",
    "Conversation",
    "ConversationBranch",
    "ConversationMember",
    "ConversationRole",
    "ConversationStatus",
    "Message",
    "MessageRole",
    "MessageStatus",
    "MessageType",
    "File",
    "FileStatus",
    "FileType",
    "KnowledgeBase",
    "KnowledgeBaseDocument",
    "KnowledgeBaseMember",
    "KnowledgeBaseRole",
    "Agent",
    "AgentExecution",
    "AgentStatus",
    "AgentType",
    "Workflow",
    "WorkflowExecution",
    "WorkflowStatus",
    "WorkflowTriggerType",
    "Prompt",
    "PromptType",
    "PromptVisibility",
    "BillingInterval",
    "Invoice",
    "PaymentMethod",
    "Plan",
    "Subscription",
    "SubscriptionStatus",
    "APIKey",
    "APIKeyStatus",
    "Webhook",
    "WebhookDelivery",
    "WebhookEvent",
    "Notification",
    "NotificationChannel",
    "NotificationPreference",
    "NotificationStatus",
    "NotificationType",
    "AuditAction",
    "AuditLog",
    "OAuthAccount",
    "SessionStatus",
    "UserSession",
    "UsageAggregate",
    "UsageRecord",
    "UsageType",
    "Plugin",
    "PluginCategory",
    "PluginInstallation",
    "PluginStatus",
]
