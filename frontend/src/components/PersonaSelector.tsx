import { useEffect, useState } from 'react';
import * as api from '../lib/api';

interface Props {
  selectedId: string | null;
  onSelect: (persona: api.Persona | null) => void;
  onClose: () => void;
}

export default function PersonaSelector({ selectedId, onSelect, onClose }: Props) {
  const [personas, setPersonas] = useState<api.Persona[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    api
      .listPersonas()
      .then(setPersonas)
      .catch(() => setPersonas([]))
      .finally(() => setLoading(false));
  }, []);

  const categories = [...new Set(personas.map((p) => p.category))];
  const filtered = personas.filter(
    (p) =>
      p.name.toLowerCase().includes(filter.toLowerCase()) ||
      p.description.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="persona-overlay" onClick={onClose}>
      <div className="persona-modal" onClick={(e) => e.stopPropagation()}>
        <div className="persona-header">
          <h3>Choose a Persona</h3>
          <button className="persona-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <input
          className="persona-search"
          placeholder="Search personas..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          autoFocus
        />

        {loading ? (
          <div className="persona-loading">Loading personas...</div>
        ) : (
          <div className="persona-grid">
            {filtered.map((p) => (
              <button
                key={p.id}
                className={`persona-card${selectedId === p.id ? ' selected' : ''}`}
                onClick={() => {
                  onSelect(p.id === selectedId ? null : p);
                  onClose();
                }}
              >
                <div className="persona-emoji">{p.avatar_emoji}</div>
                <div className="persona-info">
                  <span className="persona-name">{p.name}</span>
                  <span className="persona-desc">{p.description}</span>
                  <span className="persona-category">{p.category}</span>
                </div>
                {selectedId === p.id && <span className="persona-check">✓</span>}
              </button>
            ))}
            {filtered.length === 0 && (
              <div className="persona-empty">No personas found</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
