import { type FormEvent, useEffect, useRef, useState } from 'react';
import * as api from '../lib/api';
import { useAuth } from '../context/AuthContext';
import Sidebar from './Sidebar';

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  streaming?: boolean;
}

export default function ChatPage() {
  const { user, organization, signOut } = useAuth();
  const [conversations, setConversations] = useState<api.Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    api.listConversations().then((res) => {
      setConversations(res.conversations);
      if (res.conversations.length > 0) {
        setActiveId(res.conversations[0].id);
      }
    });
  }, []);

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
          res.messages.map((m) => ({ id: m.id, role: m.role, content: m.content ?? '' })),
        );
      })
      .catch(() => setMessages([]));
  }, [activeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleNew = async () => {
    const conv = await api.createConversation('New conversation');
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const content = input.trim();
    if (!content || busy || !activeId) return;

    const userMsg: ChatMessage = { id: `local-${Date.now()}`, role: 'user', content };
    const assistantMsg: ChatMessage = { id: `local-${Date.now() + 1}`, role: 'assistant', content: '', streaming: true };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput('');
    setBusy(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await api.streamChat(activeId, content, (event) => {
        if (event.type === 'content') {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.streaming) {
              next[next.length - 1] = { ...last, content: last.content + event.content };
            }
            return next;
          });
        } else if (event.type === 'error') {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.streaming) {
              next[next.length - 1] = { ...last, streaming: false, content: last.content || '⚠ ' + event.message };
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
      }, controller.signal);
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

  const handleStop = () => abortRef.current?.abort();

  return (
    <div className="app-shell">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={handleNew}
      />

      <main className="chat-main">
        <header className="chat-header">
          <div className="chat-header-title">
            {activeId ? conversations.find((c) => c.id === activeId)?.title ?? 'Conversation' : 'Nova AI'}
          </div>
          <div className="chat-header-user">
            <span className="org-name">{organization?.name ?? 'No organization'}</span>
            <span className="user-avatar">{(user?.full_name ?? user?.email ?? '?').charAt(0).toUpperCase()}</span>
            <button className="sign-out" onClick={signOut}>
              Sign out
            </button>
          </div>
        </header>

        <div className="message-scroll">
          {messages.length === 0 && (
            <div className="message-welcome">
              <h2>Welcome to Nova AI</h2>
              <p>Start a new conversation or pick one from the sidebar.</p>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`message-row ${m.role}`}>
              <div className="message-avatar">{m.role === 'user' ? 'You' : 'AI'}</div>
              <div className="message-bubble">
                <span className="message-role-label">{m.role === 'user' ? 'You' : 'Nova'}</span>
                <div className="message-content">{m.content || (m.streaming ? '' : '')}</div>
                {m.streaming && <span className="cursor-blink" />}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <form className="composer" onSubmit={handleSubmit}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={activeId ? 'Ask Nova…' : 'Create a conversation first'}
            disabled={!activeId || busy}
          />
          {busy ? (
            <button type="button" className="composer-stop" onClick={handleStop}>
              Stop
            </button>
          ) : (
            <button type="submit" className="composer-send" disabled={!activeId || !input.trim()}>
              Send
            </button>
          )}
        </form>
      </main>
    </div>
  );
}
