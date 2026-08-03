import { useState } from 'react';
import * as api from '../lib/api';

interface Props {
  conversations: api.Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export default function Sidebar({ conversations, activeId, onSelect, onNew }: Props) {
  const [filter, setFilter] = useState('');

  const visible = conversations.filter((c) =>
    c.title.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-title">Conversations</span>
        <button className="new-chat" onClick={onNew} title="New conversation">
          +
        </button>
      </div>

      <input
        className="sidebar-search"
        placeholder="Search…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />

      <nav className="conversation-list">
        {visible.length === 0 && <div className="conversation-empty">No conversations yet</div>}
        {visible.map((c) => (
          <button
            key={c.id}
            className={`conversation-item${c.id === activeId ? ' active' : ''}`}
            onClick={() => onSelect(c.id)}
          >
            <span className="conversation-dot" />
            <span className="conversation-title">{c.title || 'Untitled'}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
