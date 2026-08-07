import { useEffect, useState } from 'react';
import {
  createAgent,
  deleteAgent,
  listAgents,
  updateAgent,
  type Agent,
  type KnowledgeBase,
} from '../lib/api';
import { TrashIcon } from '../lib/icons';

interface Props {
  knowledgeBases: KnowledgeBase[];
  onClose: () => void;
  onChanged?: () => void;
}

const PROVIDERS = [
  { id: 'groq', label: 'Groq' },
  { id: 'gemini', label: 'Gemini' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'openrouter', label: 'OpenRouter' },
];

const MODELS: Record<string, string[]> = {
  groq: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant'],
  gemini: ['gemini-2.0-flash'],
  openai: ['gpt-4o', 'gpt-4o-mini'],
  anthropic: ['claude-sonnet-4', 'claude-haiku-4'],
  openrouter: ['auto'],
};

interface Draft {
  name: string;
  description: string;
  model_provider: string;
  model: string;
  temperature: number;
  system_prompt: string;
  knowledge_base_ids: string[];
}

const emptyDraft: Draft = {
  name: '',
  description: '',
  model_provider: 'groq',
  model: 'llama-3.3-70b-versatile',
  temperature: 0.7,
  system_prompt: '',
  knowledge_base_ids: [],
};

function draftFromAgent(a: Agent): Draft {
  return {
    name: a.name,
    description: a.description ?? '',
    model_provider: a.model_provider,
    model: a.model,
    temperature: a.temperature,
    system_prompt: a.system_prompt ?? '',
    knowledge_base_ids: a.knowledge_base_ids ?? [],
  };
}

export default function AgentsPanel({ knowledgeBases, onClose, onChanged }: Props) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [editingId, setEditingId] = useState('');
  const [error, setError] = useState('');

  async function refresh() {
    setLoading(true);
    try {
      setAgents(await listAgents());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function set(field: keyof Draft, value: string | number | string[]) {
    setDraft((d) => ({ ...d, [field]: value }));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (!draft.name.trim()) {
      setError('Name is required');
      return;
    }
    try {
      if (editingId) {
        await updateAgent(editingId, { ...draft });
      } else {
        await createAgent({ ...draft });
      }
      setDraft(emptyDraft);
      setEditingId('');
      await refresh();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    }
  }

  function startEdit(a: Agent) {
    setEditingId(a.id);
    setDraft(draftFromAgent(a));
    setError('');
  }

  async function remove(a: Agent) {
    if (!window.confirm(`Delete agent "${a.name}"?`)) return;
    try {
      await deleteAgent(a.id);
      if (editingId === a.id) {
        setEditingId('');
        setDraft(emptyDraft);
      }
      await refresh();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Agents</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="agents-layout">
            <div>
              <div className="agents-list-head">
                <span>Your agents</span>
                <button className="btn-small" onClick={() => { setEditingId(''); setDraft(emptyDraft); setError(''); }}>
                  + New
                </button>
              </div>
              <div className="agents-list">
                {loading && <div className="agents-empty">Loading…</div>}
                {!loading && agents.length === 0 && (
                  <div className="agents-empty">No agents yet. Create your first one.</div>
                )}
                {agents.map((a) => (
                  <div key={a.id} className={`agent-item${editingId === a.id ? ' editing' : ''}`}>
                    <div className="agent-item-main" onClick={() => startEdit(a)}>
                      <div className="agent-item-name">{a.name}</div>
                      <div className="agent-item-meta">
                        {a.model_provider} · {a.model}
                      </div>
                      {a.description && <div className="agent-item-desc">{a.description}</div>}
                    </div>
                    <button className="agent-item-delete" onClick={() => remove(a)}>
                      <TrashIcon />
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <form className="agent-form" onSubmit={save}>
              <div className="section-title">
                {editingId ? 'Edit agent' : 'Create agent'}
              </div>
              <label>
                Name
                <input
                  value={draft.name}
                  onChange={(e) => set('name', e.target.value)}
                  placeholder="e.g. Code Reviewer"
                />
              </label>
              <label>
                Description
                <input
                  value={draft.description}
                  onChange={(e) => set('description', e.target.value)}
                  placeholder="What does this agent do?"
                />
              </label>
              <div className="agent-form-row">
                <label>
                  Provider
                  <select
                    value={draft.model_provider}
                    onChange={(e) => {
                      const provider = e.target.value;
                      const models = MODELS[provider] ?? [];
                      setDraft((d) => ({
                        ...d,
                        model_provider: provider,
                        model: models[0] ?? d.model,
                      }));
                    }}
                  >
                    {PROVIDERS.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Model
                  <select value={draft.model} onChange={(e) => set('model', e.target.value)}>
                    {(MODELS[draft.model_provider] ?? []).map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Temperature
                  <input
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    value={draft.temperature}
                    onChange={(e) => set('temperature', Number(e.target.value))}
                  />
                </label>
              </div>
              <label>
                System prompt
                <textarea
                  rows={4}
                  value={draft.system_prompt}
                  onChange={(e) => set('system_prompt', e.target.value)}
                  placeholder="Instructions the agent follows…"
                />
              </label>
              <div>
                <div className="agent-kb-label">Knowledge bases</div>
                {knowledgeBases.length === 0 ? (
                  <div className="agents-empty">No knowledge bases available.</div>
                ) : (
                  <div className="agent-kb-list">
                    {knowledgeBases.map((kb) => (
                      <label key={kb.id} className="agent-kb-item">
                        <input
                          type="checkbox"
                          checked={draft.knowledge_base_ids.includes(kb.id)}
                          onChange={(e) => {
                            const ids = e.target.checked
                              ? [...draft.knowledge_base_ids, kb.id]
                              : draft.knowledge_base_ids.filter((id) => id !== kb.id);
                            set('knowledge_base_ids', ids);
                          }}
                        />
                        {kb.name}
                      </label>
                    ))}
                  </div>
                )}
              </div>
              <div className="agent-form-actions">
                <button type="submit" className="auth-submit">
                  {editingId ? 'Update agent' : 'Create agent'}
                </button>
                {editingId && (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      setEditingId('');
                      setDraft(emptyDraft);
                    }}
                  >
                    Cancel
                  </button>
                )}
              </div>
              {error && <div className="form-error">{error}</div>}
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
