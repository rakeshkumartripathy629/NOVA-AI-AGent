import { useEffect, useRef, useState } from 'react';
import * as api from '../lib/api';

interface Props {
  onClose: () => void;
  onToast: (text: string) => void;
}

type Tab = 'keys' | 'webhooks' | 'usage' | 'workflows' | 'memory' | 'privacy';

const MEMORY_PAGE_SIZE = 20;

const CATEGORY_LABELS: Record<api.MemoryCategory, string> = {
  profile: 'Profile',
  skills: 'Skills',
  education: 'Education',
  work_experience: 'Work experience',
  project: 'Project',
  goals: 'Goals',
  interests: 'Interests',
  preference: 'Preference',
  technical_preference: 'Technical preference',
  past_event: 'Past event',
  fact: 'Fact',
  topic: 'Topic',
};

export default function SettingsModal({ onClose, onToast }: Props) {
  const [tab, setTab] = useState<Tab>('keys');
  const [keys, setKeys] = useState<api.ApiKey[]>([]);
  const [webhooks, setWebhooks] = useState<api.Webhook[]>([]);
  const [workflows, setWorkflows] = useState<api.Workflow[]>([]);
  const [usage, setUsage] = useState<{ period: string; items: api.UsageItem[] } | null>(null);
  const [memories, setMemories] = useState<api.MemoryItem[]>([]);
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [memoryPage, setMemoryPage] = useState(1);
  const [memoryTotal, setMemoryTotal] = useState(0);
  const [memorySearching, setMemorySearching] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editCategory, setEditCategory] = useState<api.MemoryCategory>('fact');
  const [editImportance, setEditImportance] = useState(3);
  const memoryInit = useRef(false);

  const [keyName, setKeyName] = useState('');
  const [newKey, setNewKey] = useState('');
  const [webhookName, setWebhookName] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [workflowName, setWorkflowName] = useState('');
  const [memorySearch, setMemorySearch] = useState('');
  const [memoryInput, setMemoryInput] = useState('');
  const [memoryCategory, setMemoryCategory] = useState<api.MemoryCategory>('fact');

  const loadMemories = async (reset: boolean) => {
    try {
      if (reset) {
        const r = await api.listMemories({ page: 1, page_size: MEMORY_PAGE_SIZE });
        setMemories(r.memories ?? []);
        setMemoryTotal(r.total ?? 0);
        setMemoryPage(1);
      } else {
        const r = await api.listMemories({
          page: memoryPage + 1,
          page_size: MEMORY_PAGE_SIZE,
        });
        setMemories((prev) => [...prev, ...(r.memories ?? [])]);
        setMemoryTotal(r.total ?? 0);
        setMemoryPage((p) => p + 1);
      }
    } catch {
      /* ignore */
    }
  };

  const load = async () => {
    try {
      const [k, w, u, wf, me] = await Promise.all([
        api.listApiKeys(),
        api.listWebhooks(),
        api.getUsage(),
        api.listWorkflows(),
        api.fetchMe(),
      ]);
      setKeys(k);
      setWebhooks(w);
      setUsage(u);
      setWorkflows(wf);
      setMemoryEnabled((me.preferences?.memory_enabled ?? true) !== false);
    } catch {
      /* ignore */
    }
    void loadMemories(true);
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!memoryInit.current) {
      memoryInit.current = true;
      return;
    }
    const timer = setTimeout(() => {
      if (memorySearch.trim()) {
        setMemorySearching(true);
        void (async () => {
          try {
            const r = await api.searchMemories(memorySearch.trim(), 50);
            setMemories(r.memories ?? []);
            setMemoryTotal(r.total ?? 0);
            setMemoryPage(1);
          } catch {
            /* ignore */
          } finally {
            setMemorySearching(false);
          }
        })();
      } else {
        void loadMemories(true);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [memorySearch]);

  const startEdit = (m: api.MemoryItem) => {
    setEditingId(m.id);
    setEditContent(m.content);
    setEditCategory(m.category);
    setEditImportance(m.importance);
  };

  const saveEdit = async () => {
    if (!editingId || !editContent.trim()) return;
    try {
      await api.updateMemory(editingId, {
        content: editContent.trim(),
        category: editCategory,
        importance: editImportance,
      });
      setEditingId(null);
      onToast('Memory updated');
      void loadMemories(true);
    } catch (err) {
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed to update memory'));
    }
  };

  const cancelEdit = () => setEditingId(null);

  const handleCreateKey = async () => {
    if (!keyName.trim()) return;
    try {
      const created = await api.createApiKey(keyName.trim());
      setNewKey(created.key ?? '');
      setKeyName('');
      onToast('API key created');
      void load();
    } catch (err) {
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed to create key'));
    }
  };

  const handleCreateWebhook = async () => {
    if (!webhookName.trim() || !webhookUrl.trim()) return;
    try {
      const created = await api.createWebhook({
        name: webhookName.trim(),
        url: webhookUrl.trim(),
      });
      if (created.secret) {
        setNewKey(`Webhook secret: ${created.secret}`);
      }
      setWebhookName('');
      setWebhookUrl('');
      onToast('Webhook created');
      void load();
    } catch (err) {
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed to create webhook'));
    }
  };

  const handleCreateWorkflow = async () => {
    if (!workflowName.trim()) return;
    try {
      await api.createWorkflow(workflowName.trim());
      setWorkflowName('');
      onToast('Workflow created');
      void load();
    } catch (err) {
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed to create workflow'));
    }
  };

  const maxUsage = Math.max(1, ...(usage?.items ?? []).map((i) => i.total_quantity));

  const toggleMemory = async () => {
    const next = !memoryEnabled;
    setMemoryEnabled(next);
    try {
      await api.updateMyProfile({ preferences: { memory_enabled: next } });
      onToast(next ? 'Memory on' : 'Memory off');
    } catch (err) {
      setMemoryEnabled(!next);
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed to update memory setting'));
    }
  };

  const handleAddMemory = async () => {
    if (!memoryInput.trim()) return;
    try {
      await api.createMemory(memoryInput.trim(), memoryCategory);
      setMemoryInput('');
      onToast('Memory saved');
      void loadMemories(true);
    } catch (err) {
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed to save memory'));
    }
  };

  const handleClearMemories = async () => {
    if (
      memories.length > 0 &&
      !window.confirm('Delete all your saved memories? This cannot be undone.')
    ) {
      return;
    }
    try {
      await api.deleteAllMemories();
      setMemories([]);
      setMemoryTotal(0);
      setMemoryPage(1);
      onToast('All memories cleared');
    } catch (err) {
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed to clear memories'));
    }
  };

  const memoryHasMore = memories.length < memoryTotal;

  const handleExport = async () => {
    try {
      const data = await api.exportMyData();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `nova-ai-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      onToast('Data exported');
    } catch (err) {
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Export failed'));
    }
  };

  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleDeleteAccount = async () => {
    try {
      await api.deleteMyAccount();
      api.logout();
      window.location.assign('/');
    } catch (err) {
      onToast('⚠ ' + (err instanceof Error ? err.message : 'Delete failed'));
      setConfirmDelete(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h3>Settings</h3>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="settings-tabs">
          <button
            className={`settings-tab${tab === 'keys' ? ' active' : ''}`}
            onClick={() => setTab('keys')}
          >
            API Keys
          </button>
          <button
            className={`settings-tab${tab === 'webhooks' ? ' active' : ''}`}
            onClick={() => setTab('webhooks')}
          >
            Webhooks
          </button>
          <button
            className={`settings-tab${tab === 'usage' ? ' active' : ''}`}
            onClick={() => setTab('usage')}
          >
            Usage
          </button>
          <button
            className={`settings-tab${tab === 'workflows' ? ' active' : ''}`}
            onClick={() => setTab('workflows')}
          >
            Workflows
          </button>
          <button
            className={`settings-tab${tab === 'memory' ? ' active' : ''}`}
            onClick={() => setTab('memory')}
          >
            Memory
          </button>
          <button
            className={`settings-tab${tab === 'privacy' ? ' active' : ''}`}
            onClick={() => setTab('privacy')}
          >
            Privacy
          </button>
        </div>

        <div className="settings-body">
          {tab === 'keys' && (
            <div>
              {newKey && (
                <div className="secret-box">
                  <div className="secret-label">Copy this now — it won't be shown again:</div>
                  <code className="secret-value">{newKey}</code>
                  <button
                    className="folder-save"
                    onClick={() => {
                      void navigator.clipboard?.writeText(newKey);
                      onToast('Copied');
                    }}
                  >
                    Copy
                  </button>
                </div>
              )}
              <div className="settings-row">
                <input
                  className="settings-input"
                  placeholder="Key name (e.g. production)"
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateKey()}
                />
                <button className="folder-save" onClick={handleCreateKey}>
                  Create key
                </button>
              </div>
              {keys.length === 0 && (
                <div className="conversation-empty">No API keys yet</div>
              )}
              {keys.map((k) => (
                <div className="settings-item" key={k.id}>
                  <div className="settings-item-main">
                    <div className="settings-item-title">{k.name}</div>
                    <div className="settings-item-sub">
                      {k.prefix}… · {k.scopes.join(', ') || 'chat'} ·{' '}
                      {k.usage_count} calls
                    </div>
                  </div>
                  <span className={`status-badge ${k.status}`}>{k.status}</span>
                  <button
                    className="conv-action danger"
                    title="Delete"
                    onClick={async () => {
                      try {
                        await api.deleteApiKey(k.id);
                        void load();
                        onToast('Key deleted');
                      } catch (err) {
                        onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed'));
                      }
                    }}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          {tab === 'webhooks' && (
            <div>
              <div className="settings-row">
                <input
                  className="settings-input"
                  placeholder="Webhook name"
                  value={webhookName}
                  onChange={(e) => setWebhookName(e.target.value)}
                />
                <input
                  className="settings-input"
                  placeholder="https://…"
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                />
                <button className="folder-save" onClick={handleCreateWebhook}>
                  Add
                </button>
              </div>
              {webhooks.length === 0 && (
                <div className="conversation-empty">No webhooks yet</div>
              )}
              {webhooks.map((w) => (
                <div className="settings-item" key={w.id}>
                  <div className="settings-item-main">
                    <div className="settings-item-title">{w.name}</div>
                    <div className="settings-item-sub">{w.url}</div>
                  </div>
                  <button
                    className="conv-action"
                    title="Send test event"
                    onClick={async () => {
                      try {
                        await api.testWebhook(w.id);
                        onToast('Test delivery sent');
                      } catch (err) {
                        onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed'));
                      }
                    }}
                  >
                    Test
                  </button>
                  <button
                    className="conv-action danger"
                    title="Delete"
                    onClick={async () => {
                      try {
                        await api.deleteWebhook(w.id);
                        void load();
                        onToast('Webhook deleted');
                      } catch (err) {
                        onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed'));
                      }
                    }}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          {tab === 'usage' && (
            <div>
              <div className="usage-period">
                Current period: {usage?.period ?? '—'}
              </div>
              {(usage?.items ?? []).length === 0 && (
                <div className="conversation-empty">No usage recorded yet</div>
              )}
              {usage?.items.map((i) => (
                <div className="usage-row" key={i.type}>
                  <div className="usage-row-top">
                    <span className="usage-type">{i.type}</span>
                    <span className="usage-qty">
                      {i.total_quantity.toLocaleString()}
                    </span>
                  </div>
                  <div className="usage-bar-track">
                    <div
                      className="usage-bar-fill"
                      style={{
                        width: `${Math.max(4, (i.total_quantity / maxUsage) * 100)}%`,
                      }}
                    />
                  </div>
                  <div className="usage-cost">
                    ${i.total_cost.toFixed(4)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === 'workflows' && (
            <div>
              <div className="settings-row">
                <input
                  className="settings-input"
                  placeholder="Workflow name"
                  value={workflowName}
                  onChange={(e) => setWorkflowName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateWorkflow()}
                />
                <button className="folder-save" onClick={handleCreateWorkflow}>
                  Create
                </button>
              </div>
              {workflows.length === 0 && (
                <div className="conversation-empty">
                  No workflows yet — create one to start automating
                </div>
              )}
              {workflows.map((w) => (
                <div className="settings-item" key={w.id}>
                  <div className="settings-item-main">
                    <div className="settings-item-title">{w.name}</div>
                    <div className="settings-item-sub">
                      {w.description || 'No description'} · {w.execution_count}{' '}
                      runs · {w.status}
                    </div>
                  </div>
                  <button
                    className="conv-action"
                    title="Run workflow"
                    onClick={async () => {
                      try {
                        const r = await api.runWorkflow(w.id, {});
                        onToast(`Workflow started (${r.status})`);
                        void load();
                      } catch (err) {
                        onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed'));
                      }
                    }}
                  >
                    ▶
                  </button>
                  <button
                    className="conv-action danger"
                    title="Delete"
                    onClick={async () => {
                      try {
                        await api.deleteWorkflow(w.id);
                        void load();
                        onToast('Workflow deleted');
                      } catch (err) {
                        onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed'));
                      }
                    }}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          {tab === 'memory' && (
            <div>
              <div className="settings-item">
                <div className="settings-item-main">
                  <div className="settings-item-title">Auto-memory</div>
                  <div className="settings-item-sub">
                    Automatically remember facts and preferences from
                    conversations so Nova can recall them later.
                  </div>
                </div>
                <button
                  className={`folder-save${memoryEnabled ? '' : ' muted'}`}
                  onClick={toggleMemory}
                >
                  {memoryEnabled ? 'On' : 'Off'}
                </button>
              </div>

              <div className="settings-row">
                <input
                  className="settings-input"
                  placeholder="Add a fact to remember…"
                  value={memoryInput}
                  onChange={(e) => setMemoryInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAddMemory()}
                />
                <select
                  className="settings-input settings-select"
                  value={memoryCategory}
                  onChange={(e) =>
                    setMemoryCategory(e.target.value as api.MemoryCategory)
                  }
                >
                  <option value="fact">fact</option>
                  <option value="profile">profile</option>
                  <option value="skills">skills</option>
                  <option value="education">education</option>
                  <option value="work_experience">work experience</option>
                  <option value="project">project</option>
                  <option value="goals">goals</option>
                  <option value="interests">interests</option>
                  <option value="preference">preference</option>
                  <option value="technical_preference">technical preference</option>
                  <option value="past_event">past event</option>
                  <option value="topic">topic</option>
                </select>
                <button className="folder-save" onClick={handleAddMemory}>
                  Save
                </button>
              </div>

              <div className="settings-row">
                <input
                  className="settings-input"
                  placeholder="Search memories (semantic)…"
                  value={memorySearch}
                  onChange={(e) => setMemorySearch(e.target.value)}
                />
                <button className="conv-action danger" title="Clear all memories" onClick={handleClearMemories}>
                  Clear all
                </button>
              </div>

              <div className="settings-item-sub memory-count">
                {memorySearching
                  ? 'Searching…'
                  : memoryTotal === 0
                    ? 'No memories yet'
                    : `${memoryTotal} ${memoryTotal === 1 ? 'memory' : 'memories'}${memorySearch.trim() ? ' found' : ''}`}
              </div>

              {memories.length === 0 && !memorySearching && (
                <div className="conversation-empty">
                  {memorySearch.trim()
                    ? 'No memories match your search'
                    : 'No memories yet — they are added automatically or manually'}
                </div>
              )}
              {memories.map((m) =>
                editingId === m.id ? (
                  <div className="settings-item settings-item-edit" key={m.id}>
                    <div className="settings-item-main">
                      <input
                        className="settings-input"
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                      />
                      <div className="settings-row">
                        <select
                          className="settings-input settings-select"
                          value={editCategory}
                          onChange={(e) =>
                            setEditCategory(e.target.value as api.MemoryCategory)
                          }
                        >
                          {(Object.keys(CATEGORY_LABELS) as api.MemoryCategory[]).map((c) => (
                            <option key={c} value={c}>
                              {CATEGORY_LABELS[c]}
                            </option>
                          ))}
                        </select>
                        <label className="settings-item-sub">
                          Importance
                          <input
                            className="settings-input settings-importance"
                            type="number"
                            min={1}
                            max={5}
                            value={editImportance}
                            onChange={(e) =>
                              setEditImportance(
                                Math.max(1, Math.min(5, Number(e.target.value) || 1)),
                              )
                            }
                          />
                        </label>
                      </div>
                    </div>
                    <button className="folder-save" onClick={saveEdit}>
                      Save
                    </button>
                    <button className="conv-action" onClick={cancelEdit}>
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="settings-item" key={m.id}>
                    <div className="settings-item-main">
                      <div className="settings-item-title">{m.content}</div>
                      <div className="settings-item-sub">
                        {CATEGORY_LABELS[m.category] ?? m.category}
                        {' · '}
                        {m.auto ? 'auto' : 'manual'}
                        {' · importance '}
                        {m.importance}
                        {' · used '}
                        {m.use_count}×
                      </div>
                    </div>
                    <button
                      className="conv-action"
                      title="Edit"
                      onClick={() => startEdit(m)}
                    >
                      ✎
                    </button>
                    <button
                      className="conv-action danger"
                      title="Delete"
                      onClick={async () => {
                        try {
                          await api.deleteMemory(m.id);
                          onToast('Memory deleted');
                          void loadMemories(true);
                        } catch (err) {
                          onToast('⚠ ' + (err instanceof Error ? err.message : 'Failed'));
                        }
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ),
              )}
              {memoryHasMore && !memorySearch.trim() && (
                <button className="folder-save memory-load-more" onClick={() => void loadMemories(false)}>
                  Load more
                </button>
              )}
            </div>
          )}

          {tab === 'privacy' && (
            <div className="privacy-tab">
              <div className="privacy-block">
                <div className="privacy-title">Export your data</div>
                <p className="privacy-desc">
                  Download all your personal data — profile, conversations, and
                  messages — as a JSON file.
                </p>
                <button className="folder-save" onClick={handleExport}>
                  Export data
                </button>
              </div>

              <div className="privacy-block danger-block">
                <div className="privacy-title">Delete account</div>
                <p className="privacy-desc">
                  Permanently delete your account and anonymize all personal
                  data. This cannot be undone.
                </p>
                {confirmDelete ? (
                  <div className="privacy-confirm">
                    <span>Are you sure? This removes everything.</span>
                    <button className="btn-danger" onClick={handleDeleteAccount}>
                      Yes, delete my account
                    </button>
                    <button
                      className="folder-save"
                      onClick={() => setConfirmDelete(false)}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    className="btn-danger"
                    onClick={() => setConfirmDelete(true)}
                  >
                    Delete account
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
