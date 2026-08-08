import { useEffect, useState } from 'react';
import * as api from '../lib/api';

interface Props {
  onClose: () => void;
  onToast: (text: string) => void;
}

type Tab = 'overview' | 'users' | 'orgs' | 'audit';

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export default function AdminPanel({ onClose, onToast }: Props) {
  const [tab, setTab] = useState<Tab>('overview');
  const [stats, setStats] = useState<api.AdminStats | null>(null);
  const [users, setUsers] = useState<api.AdminUser[]>([]);
  const [orgs, setOrgs] = useState<api.AdminOrg[]>([]);
  const [logs, setLogs] = useState<api.AdminAuditLog[]>([]);
  const [search, setSearch] = useState('');

  const loadStats = async () => {
    try {
      setStats(await api.adminStats());
    } catch {
      onToast('⚠ Failed to load stats');
    }
  };

  const loadUsers = async () => {
    try {
      setUsers(await api.adminUsers(search));
    } catch {
      onToast('⚠ Failed to load users');
    }
  };

  const loadOrgs = async () => {
    try {
      setOrgs(await api.adminOrganizations(search));
    } catch {
      onToast('⚠ Failed to load organizations');
    }
  };

  const loadAudit = async () => {
    try {
      const res = await api.adminAuditLogs();
      setLogs(res.logs);
    } catch {
      onToast('⚠ Failed to load audit logs');
    }
  };

  useEffect(() => {
    void loadStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (tab === 'users') void loadUsers();
    if (tab === 'orgs') void loadOrgs();
    if (tab === 'audit') void loadAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, search]);

  const statCards: { label: string; value: string }[] = [
    { label: 'Users', value: String(stats?.total_users ?? '—') },
    { label: 'Organizations', value: String(stats?.total_organizations ?? '—') },
    { label: 'Files', value: String(stats?.total_files ?? '—') },
    { label: 'Storage', value: stats ? formatBytes(stats.total_files_size) : '—' },
    { label: 'Subscriptions', value: String(stats?.total_subscriptions ?? '—') },
    { label: 'Active subs', value: String(stats?.active_subscriptions ?? '—') },
    { label: 'Invoices', value: String(stats?.total_invoices ?? '—') },
    { label: 'Revenue', value: stats ? `$${(stats.revenue / 100).toFixed(2)}` : '—' },
  ];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <div className="settings-title">
            <h3>Admin Panel</h3>
            <p>Platform management</p>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="admin-tabs">
          <button
            className={`admin-tab${tab === 'overview' ? ' active' : ''}`}
            onClick={() => setTab('overview')}
          >
            Overview
          </button>
          <button
            className={`admin-tab${tab === 'users' ? ' active' : ''}`}
            onClick={() => setTab('users')}
          >
            Users
          </button>
          <button
            className={`admin-tab${tab === 'orgs' ? ' active' : ''}`}
            onClick={() => setTab('orgs')}
          >
            Organizations
          </button>
          <button
            className={`admin-tab${tab === 'audit' ? ' active' : ''}`}
            onClick={() => setTab('audit')}
          >
            Audit Logs
          </button>
        </div>

        <div className="admin-body">
          {tab === 'overview' && (
            <div className="admin-stats-grid">
              {statCards.map((s) => (
                <div key={s.label} className="admin-stat-card">
                  <div className="admin-stat-value">{s.value}</div>
                  <div className="admin-stat-label">{s.label}</div>
                </div>
              ))}
            </div>
          )}

          {(tab === 'users' || tab === 'orgs') && (
            <>
              <div className="admin-search">
                <input
                  placeholder="Search…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              {tab === 'users' ? (
                <div className="admin-table-wrap">
                  {users.length === 0 && (
                    <div className="admin-empty">No users found</div>
                  )}
                  {users.map((u) => (
                    <div key={u.id} className="admin-row">
                      <div className="admin-row-main">
                        <div className="admin-row-title">
                          {u.full_name || u.username || '—'}
                          <span className={`admin-status ${u.status}`}>{u.status}</span>
                        </div>
                        <div className="admin-row-sub">
                          {u.email} · {u.role}
                        </div>
                      </div>
                      <div className="admin-row-date">
                        {new Date(u.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="admin-table-wrap">
                  {orgs.length === 0 && (
                    <div className="admin-empty">No organizations found</div>
                  )}
                  {orgs.map((o) => (
                    <div key={o.id} className="admin-row">
                      <div className="admin-row-main">
                        <div className="admin-row-title">
                          {o.name}
                          <span className={`admin-plan ${o.plan}`}>{o.plan}</span>
                        </div>
                        <div className="admin-row-sub">
                          {o.slug} · {o.status}
                        </div>
                      </div>
                      <div className="admin-row-date">
                        {new Date(o.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {tab === 'audit' && (
            <div className="admin-table-wrap">
              {logs.length === 0 && (
                <div className="admin-empty">No audit log entries</div>
              )}
              {logs.map((l) => (
                <div key={l.id} className="admin-row">
                  <div className="admin-row-main">
                    <div className="admin-row-title">
                      <span className={`audit-action ${l.action}`}>{l.action}</span>
                      <span className="admin-row-sub-inline">{l.resource_type}</span>
                    </div>
                    <div className="admin-row-sub">
                      user: {l.user_id?.slice(0, 8)} · org: {l.organization_id?.slice(0, 8)}
                    </div>
                  </div>
                  <div className="admin-row-date">
                    {l.created_at ? new Date(l.created_at).toLocaleString() : '—'}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
