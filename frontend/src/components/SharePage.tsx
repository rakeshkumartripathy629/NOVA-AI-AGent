import { useEffect, useState } from 'react';
import * as api from '../lib/api';
import Markdown from '../lib/Markdown';

interface SharePageProps {
  token: string;
}

export default function SharePage({ token }: SharePageProps) {
  const [data, setData] = useState<api.PublicShareData | null>(null);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError('');
    api
      .getSharedConversation(token)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load');
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="share-page">
      <header className="share-header">
        <div className="share-brand">
          <span className="share-logo">N</span>
          <span className="share-brand-name">Nova AI</span>
        </div>
        <span className="share-badge">Shared conversation</span>
      </header>

      <main className="share-main">
        {error ? (
          <div className="share-error">
            <h1>Conversation not found</h1>
            <p>This shared link is invalid or has been removed.</p>
          </div>
        ) : !data ? (
          <div className="share-loading">Loading conversation…</div>
        ) : (
          <>
            <div className="share-title">
              <h1>{data.title || 'Shared conversation'}</h1>
            </div>
            <div className="share-chat">
              {data.messages.length === 0 && (
                <div className="share-empty">No messages in this conversation.</div>
              )}
              {data.messages.map((m) => (
                <div
                  key={m.id ?? `${m.role}-${m.created_at ?? m.content.slice(0, 8)}`}
                  className={`message-row ${m.role}`}
                >
                  <div className="message-avatar">
                    {m.role === 'user' ? (
                      'You'
                    ) : (
                      <img src="/nova-logo.png" alt="Nova" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    )}
                  </div>
                  <div className="message-main">
                    <div className="message-bubble">
                      <div className="message-head">
                        <span className="message-role-label">
                          {m.role === 'user' ? 'You' : 'Nova'}
                        </span>
                      </div>
                      <div className="message-content">
                        {m.role === 'assistant' ? (
                          <Markdown text={m.content ?? ''} />
                        ) : (
                          m.content ?? ''
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <footer className="share-footer">
              Powered by <strong>Nova AI</strong>
            </footer>
          </>
        )}
      </main>
    </div>
  );
}
