const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';

export class ApiError extends Error {
  status: number;
  details: string;

  constructor(status: number, message: string, details = '') {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export function getToken(): string | null {
  return localStorage.getItem('nova_access_token');
}

export function setToken(token: string | null): void {
  if (token) {
    localStorage.setItem('nova_access_token', token);
  } else {
    localStorage.removeItem('nova_access_token');
  }
}

let refreshPromise: Promise<string | null> | null = null;

export async function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const resp = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json' },
        });
        if (!resp.ok) {
          setToken(null);
          return null;
        }
        const data = (await resp.json()) as { access_token?: string };
        const token = data.access_token ?? null;
        setToken(token);
        return token;
      } catch {
        setToken(null);
        return null;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };
  if (options.body && typeof options.body === 'string') {
    headers['Content-Type'] = 'application/json';
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const doFetch = (): Promise<Response> =>
    fetch(`${API_BASE}${path}`, { ...options, headers });

  let resp = await doFetch();
  if (resp.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      headers.Authorization = `Bearer ${newToken}`;
      resp = await doFetch();
    }
  }
  if (!resp.ok) {
    let message = `Request failed (${resp.status})`;
    let details = '';
    try {
      const body = await resp.json();
      message = body.detail ?? body.error?.message ?? message;
      details = body.error?.details ? JSON.stringify(body.error.details) : '';
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, message, details);
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const form = new URLSearchParams();
  form.set('username', email);
  form.set('password', password);
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
    body: form,
  });
  if (!resp.ok) {
    let message = `Login failed (${resp.status})`;
    try {
      const body = await resp.json();
      message = body.detail ?? message;
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, message);
  }
  return (await resp.json()) as AuthResponse;
}

export async function register(input: RegisterInput): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function forgotPassword(email: string): Promise<{ message: string }> {
  return request<{ message: string }>('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<{ message: string }> {
  return request<{ message: string }>('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password: newPassword, confirm_password: newPassword }),
  });
}

export async function fetchMe(): Promise<User> {
  return request<User>('/auth/me');
}

export async function logout(): Promise<void> {
  try {
    await request<void>('/auth/logout', { method: 'POST' });
  } catch {
    /* ignore — local token cleared below regardless */
  } finally {
    setToken(null);
  }
}

// ---- Conversations ----

export async function listConversations(): Promise<ConversationListResponse> {
  return request<ConversationListResponse>('/conversations');
}

export async function createConversation(title: string): Promise<Conversation> {
  return request<Conversation>('/conversations', {
    method: 'POST',
    body: JSON.stringify({ title, is_private: false }),
  });
}

export async function listMessages(
  conversationId: string,
  page = 1,
  pageSize = 100,
): Promise<MessageListResponse> {
  return request<MessageListResponse>(
    `/messages/conversations/${conversationId}/messages?page=${page}&page_size=${pageSize}`,
  );
}

export async function updateMessage(
  conversationId: string,
  messageId: string,
  content: string,
): Promise<Message> {
  return request<Message>(`/messages/conversations/${conversationId}/messages/${messageId}`, {
    method: 'PATCH',
    body: JSON.stringify({ content }),
  });
}

export async function createMessage(
  conversationId: string,
  input: { role: string; content: string; type?: string },
): Promise<Message> {
  return request<Message>(`/messages/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ role: input.role, content: input.content, type: input.type ?? 'text' }),
  });
}

export async function deleteMessage(conversationId: string, messageId: string): Promise<void> {
  return request<void>(`/messages/conversations/${conversationId}/messages/${messageId}`, {
    method: 'DELETE',
  });
}

export async function renameConversation(id: string, title: string): Promise<Conversation> {
  return request<Conversation>(`/conversations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(id: string): Promise<void> {
  return request<void>(`/conversations/${id}`, { method: 'DELETE' });
}

export async function streamChat(
  conversationId: string,
  content: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
  knowledgeBaseIds?: string[],
  useWebSearch = false,
  agentId?: string,
  model?: string,
  providerName?: string,
): Promise<void> {
  const token = getToken();
  const body: Record<string, unknown> = { content, stream: true };
  if (knowledgeBaseIds && knowledgeBaseIds.length > 0) {
    body.knowledge_base_ids = knowledgeBaseIds;
  }
  if (useWebSearch) {
    body.use_web_search = true;
  }
  if (agentId) {
    body.agent_id = agentId;
  }
  if (model) {
    body.model = model;
  }
  if (providerName) {
    body.provider_name = providerName;
  }
  const doStream = (authToken: string | null): Promise<Response> =>
    fetch(`${API_BASE}/messages/conversations/${conversationId}/messages/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      body: JSON.stringify(body),
      signal,
    });

  let resp = await doStream(token);
  if (resp.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      resp = await doStream(newToken);
    }
  }
  if (!resp.ok || !resp.body) {
    throw new ApiError(resp.status, `Stream failed (${resp.status})`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        onEvent(JSON.parse(payload) as ChatEvent);
      } catch {
        /* skip malformed frame */
      }
    }
  }
}

// ---- Agents ----

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  model_provider: string;
  model: string;
  temperature: number;
  system_prompt?: string | null;
  knowledge_base_ids: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentInput {
  name: string;
  description?: string;
  model_provider: string;
  model?: string;
  temperature?: number;
  system_prompt?: string;
  knowledge_base_ids?: string[];
}

export async function listAgents(): Promise<Agent[]> {
  const resp = await request<{ agents: Agent[] }>('/agents');
  return resp.agents ?? [];
}

export async function createAgent(input: AgentInput): Promise<Agent> {
  return request<Agent>('/agents', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function updateAgent(id: string, input: Partial<AgentInput>): Promise<Agent> {
  return request<Agent>(`/agents/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export async function deleteAgent(id: string): Promise<void> {
  await request<unknown>(`/agents/${id}`, { method: 'DELETE' });
}

// ---- Projects ----

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  organization_id: string;
  owner_id: string;
  settings: Record<string, unknown>;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export async function listProjects(): Promise<Project[]> {
  const resp = await request<{ projects: Project[] }>('/projects');
  return resp.projects ?? [];
}

export async function createProject(
  name: string,
  description?: string,
  organizationId?: string,
): Promise<Project> {
  return request<Project>('/projects', {
    method: 'POST',
    body: JSON.stringify({ name, description, organization_id: organizationId }),
  });
}

export async function updateProject(
  id: string,
  input: { name?: string; description?: string; is_archived?: boolean },
): Promise<Project> {
  return request<Project>(`/projects/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export async function deleteProject(id: string): Promise<void> {
  await request<unknown>(`/projects/${id}`, { method: 'DELETE' });
}

// ---- Global search ----

export interface SearchHit {
  type: string;
  id: string;
  title: string;
  snippet?: string;
  url?: string;
  score: number;
}

export async function searchWorkspace(
  query: string,
  scope?: string[],
  limit = 25,
): Promise<SearchHit[]> {
  const resp = await request<{ results: SearchHit[] }>('/search', {
    method: 'POST',
    body: JSON.stringify({ query, scope, limit }),
  });
  return resp.results ?? [];
}

// ---- Voice ----

export async function transcribeVoice(file: File): Promise<string> {
  const form = new FormData();
  form.append('file', file);
  const token = getToken();
  const resp = await fetch(`${API_BASE}/voice/transcribe`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) {
    let message = `Transcription failed (${resp.status})`;
    try {
      const body = await resp.json();
      message = body.detail ?? message;
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, message);
  }
  const data = (await resp.json()) as { text: string };
  return data.text ?? '';
}

export async function synthesizeVoice(text: string): Promise<Blob> {
  const form = new FormData();
  form.append('text', text);
  const token = getToken();
  const resp = await fetch(`${API_BASE}/voice/synthesize`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) {
    let message = `TTS failed (${resp.status})`;
    try {
      const body = await resp.json();
      message = body.detail ?? message;
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, message);
  }
  const data = (await resp.json()) as { audio_base64: string };
  const bin = atob(data.audio_base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: 'audio/mpeg' });
}

export async function analyzeImage(file: File, prompt?: string): Promise<string> {
  const form = new FormData();
  form.append('file', file);
  if (prompt) form.append('prompt', prompt);
  const token = getToken();
  const resp = await fetch(`${API_BASE}/vision/analyze`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) {
    let message = `Vision failed (${resp.status})`;
    try {
      const body = await resp.json();
      message = body.detail ?? message;
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, message);
  }
  const data = (await resp.json()) as { description: string };
  return data.description ?? '';
}

// ---- Conversation helpers (pin / folder / summary / share) ----

export async function updateConversation(
  id: string,
  patch: {
    title?: string;
    is_archived?: boolean;
    is_pinned?: boolean;
    folder?: string | null;
  },
): Promise<Conversation> {
  return request<Conversation>(`/conversations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export async function suggestFollowups(conversationId: string): Promise<string[]> {
  const resp = await request<{ suggestions: string[] }>(
    `/messages/conversations/${conversationId}/followups`,
    { method: 'POST' },
  );
  return resp.suggestions ?? [];
}

export async function summarizeConversation(conversationId: string): Promise<string> {
  const resp = await request<{ summary: string }>(
    `/conversations/${conversationId}/summarize`,
    { method: 'POST' },
  );
  return resp.summary ?? '';
}

export async function shareConversation(
  conversationId: string,
): Promise<{ url: string; token: string }> {
  return request<{ url: string; token: string }>(
    `/conversations/${conversationId}/share`,
    { method: 'POST' },
  );
}

export interface PublicSharedMessage {
  id: string;
  role: string;
  content: string;
  model?: string | null;
  created_at?: string | null;
}

export interface PublicShareData {
  title: string;
  messages: PublicSharedMessage[];
}

export async function getSharedConversation(
  token: string,
): Promise<PublicShareData> {
  const resp = await fetch(`${API_BASE}/conversations/public/${encodeURIComponent(token)}`, {
    headers: { Accept: 'application/json' },
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, `Shared conversation not found (${resp.status})`);
  }
  return (await resp.json()) as PublicShareData;
}

// ---- Notifications ----

export interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  status: string;
  priority: number;
  reference_type?: string | null;
  reference_id?: string | null;
  action_url?: string | null;
  action_label?: string | null;
  read_at?: string | null;
  created_at: string;
}

export async function listNotifications(): Promise<Notification[]> {
  const resp = await request<{ notifications: Notification[] }>('/notifications');
  return resp.notifications ?? [];
}

export async function unreadCount(): Promise<number> {
  const resp = await request<{ count: number }>('/notifications/unread-count');
  return resp.count ?? 0;
}

export async function markNotificationRead(id: string): Promise<Notification> {
  return request<Notification>(`/notifications/${id}/read`, { method: 'PATCH' });
}

export async function markAllNotificationsRead(): Promise<void> {
  await request<unknown>('/notifications/read-all', { method: 'POST' });
}

// ---- API keys ----

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  status: string;
  scopes: string[];
  expires_at?: string | null;
  last_used_at?: string | null;
  usage_count: number;
  created_at: string;
}

export async function listApiKeys(): Promise<ApiKey[]> {
  const resp = await request<{ api_keys: ApiKey[] }>('/api-keys');
  return resp.api_keys ?? [];
}

export async function createApiKey(
  name: string,
  scopes?: string[],
): Promise<ApiKey & { key?: string }> {
  return request<ApiKey & { key?: string }>('/api-keys', {
    method: 'POST',
    body: JSON.stringify({ name, scopes: scopes ?? ['chat'] }),
  });
}

export async function deleteApiKey(keyId: string): Promise<void> {
  await request<unknown>(`/api-keys/${keyId}`, { method: 'DELETE' });
}

// ---- Webhooks ----

export interface Webhook {
  id: string;
  name: string;
  url: string;
  events: string[];
  is_active: boolean;
  retry_count: number;
  timeout_seconds: number;
  last_triggered_at?: string | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  failure_count: number;
  created_at: string;
}

export async function listWebhooks(): Promise<Webhook[]> {
  const resp = await request<{ webhooks: Webhook[] }>('/webhooks');
  return resp.webhooks ?? [];
}

export async function createWebhook(input: {
  name: string;
  url: string;
  events?: string[];
}): Promise<Webhook & { secret?: string }> {
  return request<Webhook & { secret?: string }>('/webhooks', {
    method: 'POST',
    body: JSON.stringify({ ...input, events: input.events ?? [] }),
  });
}

export async function deleteWebhook(id: string): Promise<void> {
  await request<unknown>(`/webhooks/${id}`, { method: 'DELETE' });
}

export async function testWebhook(id: string): Promise<unknown> {
  return request<unknown>(`/webhooks/${id}/test`, { method: 'POST' });
}

// ---- Workflows ----

export interface Workflow {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  definition: Record<string, unknown>;
  trigger_type: string;
  status: string;
  execution_count: number;
  success_count: number;
  error_count: number;
  last_executed_at?: string | null;
  created_at: string;
}

export async function listWorkflows(): Promise<Workflow[]> {
  const resp = await request<{ workflows: Workflow[] }>('/workflows');
  return resp.workflows ?? [];
}

export async function createWorkflow(
  name: string,
  description?: string,
): Promise<Workflow> {
  return request<Workflow>('/workflows', {
    method: 'POST',
    body: JSON.stringify({ name, description, definition: {} }),
  });
}

export async function deleteWorkflow(id: string): Promise<void> {
  await request<unknown>(`/workflows/${id}`, { method: 'DELETE' });
}

export async function runWorkflow(
  id: string,
  input: Record<string, unknown> = {},
): Promise<{ id: string; status: string }> {
  return request<{ id: string; status: string }>(`/workflows/${id}/run`, {
    method: 'POST',
    body: JSON.stringify({ input }),
  });
}

// ---- Knowledge bases & files ----

export async function listKnowledgeBases(): Promise<KnowledgeBaseListResponse> {
  return request<KnowledgeBaseListResponse>('/knowledge-bases');
}

export async function createKnowledgeBase(
  name: string,
  description?: string,
): Promise<KnowledgeBase> {
  return request<KnowledgeBase>('/knowledge-bases', {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  });
}

export async function deleteKnowledgeBase(kbId: string): Promise<void> {
  await request<unknown>(`/knowledge-bases/${kbId}`, { method: 'DELETE' });
}

export interface KnowledgeBaseDocument {
  id: string;
  knowledge_base_id: string;
  title: string;
  content?: string | null;
  source_type: string;
  source_url?: string | null;
  source_metadata: Record<string, unknown>;
  status: string;
  chunk_count: number;
  uploaded_by: string;
  created_at: string;
}

export async function listKnowledgeBaseDocuments(
  kbId: string,
): Promise<KnowledgeBaseDocument[]> {
  const resp = await request<{ documents: KnowledgeBaseDocument[] }>(
    `/knowledge-bases/${kbId}/documents`,
  );
  return resp.documents ?? [];
}

export async function deleteKnowledgeBaseDocument(
  kbId: string,
  docId: string,
): Promise<void> {
  await request<unknown>(`/knowledge-bases/${kbId}/documents/${docId}`, {
    method: 'DELETE',
  });
}

export async function uploadFile(
  knowledgeBaseId: string,
  file: File,
): Promise<FileRecord> {
  const form = new FormData();
  form.append('file', file);
  form.append('knowledge_base_id', knowledgeBaseId);
  const token = getToken();
  const resp = await fetch(`${API_BASE}/files/upload`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) {
    let message = `Upload failed (${resp.status})`;
    try {
      const body = await resp.json();
      message = body.detail ?? message;
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, message);
  }
  return (await resp.json()) as FileRecord;
}

export async function getFile(fileId: string): Promise<FileRecord> {
  return request<FileRecord>(`/files/${fileId}`);
}

export async function openFile(fileId: string): Promise<void> {
  const token = getToken();
  const resp = await fetch(`${API_BASE}/files/${fileId}/download-content`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, `Download failed (${resp.status})`);
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.target = '_blank';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// ---- Billing & usage ----

export async function listPlans(): Promise<{ plans: Plan[] }> {
  return request<{ plans: Plan[] }>('/billing/plans');
}

export async function getSubscription(organizationId: string): Promise<Subscription> {
  return request<Subscription>(`/billing/organizations/${organizationId}/subscription`);
}

export async function getUsage(): Promise<{ period: string; items: UsageItem[] }> {
  return request<{ period: string; items: UsageItem[] }>('/subscriptions/usage');
}

export async function createCheckoutSession(
  organizationId: string,
  planId: string,
): Promise<{ session_id: string; url: string }> {
  return request<{ session_id: string; url: string }>('/billing/checkout', {
    method: 'POST',
    body: JSON.stringify({
      organization_id: organizationId,
      plan_id: planId,
      success_url: `${window.location.origin}?payment=success`,
      cancel_url: `${window.location.origin}?payment=cancelled`,
    }),
  });
}

export async function getBillingConfig(): Promise<{
  enabled: boolean;
  publishable_key?: string | null;
  currency?: string;
}> {
  return request<{ enabled: boolean; publishable_key?: string | null; currency?: string }>(
    '/billing/config',
  );
}

// ---- Types ----

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
  organization: Organization | null;
}

export interface RegisterInput {
  email: string;
  password: string;
  full_name?: string;
  username?: string;
}

export interface User {
  id: string;
  email: string;
  username?: string;
  full_name?: string;
  role?: string;
  is_superuser?: boolean;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
}

export interface Conversation {
  id: string;
  title: string;
  is_private: boolean;
  is_archived?: boolean;
  is_pinned?: boolean;
  summary?: string | null;
  settings?: Record<string, unknown>;
  last_message_at?: string;
  message_count?: number;
  created_at: string;
}

export interface ConversationListResponse {
  conversations: Conversation[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  user_id: string | null;
  role: string;
  type: string;
  status: string;
  content: string | null;
  created_at: string;
  is_edited?: boolean;
  citations?: Citation[];
}

export interface Citation {
  index: number;
  type?: string;
  title?: string;
  url?: string;
  content?: string;
}

export interface MessageListResponse {
  messages: Message[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export type ChatEvent =
  | { type: 'content'; content: string }
  | { type: 'citations'; citations: unknown[] }
  | { type: 'done'; message_id: string }
  | { type: 'error'; message: string };

export interface KnowledgeBase {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  is_indexed: boolean;
  document_count: number;
  total_chunks: number;
}

export interface KnowledgeBaseListResponse {
  knowledge_bases: KnowledgeBase[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface FileRecord {
  id: string;
  original_filename: string;
  filename: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  status: string;
  knowledge_base_id?: string | null;
  created_at: string;
}

export interface Plan {
  id: string;
  name: string;
  display_name?: string;
  description?: string | null;
  price: number;
  currency: string;
  interval: string;
  features?: string[];
  limits?: Record<string, unknown>;
  is_popular?: boolean;
}

export interface Subscription {
  id: string;
  organization_id: string;
  plan_id: string;
  status: string;
  interval: string;
  current_period_start?: string;
  current_period_end?: string;
}

export interface UsageItem {
  type: string;
  total_quantity: number;
  total_cost: number;
}

// ---- Admin ----

export interface AdminStats {
  total_users: number;
  total_organizations: number;
  total_files: number;
  total_files_size: number;
  total_subscriptions: number;
  active_subscriptions: number;
  total_invoices: number;
  revenue: number;
}

export interface AdminUser {
  id: string;
  email: string;
  username?: string | null;
  full_name?: string | null;
  role: string;
  status: string;
  created_at: string;
}

export interface AdminOrg {
  id: string;
  name: string;
  slug: string;
  plan: string;
  status: string;
  owner_id?: string | null;
  created_at: string;
}

export interface AdminAuditLog {
  id: string;
  action: string;
  resource_type: string;
  organization_id?: string | null;
  user_id?: string | null;
  created_at?: string | null;
}

export async function adminStats(): Promise<AdminStats> {
  return request<AdminStats>('/admin/stats');
}

export async function adminUsers(search?: string): Promise<AdminUser[]> {
  const qs = search ? `?search=${encodeURIComponent(search)}` : '';
  return request<AdminUser[]>(`/admin/users${qs}`);
}

export async function adminOrganizations(search?: string): Promise<AdminOrg[]> {
  const qs = search ? `?search=${encodeURIComponent(search)}` : '';
  return request<AdminOrg[]>(`/admin/organizations${qs}`);
}

export async function adminAuditLogs(): Promise<{
  logs: AdminAuditLog[];
  total: number;
}> {
  return request<{ logs: AdminAuditLog[]; total: number }>('/admin/audit-logs');
}

// ---- GDPR ----

export async function exportMyData(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>('/users/me/export', { method: 'POST' });
}

export async function deleteMyAccount(): Promise<void> {
  await request<unknown>('/users/me', { method: 'DELETE' });
}
