import { useEffect, useState } from 'react';
import {
  createProject,
  deleteProject,
  listProjects,
  updateProject,
  type Project,
} from '../lib/api';
import { TrashIcon } from '../lib/icons';

interface Props {
  organizationId?: string;
  onClose: () => void;
}

export default function ProjectsModal({ organizationId, onClose }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setProjects(await listProjects());
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setMessage('');
    try {
      await createProject(name.trim(), description.trim() || undefined, organizationId);
      setName('');
      setDescription('');
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Create failed');
    } finally {
      setBusy(false);
    }
  }

  async function archive(p: Project) {
    try {
      await updateProject(p.id, { is_archived: !p.is_archived });
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Update failed');
    }
  }

  async function remove(p: Project) {
    if (!window.confirm(`Delete project "${p.name}"?`)) return;
    try {
      await deleteProject(p.id);
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Delete failed');
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Projects</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="agents-layout">
            <div>
              <div className="agents-list-head">
                <span>Your projects</span>
              </div>
              <div className="agents-list">
                {loading && <div className="agents-empty">Loading…</div>}
                {!loading && projects.length === 0 && (
                  <div className="agents-empty">No projects yet.</div>
                )}
                {projects.map((p) => (
                  <div key={p.id} className={`agent-item${p.is_archived ? ' archived' : ''}`}>
                    <div className="agent-item-main">
                      <div className="agent-item-name">{p.name}</div>
                      <div className="agent-item-meta">
                        {p.is_archived ? 'archived' : 'active'}
                      </div>
                      {p.description && <div className="agent-item-desc">{p.description}</div>}
                    </div>
                    <button className="agent-item-delete" onClick={() => archive(p)}>
                      {p.is_archived ? 'Unarchive' : 'Archive'}
                    </button>
                    <button className="agent-item-delete" onClick={() => remove(p)}>
                      <TrashIcon />
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <form className="agent-form" onSubmit={create}>
              <div className="section-title">Create project</div>
              <label>
                Name
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Website revamp"
                />
              </label>
              <label>
                Description
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What is this project about?"
                />
              </label>
              <div className="agent-form-actions">
                <button type="submit" className="auth-submit" disabled={busy || !name.trim()}>
                  Create
                </button>
              </div>
              {message && <div className="form-error">{message}</div>}
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
