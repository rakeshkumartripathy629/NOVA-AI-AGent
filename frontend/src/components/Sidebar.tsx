import { useEffect, useRef, useState } from 'react';
import * as api from '../lib/api';
import {
  EditIcon,
  TrashIcon,
  SearchIcon,
  FolderIcon,
  SparklesIcon,
  ShareIcon,
  BotIcon,
  GearIcon,
  ShieldIcon,
  SunIcon,
  MoonIcon,
} from '../lib/icons';

interface Props {
  conversations: api.Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onPin: (id: string, pinned: boolean) => Promise<void>;
  onFolder: (id: string, folder: string | null) => Promise<void>;
  user?: { full_name?: string; email?: string; is_superuser?: boolean } | null;
  theme: 'dark' | 'light';
  canExport: boolean;
  canSummarize: boolean;
  summarizing: boolean;
  onSearch: () => void;
  onProjects: () => void;
  onExport: () => void;
  onSummarize: () => void;
  onShare: () => void;
  onBilling: () => void;
  onAdmin: () => void;
  onSettings: () => void;
  onToggleTheme: () => void;
  onSignOut: () => void;
}

function ConversationRow({
  c,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  c: api.Conversation;
  active: boolean;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [renaming, setRenaming] = useState(false);
  const [renameText, setRenameText] = useState('');
  const [hovered, setHovered] = useState(false);

  const commitRename = async () => {
    const title = renameText.trim();
    setRenaming(false);
    if (title) await onRename(c.id, title);
  };

  return (
    <div
      className={`chatgpt-conv-item${active ? ' active' : ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {renaming ? (
        <input
          className="chatgpt-conv-rename"
          autoFocus
          value={renameText}
          onChange={(e) => setRenameText(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename();
            if (e.key === 'Escape') setRenaming(false);
          }}
        />
      ) : (
        <>
          <button
            className="chatgpt-conv-main"
            onClick={() => onSelect(c.id)}
            title={c.title}
          >
            <span className="chatgpt-conv-title">{c.title || 'Untitled'}</span>
          </button>
          {(hovered || active) && (
            <div className="chatgpt-conv-actions">
              <button
                className="chatgpt-conv-action"
                title="Rename"
                onClick={() => {
                  setRenameText(c.title);
                  setRenaming(true);
                }}
              >
                <EditIcon />
              </button>
              <button
                className="chatgpt-conv-action danger"
                title="Delete"
                onClick={() => onDelete(c.id)}
              >
                <TrashIcon />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onRename,
  onDelete,
  onPin: _onPin,
  onFolder: _onFolder,
  user,
  theme,
  canExport,
  canSummarize,
  summarizing,
  onSearch,
  onProjects,
  onExport,
  onSummarize,
  onShare,
  onBilling,
  onAdmin,
  onSettings,
  onToggleTheme,
  onSignOut,
}: Props) {
  const [filter, setFilter] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: PointerEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  const visible = conversations.filter((c) =>
    c.title.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <aside className={`chatgpt-sidebar${collapsed ? ' collapsed' : ''}`}>
      {/* Header */}
      <div className="chatgpt-sidebar-header">
        {!collapsed && (
          <div className="chatgpt-brand-wrap">
            <div className="chatgpt-brand-logo">
              <img src="/nova-logo.png" alt="Nova" />
            </div>
            <span className="chatgpt-brand">Nova AI</span>
          </div>
        )}
        <button
          className="chatgpt-sidebar-toggle"
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12h18M3 6h18M3 18h18" />
          </svg>
        </button>
      </div>

      {/* New chat button */}
      <button className="chatgpt-new-chat" onClick={onNew}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 5v14M5 12h14" />
        </svg>
        {!collapsed && <span>New chat</span>}
      </button>

      {/* Search */}
      {!collapsed && (
        <div className="chatgpt-search-wrap">
          <SearchIcon />
          <input
            className="chatgpt-search"
            placeholder="Search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      )}

      {/* Conversation list */}
      {!collapsed && (
        <div className="chatgpt-conv-list">
          {visible.length === 0 && (
            <div className="chatgpt-conv-empty">No conversations yet</div>
          )}
          {visible.map((c) => (
            <ConversationRow
              key={c.id}
              c={c}
              active={c.id === activeId}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}

      {/* Footer - user profile */}
      <div className="chatgpt-sidebar-footer" ref={menuRef}>
        <button
          className="chatgpt-user-btn"
          onClick={() => setMenuOpen((o) => !o)}
        >
          <div className="chatgpt-user-avatar">
            {(user?.full_name ?? user?.email ?? '?').charAt(0).toUpperCase()}
          </div>
          {!collapsed && (
            <div className="chatgpt-user-info">
              <span className="chatgpt-user-name">
                {user?.full_name ?? user?.email ?? 'User'}
              </span>
              <span className="chatgpt-user-plan">Free</span>
            </div>
          )}
        </button>

        {menuOpen && (
          <div className="chatgpt-menu">
            <button className="chatgpt-menu-item" onClick={() => { setMenuOpen(false); onSearch(); }}>
              <SearchIcon /> Search
            </button>
            <button className="chatgpt-menu-item" onClick={() => { setMenuOpen(false); onProjects(); }}>
              <FolderIcon /> Projects
            </button>
            <button className="chatgpt-menu-item" onClick={() => { setMenuOpen(false); onExport(); }} disabled={!canExport}>
              <ShareIcon /> Export
            </button>
            <button className="chatgpt-menu-item" onClick={() => { setMenuOpen(false); onSummarize(); }} disabled={!canSummarize}>
              <SparklesIcon /> {summarizing ? 'Summarizing…' : 'Summarize'}
            </button>
            <button className="chatgpt-menu-item" onClick={() => { setMenuOpen(false); onShare(); }} disabled={!canExport}>
              <ShareIcon /> Share
            </button>
            <button className="chatgpt-menu-item" onClick={() => { setMenuOpen(false); onBilling(); }}>
              <BotIcon /> Billing
            </button>
            {user?.is_superuser && (
              <button className="chatgpt-menu-item" onClick={() => { setMenuOpen(false); onAdmin(); }}>
                <ShieldIcon /> Admin
              </button>
            )}
            <div className="chatgpt-menu-divider" />
            <button className="chatgpt-menu-item" onClick={() => { setMenuOpen(false); onSettings(); }}>
              <GearIcon /> Settings
            </button>
            <button className="chatgpt-menu-item" onClick={onToggleTheme}>
              {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
              {theme === 'dark' ? 'Light mode' : 'Dark mode'}
            </button>
            <div className="chatgpt-menu-divider" />
            <button className="chatgpt-menu-item danger" onClick={onSignOut}>
              <ShareIcon /> Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
