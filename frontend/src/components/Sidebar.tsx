import { useEffect, useRef, useState } from 'react';
import * as api from '../lib/api';
import {
  EditIcon,
  TrashIcon,
  PinIcon,
  FolderPlusIcon,
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

function folderOf(c: api.Conversation): string {
  const settings = (c.settings ?? {}) as { folder?: string };
  return (settings.folder ?? '').trim();
}

function ConversationRow({
  c,
  active,
  onSelect,
  onRename,
  onDelete,
  onPin,
  onFolder,
}: {
  c: api.Conversation;
  active: boolean;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onPin: (id: string, pinned: boolean) => Promise<void>;
  onFolder: (id: string, folder: string | null) => Promise<void>;
}) {
  const [renaming, setRenaming] = useState(false);
  const [renameText, setRenameText] = useState('');
  const [folderOpen, setFolderOpen] = useState(false);
  const [folderText, setFolderText] = useState(folderOf(c));

  const commitRename = async () => {
    const title = renameText.trim();
    setRenaming(false);
    if (title) await onRename(c.id, title);
  };

  const commitFolder = async () => {
    const name = folderText.trim();
    setFolderOpen(false);
    await onFolder(c.id, name || null);
  };

  return (
    <div className={`conversation-item${active ? ' active' : ''}`}>
      {renaming ? (
        <input
          className="conversation-rename"
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
            className="conversation-main"
            onClick={() => onSelect(c.id)}
            title={c.title}
          >
            <span className="conversation-dot" />
            <span className="conversation-title">{c.title || 'Untitled'}</span>
          </button>
          <div className="conversation-actions">
            <button
              className={`conv-action${c.is_pinned ? ' on' : ''}`}
              title={c.is_pinned ? 'Unpin' : 'Pin'}
              onClick={() => onPin(c.id, !c.is_pinned)}
            >
              <PinIcon />
            </button>
            <button
              className="conv-action"
              title="Move to folder"
              onClick={() => {
                setFolderText(folderOf(c));
                setFolderOpen((o) => !o);
              }}
            >
              <FolderPlusIcon />
            </button>
            <button
              className="conv-action"
              title="Rename"
              onClick={() => {
                setRenameText(c.title);
                setRenaming(true);
              }}
            >
              <EditIcon />
            </button>
            <button
              className="conv-action danger"
              title="Delete"
              onClick={() => onDelete(c.id)}
            >
              <TrashIcon />
            </button>
          </div>
          {folderOpen && (
            <div className="folder-popover" onClick={(e) => e.stopPropagation()}>
              <input
                className="folder-input"
                autoFocus
                placeholder="Folder name…"
                value={folderText}
                onChange={(e) => setFolderText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitFolder();
                  if (e.key === 'Escape') setFolderOpen(false);
                }}
              />
              <div className="folder-actions">
                <button className="folder-save" onClick={commitFolder}>
                  Save
                </button>
                {folderText && (
                  <button
                    className="folder-clear"
                    onClick={() => {
                      setFolderText('');
                      setFolderOpen(false);
                      onFolder(c.id, null);
                    }}
                  >
                    Remove
                  </button>
                )}
              </div>
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
  onPin,
  onFolder,
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
  const pinned = visible.filter((c) => c.is_pinned);
  const unpinned = visible.filter((c) => !c.is_pinned);

  const folders: { name: string; items: api.Conversation[] }[] = [];
  const folderless: api.Conversation[] = [];
  for (const c of unpinned) {
    const f = folderOf(c);
    if (!f) {
      folderless.push(c);
      continue;
    }
    const existing = folders.find((g) => g.name === f);
    if (existing) existing.items.push(c);
    else folders.push({ name: f, items: [c] });
  }

  const renderRow = (c: api.Conversation) => (
    <ConversationRow
      key={c.id}
      c={c}
      active={c.id === activeId}
      onSelect={onSelect}
      onRename={onRename}
      onDelete={onDelete}
      onPin={onPin}
      onFolder={onFolder}
    />
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
        {visible.length === 0 && (
          <div className="conversation-empty">No conversations yet</div>
        )}

        {pinned.length > 0 && (
          <>
            <div className="conversation-group-label">Pinned</div>
            {pinned.map(renderRow)}
          </>
        )}

        {folders.map((g) => (
          <div key={g.name}>
            <div className="conversation-group-label">{g.name}</div>
            {g.items.map(renderRow)}
          </div>
        ))}

        {pinned.length > 0 && (
          <div className="conversation-group-label">All conversations</div>
        )}
        {folderless.map(renderRow)}
      </nav>

      <div className="sidebar-footer" ref={menuRef}>
        <button
          type="button"
          className="user-avatar sidebar-avatar"
          onClick={() => setMenuOpen((o) => !o)}
          title="Menu"
        >
          {(user?.full_name ?? user?.email ?? '?').charAt(0).toUpperCase()}
        </button>
        {menuOpen && (
          <div className="avatar-menu sidebar-avatar-menu">
            <div className="avatar-menu-head">
              <span className="avatar-menu-name">
                {user?.full_name ?? user?.email ?? 'User'}
              </span>
              <span className="avatar-menu-sub">{user?.email}</span>
            </div>
            <button
              className="avatar-menu-item"
              onClick={() => {
                setMenuOpen(false);
                onSearch();
              }}
            >
              <SearchIcon />
              Search
            </button>
            <button
              className="avatar-menu-item"
              onClick={() => {
                setMenuOpen(false);
                onProjects();
              }}
            >
              <FolderIcon />
              Projects
            </button>
            <button
              className="avatar-menu-item"
              onClick={() => {
                setMenuOpen(false);
                onExport();
              }}
              disabled={!canExport}
            >
              <ShareIcon />
              Export
            </button>
            <button
              className="avatar-menu-item"
              onClick={() => {
                setMenuOpen(false);
                onSummarize();
              }}
              disabled={!canSummarize}
            >
              <SparklesIcon />
              {summarizing ? 'Summarizing…' : 'Summarize'}
            </button>
            <button
              className="avatar-menu-item"
              onClick={() => {
                setMenuOpen(false);
                onShare();
              }}
              disabled={!canExport}
            >
              <ShareIcon />
              Share
            </button>
            <button
              className="avatar-menu-item"
              onClick={() => {
                setMenuOpen(false);
                onBilling();
              }}
            >
              <BotIcon />
              Billing
            </button>
            {user?.is_superuser && (
              <button
                className="avatar-menu-item"
                onClick={() => {
                  setMenuOpen(false);
                  onAdmin();
                }}
              >
                <ShieldIcon />
                Admin
              </button>
            )}
            <div className="avatar-menu-divider" />
            <button
              className="avatar-menu-item"
              onClick={() => {
                setMenuOpen(false);
                onSettings();
              }}
            >
              <GearIcon />
              Settings
            </button>
            <button
              className="avatar-menu-item"
              onClick={onToggleTheme}
            >
              {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
              {theme === 'dark' ? 'Light mode' : 'Dark mode'}
            </button>
            <div className="avatar-menu-divider" />
            <button className="avatar-menu-item danger" onClick={onSignOut}>
              <ShareIcon />
              Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
