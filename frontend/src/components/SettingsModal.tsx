import { useEffect, useState } from 'react';
import * as api from '../lib/api';

interface Props {
  onClose: () => void;
  onToast: (text: string) => void;
}

type Tab = 'keys' | 'webhooks' | 'usage' | 'workflows' | 'privacy';

export default function SettingsModal({ onClose, onToast }: Props) {
  const [tab, setTab] = useState<Tab>('keys');
  const [keys, setKeys] = useState<api.ApiKey[]>([]);
  const [webhooks, setWebhooks] = useState<api.Webhook[]>([]);
  const [workflows, setWorkflows] = useState<api.Workflow[]>([]);
  const [usage, setUsage] = useState<{ period: string; items: api.UsageItem[] } | null>(null);

  const [keyName, setKeyName] = useState('');
  const [newKey, setNewKey] = useState('');
  const [webhookName, setWebhookName] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [workflowName, setWorkflowName] = useState('');

  const load = async () => {
    try {
      const [k, w, u, wf] = await Promise.all([
        api.listApiKeys(),
        api.listWebhooks(),
        api.getUsage(),
        api.listWorkflows(),
      ]);
      setKeys(k);
      setWebhooks(w);
      setUsage(u);
      setWorkflows(wf);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    void load();
  }, []);

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
