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

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
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

export function logout(): void {
  setToken(null);
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

export async function streamChat(
  conversationId: string,
  content: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken();
  const resp = await fetch(`${API_BASE}/messages/conversations/${conversationId}/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content, stream: true }),
    signal,
  });
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
  citations?: unknown[];
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
