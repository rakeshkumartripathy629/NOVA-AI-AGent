# Nova AI Backend API Reference

Base URL: `http://localhost:8000`

Auth: send `Authorization: Bearer <access_token>` header. Get token via `POST /api/v1/auth/login` (returns `access_token`, `refresh_token`). Optional org override header: `X-Organization-ID`.

Field markers: `*` = required.

---

## GET /api/v1/admin/audit-logs
_List platform audit logs_

  Query params:
     page: integer = 1
     page_size: integer = 50

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/admin/organizations
_List all organizations_

  Query params:
     page: integer = 1
     page_size: integer = 50
     search: any

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/admin/stats
_Platform statistics_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/admin/users
_List all users_

  Query params:
     page: integer = 1
     page_size: integer = 50
     search: any

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/agents
_List agents_

  Query params:
     page: integer = 1
     page_size: integer = 20
     project_id: any
     type: any
     status: any
     search: any

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/agents
_Create agent_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/agents/{agent_id}
_Get agent_

  Path params:
    *agent_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/agents/{agent_id}
_Update agent_

  Path params:
    *agent_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/agents/{agent_id}
_Delete agent_

  Path params:
    *agent_id: string

  204 Successful Response:
      (no body)

---

## POST /api/v1/agents/{agent_id}/execute
_Execute agent_

  Path params:
    *agent_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/agents/{agent_id}/executions
_List agent executions_

  Query params:
     page: integer = 1
     page_size: integer = 20
     status: any

  Path params:
    *agent_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/agents/{agent_id}/executions/{execution_id}
_Get agent execution_

  Path params:
    *agent_id: string
    *execution_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/api-keys
_List API keys_

  Query params:
     page: integer = 1
     page_size: integer = 20
     status: any

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/api-keys
_Create API key_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/api-keys/{key_id}
_Get API key_

  Path params:
    *key_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/api-keys/{key_id}
_Update API key_

  Path params:
    *key_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/api-keys/{key_id}
_Delete API key_

  Path params:
    *key_id: string

  204 Successful Response:
      (no body)

---

## POST /api/v1/api-keys/{key_id}/revoke
_Revoke API key_

  Path params:
    *key_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/audit-logs
_List audit logs_

  Query params:
     page: integer = 1
     page_size: integer = 20
     action: any
     resource_type: any
     user_id: any
     from: any
     to: any

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/audit-logs/{log_id}
_Get audit log entry_

  Path params:
    *log_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/change-password
_Change password_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/forgot-password
_Request password reset_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/login
_User login_

  Request body (application/x-www-form-urlencoded) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/logout
_User logout_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/auth/me
_Get current user_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/auth/oauth/callback/{provider}
_OAuth callback_

  Query params:
    *code: string
     state: any

  Path params:
    *provider: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/auth/oauth/github
_GitHub OAuth login_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/auth/oauth/google
_Google OAuth login_

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/refresh
_Refresh access token_

  Query params:
     refresh_token: any

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/register
_User registration_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/resend-verification
_Resend verification email_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/reset-password
_Reset password_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/switch-organization
_Switch organization_

  Query params:
    *organization_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/auth/verify-email
_Verify email address_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/billing/billing-portal
_Create billing portal session_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/billing/checkout
_Create checkout session_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/billing/organizations/{organization_id}/invoices
_List invoices_

  Query params:
     page: integer = 1
     page_size: integer = 20
     status: any

  Path params:
    *organization_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/billing/organizations/{organization_id}/invoices/{invoice_id}
_Get invoice_

  Path params:
    *organization_id: string
    *invoice_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/billing/organizations/{organization_id}/payment-methods
_List payment methods_

  Path params:
    *organization_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/billing/organizations/{organization_id}/payment-methods
_Add payment method_

  Path params:
    *organization_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/billing/organizations/{organization_id}/payment-methods/{payment_method_id}
_Delete payment method_

  Path params:
    *organization_id: string
    *payment_method_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/billing/organizations/{organization_id}/subscription
_Get organization subscription_

  Path params:
    *organization_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/billing/organizations/{organization_id}/subscription
_Create subscription_

  Path params:
    *organization_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/billing/organizations/{organization_id}/subscription
_Update subscription_

  Path params:
    *organization_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/billing/organizations/{organization_id}/subscription
_Cancel subscription_

  Query params:
     immediately: boolean = False

  Path params:
    *organization_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/billing/plans
_List available plans_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/billing/plans/{plan_id}
_Get plan_

  Path params:
    *plan_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/conversations
_List conversations_

  Query params:
     page: integer = 1
     page_size: integer = 20
     search: any
     project_id: any
     is_archived: any = False

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/conversations
_Create conversation_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/conversations/{conversation_id}
_Get conversation_

  Path params:
    *conversation_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/conversations/{conversation_id}
_Update conversation_

  Path params:
    *conversation_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/conversations/{conversation_id}
_Delete conversation_

  Path params:
    *conversation_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/conversations/{conversation_id}/members
_List conversation members_

  Query params:
     page: integer = 1
     page_size: integer = 20
     role: any

  Path params:
    *conversation_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/conversations/{conversation_id}/members
_Add conversation member_

  Path params:
    *conversation_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/conversations/{conversation_id}/members/{member_id}
_Update conversation member_

  Path params:
    *conversation_id: string
    *member_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/conversations/{conversation_id}/members/{member_id}
_Remove conversation member_

  Path params:
    *conversation_id: string
    *member_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/files
_List files_

  Query params:
     page: integer = 1
     page_size: integer = 20
     conversation_id: any
     knowledge_base_id: any
     file_type: any
     status: any
     search: any

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/files/presigned-url
_Get presigned upload URL_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/files/upload
_Upload file directly_

  Request body (multipart/form-data) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/files/{file_id}
_Get file_

  Path params:
    *file_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/files/{file_id}
_Update file metadata_

  Path params:
    *file_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/files/{file_id}
_Delete file_

  Path params:
    *file_id: string

  204 Successful Response:
      (no body)

---

## POST /api/v1/files/{file_id}/complete
_Complete upload_

  Path params:
    *file_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/files/{file_id}/download
_Download file_

  Path params:
    *file_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/health/live
_Liveness probe_

  200 Successful Response:
      application/json:
        any object

---

## GET /api/v1/health/ready
_Readiness probe_

  200 Successful Response:
      application/json:
        any object

---

## GET /api/v1/knowledge-bases
_List knowledge bases_

  Query params:
     page: integer = 1
     page_size: integer = 20
     project_id: any
     search: any

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/knowledge-bases
_Create knowledge base_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/knowledge-bases/{kb_id}
_Get knowledge base_

  Path params:
    *kb_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/knowledge-bases/{kb_id}
_Update knowledge base_

  Path params:
    *kb_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/knowledge-bases/{kb_id}
_Delete knowledge base_

  Path params:
    *kb_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/knowledge-bases/{kb_id}/documents
_List documents_

  Query params:
     page: integer = 1
     page_size: integer = 20
     status: any
     search: any

  Path params:
    *kb_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/knowledge-bases/{kb_id}/documents
_Create document_

  Path params:
    *kb_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}
_Get document_

  Path params:
    *kb_id: string
    *doc_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}
_Update document_

  Path params:
    *kb_id: string
    *doc_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}
_Delete document_

  Path params:
    *kb_id: string
    *doc_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/knowledge-bases/{kb_id}/members
_List knowledge base members_

  Path params:
    *kb_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/knowledge-bases/{kb_id}/members
_Add knowledge base member_

  Query params:
    *user_id: string
     role: KnowledgeBaseRole = viewer

  Path params:
    *kb_id: string

  201 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/knowledge-bases/{kb_id}/members/{member_id}
_Remove knowledge base member_

  Path params:
    *kb_id: string
    *member_id: string

  204 Successful Response:
      (no body)

---

## POST /api/v1/knowledge-bases/{kb_id}/search
_Search knowledge base_

  Path params:
    *kb_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/messages/conversations/{conversation_id}/messages
_List messages_

  Query params:
     page: integer = 1
     page_size: integer = 50
     before_id: any
     after_id: any

  Path params:
    *conversation_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/messages/conversations/{conversation_id}/messages
_Create message_

  Path params:
    *conversation_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/messages/conversations/{conversation_id}/messages/stream
_Stream AI response_

  Path params:
    *conversation_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/messages/conversations/{conversation_id}/messages/{message_id}
_Get message_

  Path params:
    *conversation_id: string
    *message_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/messages/conversations/{conversation_id}/messages/{message_id}
_Update message_

  Path params:
    *conversation_id: string
    *message_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/messages/conversations/{conversation_id}/messages/{message_id}
_Delete message_

  Path params:
    *conversation_id: string
    *message_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/notifications
_List notifications_

  Query params:
     page: integer = 1
     page_size: integer = 20
     status: any
     unread_only: boolean = False

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/notifications/preferences
_Get notification preferences_

  200 Successful Response:
      application/json:
        (no fields)

---

## PUT /api/v1/notifications/preferences
_Update notification preferences_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/notifications/read-all
_Mark all notifications as read_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/notifications/unread-count
_Unread notification count_

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/notifications/{notification_id}
_Delete notification_

  Path params:
    *notification_id: string

  204 Successful Response:
      (no body)

---

## PATCH /api/v1/notifications/{notification_id}/read
_Mark notification as read_

  Path params:
    *notification_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/organizations
_List organizations_

  Query params:
     page: integer = 1
     page_size: integer = 20
     search: any

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/organizations
_Create organization_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/organizations/{org_id}
_Get organization_

  Path params:
    *org_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/organizations/{org_id}
_Update organization_

  Path params:
    *org_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/organizations/{org_id}
_Delete organization_

  Path params:
    *org_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/organizations/{org_id}/members
_List organization members_

  Query params:
     page: integer = 1
     page_size: integer = 20
     role: any
     status: any

  Path params:
    *org_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/organizations/{org_id}/members/invite
_Invite member_

  Path params:
    *org_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/organizations/{org_id}/members/{member_id}
_Update member_

  Path params:
    *org_id: string
    *member_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/organizations/{org_id}/members/{member_id}
_Remove member_

  Path params:
    *org_id: string
    *member_id: string

  204 Successful Response:
      (no body)

---

## POST /api/v1/organizations/{org_id}/members/{member_id}/resend-invite
_Resend invitation_

  Path params:
    *org_id: string
    *member_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/projects
_List projects_

  Query params:
     page: integer = 1
     page_size: integer = 20
     search: any
     organization_id: any
     is_archived: any = False

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/projects
_Create project_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/projects/{project_id}
_Get project_

  Path params:
    *project_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/projects/{project_id}
_Update project_

  Path params:
    *project_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/projects/{project_id}
_Delete project_

  Path params:
    *project_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/projects/{project_id}/members
_List project members_

  Query params:
     page: integer = 1
     page_size: integer = 20
     role: any

  Path params:
    *project_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/projects/{project_id}/members
_Add project member_

  Path params:
    *project_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/projects/{project_id}/members/{member_id}
_Update project member_

  Path params:
    *project_id: string
    *member_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/projects/{project_id}/members/{member_id}
_Remove project member_

  Path params:
    *project_id: string
    *member_id: string

  204 Successful Response:
      (no body)

---

## POST /api/v1/search
_Search across the workspace_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/subscriptions/cancel
_Cancel subscription_

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/subscriptions/change
_Change subscription plan_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/subscriptions/current
_Get current subscription_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/subscriptions/plans
_List public plans_

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/subscriptions/resume
_Resume subscription_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/subscriptions/usage
_Get usage summary_

  Query params:
     period: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/users
_List users_

  Query params:
     page: integer = 1
     page_size: integer = 20
     search: any
     role: any
     status: any

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/users/me
_Get current user profile_

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/users/me
_Update current user profile_

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/users/{user_id}
_Get user by ID_

  Path params:
    *user_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/users/{user_id}
_Update user_

  Path params:
    *user_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/users/{user_id}
_Delete user_

  Path params:
    *user_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/users/{user_id}/organizations
_Get user's organizations_

  Path params:
    *user_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/users/{user_id}/role
_Update user role_

  Path params:
    *user_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/users/{user_id}/status
_Update user status_

  Path params:
    *user_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/vision/analyze
_Analyze an image_

  Request body (multipart/form-data) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/voice/synthesize
_Synthesize speech from text_

  Request body (application/x-www-form-urlencoded) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/voice/transcribe
_Transcribe audio to text_

  Request body (multipart/form-data) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/webhooks
_List webhooks_

  Query params:
     page: integer = 1
     page_size: integer = 20

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/webhooks
_Create webhook_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/webhooks/{webhook_id}
_Get webhook_

  Path params:
    *webhook_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/webhooks/{webhook_id}
_Update webhook_

  Path params:
    *webhook_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/webhooks/{webhook_id}
_Delete webhook_

  Path params:
    *webhook_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/webhooks/{webhook_id}/deliveries
_List webhook deliveries_

  Query params:
     page: integer = 1
     page_size: integer = 20

  Path params:
    *webhook_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/webhooks/{webhook_id}/deliveries/{delivery_id}
_Get webhook delivery_

  Path params:
    *webhook_id: string
    *delivery_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/webhooks/{webhook_id}/rotate-secret
_Rotate webhook secret_

  Path params:
    *webhook_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/webhooks/{webhook_id}/test
_Send a test webhook delivery_

  Path params:
    *webhook_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/workflows
_List workflows_

  Query params:
     page: integer = 1
     page_size: integer = 20
     status: any

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/workflows
_Create workflow_

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/workflows/executions/{execution_id}
_Get workflow execution_

  Path params:
    *execution_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /api/v1/workflows/{workflow_id}
_Get workflow_

  Path params:
    *workflow_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## PATCH /api/v1/workflows/{workflow_id}
_Update workflow_

  Path params:
    *workflow_id: string

  Request body (application/json) (required):
    (no fields)

  200 Successful Response:
      application/json:
        (no fields)

---

## DELETE /api/v1/workflows/{workflow_id}
_Archive workflow_

  Path params:
    *workflow_id: string

  204 Successful Response:
      (no body)

---

## GET /api/v1/workflows/{workflow_id}/executions
_List workflow executions_

  Query params:
     page: integer = 1
     page_size: integer = 20
     status: any

  Path params:
    *workflow_id: string

  200 Successful Response:
      application/json:
        (no fields)

---

## POST /api/v1/workflows/{workflow_id}/run
_Run workflow_

  Path params:
    *workflow_id: string

  Request body (application/json) (required):
    (no fields)

  201 Successful Response:
      application/json:
        (no fields)

---

## GET /health
_Health Check_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /health/live
_Liveness Check_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /health/ready
_Readiness Check_

  200 Successful Response:
      application/json:
        (no fields)

---

## GET /metrics
_Metrics_

  200 Successful Response:
      application/json:
        (no fields)

---
