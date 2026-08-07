import { useState } from 'react';
import * as api from '../lib/api';
import { EditIcon, TrashIcon } from '../lib/icons';

interface Props {
  conversations: api.Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export default function Sidebar({ conversations, activeId, onSelect, onNew, onRename, onDelete }: Props) {
  const [filter, setFilter] = useState('');
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameText, setRenameText] = useState('');

  const visible = conversations.filter((c) =>
    c.title.toLowerCase().includes(filter.toLowerCase()),
  );

  const startRename = (c: api.Conversation) => {
    setRenamingId(c.id);
    setRenameText(c.title);
  };

  const commitRename = async (id: string) => {
    const title = renameText.trim();
    setRenamingId(null);
    if (title) {
      await onRename(id, title);
    }
  };

  const handleDelete = async (c: api.Conversation) => {
    await onDelete(c.id);
  };

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
          <div
            key={c.id}
            className={`conversation-item${c.id === activeId ? ' active' : ''}`}
          >
            {renamingId === c.id ? (
              <input
                className="conversation-rename"
                autoFocus
                value={renameText}
                onChange={(e) => setRenameText(e.target.value)}
                onBlur={() => commitRename(c.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename(c.id);
                  if (e.key === 'Escape') setRenamingId(null);
                }}
              />
            ) : (
              <>
                <button className="conversation-main" onClick={() => onSelect(c.id)} title={c.title}>
                  <span className="conversation-dot" />
                  <span className="conversation-title">{c.title || 'Untitled'}</span>
                </button>
                <div className="conversation-actions">
                  <button className="conv-action" title="Rename" onClick={() => startRename(c)}>
                    <EditIcon />
                  </button>
                  <button className="conv-action danger" title="Delete" onClick={() => handleDelete(c)}>
                    <TrashIcon />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </nav>
    </aside>
  );
}
