import { type FormEvent, useEffect, useRef, useState } from 'react';
import * as api from '../lib/api';
import { useAuth } from '../context/AuthContext';
import Sidebar from './Sidebar';
import BillingModal from './BillingModal';
import Markdown from '../lib/Markdown';
import {
  CheckIcon,
  ChevronDownIcon,
  FolderIcon,
  GlobeIcon,
  PaperclipIcon,
  SendIcon,
} from '../lib/icons';

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  streaming?: boolean;
  is_edited?: boolean;
  citations?: api.Citation[];
  attachment?: { id: string; name: string; mime_type?: string; status?: string };
}

function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      resolve();
    } catch (e) {
      reject(e);
    } finally {
      document.body.removeChild(ta);
    }
  });
}

export default function ChatPage() {
  const { user, organization, signOut } = useAuth();
  const [conversations, setConversations] = useState<api.Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [knowledgeBases, setKnowledgeBases] = useState<api.KnowledgeBase[]>([]);
  const [selectedKb, setSelectedKb] = useState<string>('');
  const [kbMenuOpen, setKbMenuOpen] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [toast, setToast] = useState('');
  const [showBilling, setShowBilling] = useState(false);
  const [showDownArrow, setShowDownArrow] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const ACTIVE_KEY = 'nova_active_conversation';
  const CHAT_STATE_KEY = 'nova_chat_state';
  const DRAFT_PREFIX = 'nova_draft:';

  useEffect(() => {
    api.listConversations().then((res) => {
      setConversations(res.conversations);
      const saved = localStorage.getItem(ACTIVE_KEY);
      if (saved && res.conversations.some((c) => c.id === saved)) {
        setActiveId(saved);
      }
    });
    api.listKnowledgeBases().then((res) => {
      setKnowledgeBases(res.knowledge_bases);
    });
    const savedState = localStorage.getItem(CHAT_STATE_KEY);
    if (savedState) {
      try {
        const s = JSON.parse(savedState) as { selectedKb?: string; webSearch?: boolean };
        if (s.selectedKb) setSelectedKb(s.selectedKb);
        if (typeof s.webSearch === 'boolean') setWebSearch(s.webSearch);
      } catch {
        /* ignore malformed state */
      }
    }
  }, []);

  useEffect(() => {
    if (activeId) {
      localStorage.setItem(ACTIVE_KEY, activeId);
    } else {
      localStorage.removeItem(ACTIVE_KEY);
    }
  }, [activeId]);

  useEffect(() => {
    localStorage.setItem(
      CHAT_STATE_KEY,
      JSON.stringify({ selectedKb, webSearch }),
    );
  }, [selectedKb, webSearch]);

  useEffect(() => {
    if (!activeId) return;
    const saved = localStorage.getItem(DRAFT_PREFIX + activeId);
    if (saved != null) setInput(saved);
  }, [activeId]);

  useEffect(() => {
    if (!activeId) return;
    const key = DRAFT_PREFIX + activeId;
    if (input) {
      localStorage.setItem(key, input);
    } else {
      localStorage.removeItem(key);
    }
  }, [input, activeId]);

  const handleSignOut = () => {
    localStorage.removeItem(ACTIVE_KEY);
    localStorage.removeItem(CHAT_STATE_KEY);
    Object.keys(localStorage)
      .filter((k) => k.startsWith(DRAFT_PREFIX))
      .forEach((k) => localStorage.removeItem(k));
    signOut();
  };

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    setMessages([]);
    api
      .listMessages(activeId)
      .then((res) => {
        setMessages(
          res.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content ?? '',
            is_edited: m.is_edited,
            citations: Array.isArray(m.citations) ? (m.citations as api.Citation[]) : undefined,
          })),
        );
      })
      .catch(() => setMessages([]));
  }, [activeId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      setShowDownArrow(el.scrollHeight - el.scrollTop - el.clientHeight > 120);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && !showDownArrow) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }, [messages, showDownArrow]);

  const showToast = (text: string) => {
    setToast(text);
    setTimeout(() => setToast(''), 1600);
  };

  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      setShowDownArrow(false);
    }
  };

  const handleNew = async () => {
    const conv = await api.createConversation('New conversation');
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
  };

  const runStream = async (
    content: string,
    conversationId: string,
    kbs?: string[],
    ws?: boolean,
  ) => {
    const userMsg: ChatMessage = { id: `local-${Date.now()}`, role: 'user', content };
    const assistantMsg: ChatMessage = {
      id: `local-${Date.now() + 1}`,
      role: 'assistant',
      content: '',
      streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await api.streamChat(
        conversationId,
        content,
        (event) => {
          if (event.type === 'content') {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.streaming) {
                next[next.length - 1] = { ...last, content: last.content + event.content };
              }
              return next;
            });
          } else if (event.type === 'citations') {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.streaming) {
                next[next.length - 1] = {
                  ...last,
                  citations: (event.citations as api.Citation[]) ?? [],
                };
              }
              return next;
            });
          } else if (event.type === 'error') {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.streaming) {
                next[next.length - 1] = {
                  ...last,
                  streaming: false,
                  content: last.content || '⚠ ' + event.message,
                };
              }
              return next;
            });
          } else if (event.type === 'done') {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.streaming) {
                next[next.length - 1] = { ...last, streaming: false, id: event.message_id };
              }
              return next;
            });
            api.listConversations().then((res) => setConversations(res.conversations));
          }
        },
        controller.signal,
        kbs,
        ws,
      );
    } catch (err) {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.streaming) {
          next[next.length - 1] = {
            ...last,
            streaming: false,
            content: last.content || '⚠ ' + (err instanceof Error ? err.message : 'Stream failed'),
          };
        }
        return next;
      });
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const content = input.trim();
    if (!content || busy || !activeId) return;
    setInput('');
    await runStream(content, activeId, knowledgeBaseIds, webSearch);
  };

  const handleStop = () => abortRef.current?.abort();

  const startEdit = (m: ChatMessage) => {
    setEditId(m.id);
    setEditText(m.content);
  };

  const cancelEdit = () => {
    setEditId(null);
    setEditText('');
  };

  const saveEdit = async () => {
    const text = editText.trim();
    const target = messages.find((x) => x.id === editId);
    if (!activeId || !target || !text) return;
    setEditId(null);
    setEditText('');
    if (target.id.startsWith('local-')) return;

    const idx = messages.findIndex((x) => x.id === target.id);
    const toDelete = messages.slice(idx).filter((x) => !x.id.startsWith('local-'));
    await Promise.all(
      toDelete.map((x) => api.deleteMessage(activeId, x.id).catch(() => undefined)),
    );
    setMessages((prev) => prev.slice(0, idx));
    await runStream(text, activeId, knowledgeBaseIds, webSearch);
  };

  const copyMessage = async (m: ChatMessage) => {
    try {
      await copyToClipboard(m.content);
      showToast('Copied to clipboard');
    } catch {
      showToast('Copy failed');
    }
  };

  const removeMessage = async (m: ChatMessage) => {
    if (!activeId || m.id.startsWith('local-') || busy) return;
    const idx = messages.findIndex((x) => x.id === m.id);
    const toDelete = messages.slice(idx).filter((x) => !x.id.startsWith('local-'));
    await Promise.all(
      toDelete.map((x) => api.deleteMessage(activeId, x.id).catch(() => undefined)),
    );
    setMessages((prev) => prev.slice(0, idx));
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setUploading(true);
    try {
      let kbId = selectedKb;
      if (!kbId) {
        const existing = knowledgeBases[0];
        if (existing) {
          kbId = existing.id;
          setSelectedKb(kbId);
        } else {
          const kb = await api.createKnowledgeBase('My Documents', 'Uploaded documents');
          kbId = kb.id;
          setSelectedKb(kbId);
          api.listKnowledgeBases().then((res) => setKnowledgeBases(res.knowledge_bases));
        }
      }
      const record = await api.uploadFile(kbId, file);
      let status = record.status ?? '';
      for (let i = 0; i < 20 && status !== 'ready'; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const fresh = await api.getFile(record.id);
          status = fresh.status ?? status;
        } catch {
          break;
        }
      }
      const att = { id: record.id, name: record.original_filename, mime_type: record.mime_type, status };
      setMessages((prev) => [
        ...prev,
        {
          id: `local-${Date.now()}`,
          role: 'assistant',
          content: `PDF "${record.original_filename}" uploaded and indexed. What details would you like me to extract from it?`,
          attachment: att,
        },
      ]);
      showToast('PDF uploaded');
    } catch (err) {
      showToast('⚠ ' + (err instanceof Error ? err.message : 'Upload failed'));
    } finally {
      setUploading(false);
    }
  };

  const handleAttachClick = () => {
    fileInputRef.current?.click();
  };

  const openAttachment = async (att: NonNullable<ChatMessage['attachment']>) => {
    try {
      await api.openFile(att.id);
    } catch (err) {
      showToast('⚠ ' + (err instanceof Error ? err.message : 'Failed to open file'));
    }
  };

  const handleRename = async (id: string, title: string) => {
    try {
      const updated = await api.renameConversation(id, title);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title: updated.title ?? title } : c)),
      );
    } catch (err) {
      showToast('⚠ ' + (err instanceof Error ? err.message : 'Rename failed'));
    }
  };

  const handleDeleteConv = async (id: string) => {
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        setActiveId(null);
      }
      showToast('Conversation deleted');
    } catch (err) {
      showToast('⚠ ' + (err instanceof Error ? err.message : 'Delete failed'));
    }
  };

  const knowledgeBaseIds = selectedKb ? [selectedKb] : undefined;
  const selectedKbName = knowledgeBases.find((k) => k.id === selectedKb)?.name ?? '';

  return (
    <div className="app-shell">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNew}
        onRename={handleRename}
        onDelete={handleDeleteConv}
      />

      <main className="chat-main">
        <header className="chat-header">
          <div className="chat-header-title">
            {activeId ? conversations.find((c) => c.id === activeId)?.title ?? 'Conversation' : 'Nova AI'}
          </div>
          <div className="chat-header-user">
            <span className="org-name">{organization?.name ?? 'No organization'}</span>
            <button className="billing-btn" onClick={() => setShowBilling(true)}>
              Billing
            </button>
            <span className="user-avatar">
              {(user?.full_name ?? user?.email ?? '?').charAt(0).toUpperCase()}
            </span>
            <button className="sign-out" onClick={handleSignOut}>
              Sign out
            </button>
          </div>
        </header>

        <div className="message-scroll" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="message-welcome">
              <h2>Welcome to Nova AI</h2>
              <p>Start a new conversation or pick one from the sidebar.</p>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`message-row ${m.role}${m.id === editId ? ' editing' : ''}`}>
              <div className="message-avatar">{m.role === 'user' ? 'You' : 'AI'}</div>
              <div className="message-main">
                <div className="message-bubble">
                  <div className="message-head">
                    <span className="message-role-label">
                      {m.role === 'user' ? 'You' : 'Nova'}
                      {m.is_edited && <span className="edited-tag"> (edited)</span>}
                    </span>
                  </div>
                  {m.id === editId ? (
                    <div className="edit-box">
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) saveEdit();
                          if (e.key === 'Escape') cancelEdit();
                        }}
                      />
                      <div className="edit-actions">
                        <button className="edit-save" onClick={saveEdit}>
                          Save &amp; Resend
                        </button>
                        <button className="edit-cancel" onClick={cancelEdit}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="message-content">
                      {m.role === 'assistant' ? <Markdown text={m.content} /> : m.content}
                      {m.streaming && <span className="cursor-blink" />}
                    </div>
                  )}
                  {m.attachment && (
                    <button
                      type="button"
                      className="file-chip"
                      onClick={() => openAttachment(m.attachment!)}
                      title="Open PDF"
                    >
                      <span className="file-chip-icon">PDF</span>
                      <span className="file-chip-name">{m.attachment.name}</span>
                      <span className="file-chip-open">Open</span>
                    </button>
                  )}
                </div>
                {m.role === 'assistant' &&
                  m.citations &&
                  m.citations.length > 0 &&
                  !m.streaming && (
                    <div className="sources">
                      <span className="sources-label">Sources</span>
                      <div className="sources-list">
                        {m.citations.map((c) => (
                          <a
                            key={c.index}
                            className="source-chip"
                            href={c.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <span className="source-idx">{c.index}</span>
                            <span className="source-title">{c.title ?? c.url}</span>
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                {!m.streaming && m.id && !m.id.startsWith('local-') && (
                  <div className="message-footer">
                    <button className="msg-action" onClick={() => copyMessage(m)}>
                      Copy
                    </button>
                    {m.role === 'user' && (
                      <button className="msg-action" onClick={() => startEdit(m)}>
                        Edit
                      </button>
                    )}
                    <button className="msg-action danger" onClick={() => removeMessage(m)}>
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {showDownArrow && (
          <button className="scroll-down" onClick={scrollToBottom} title="Scroll to latest">
            <ChevronDownIcon />
          </button>
        )}

        <form className="composer" onSubmit={handleSubmit}>
          <div className="composer-box">
            <input
              className="composer-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={activeId ? 'Ask Nova anything…' : 'Create a conversation first'}
              disabled={!activeId || busy}
            />
            <div className="composer-box-footer">
              <div className="composer-icons">
                <button
                  type="button"
                  className={`icon-btn${kbMenuOpen ? ' active' : ''}`}
                  title="Knowledge base"
                  onClick={() => setKbMenuOpen((o) => !o)}
                >
                  <FolderIcon />
                  {selectedKbName && <span className="kb-chip">{selectedKbName}</span>}
                </button>
                <button
                  type="button"
                  className={`icon-btn${webSearch ? ' active' : ''}`}
                  title="Live web search"
                  onClick={() => setWebSearch((v) => !v)}
                >
                  <GlobeIcon />
                </button>
                <button
                  type="button"
                  className={`icon-btn${uploading ? ' busy' : ''}`}
                  title="Upload a PDF — Nova will ask what details you need"
                  disabled={uploading}
                  onClick={handleAttachClick}
                >
                  <PaperclipIcon />
                </button>
              </div>
              {busy ? (
                <button type="button" className="composer-stop" onClick={handleStop}>
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  className="composer-send"
                  disabled={!activeId || !input.trim()}
                  title="Send"
                >
                  <SendIcon />
                </button>
              )}
            </div>
            {kbMenuOpen && (
              <div className="kb-menu">
                {selectedKb && (
                  <button
                    className="kb-menu-item"
                    onClick={() => {
                      setSelectedKb('');
                      setKbMenuOpen(false);
                    }}
                  >
                    <span className="kb-menu-clear">Clear selection</span>
                  </button>
                )}
                {knowledgeBases.length === 0 && (
                  <div className="kb-menu-empty">No knowledge bases yet</div>
                )}
                {knowledgeBases.map((kb) => (
                  <button
                    key={kb.id}
                    className={`kb-menu-item${selectedKb === kb.id ? ' selected' : ''}`}
                    onClick={() => {
                      setSelectedKb(kb.id);
                      setKbMenuOpen(false);
                    }}
                  >
                    <span className="kb-menu-check">{selectedKb === kb.id && <CheckIcon />}</span>
                    <span className="kb-menu-name">{kb.name}</span>
                    <span className="kb-menu-count">{kb.total_chunks} chunks</span>
                  </button>
                ))}
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              hidden
              onChange={handleFileSelect}
            />
          </div>
        </form>
      </main>

      {showBilling && (
        <BillingModal organizationId={organization?.id} onClose={() => setShowBilling(false)} />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
