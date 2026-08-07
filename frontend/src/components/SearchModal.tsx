import { useState } from 'react';
import { searchWorkspace, type SearchHit } from '../lib/api';
import { SearchIcon } from '../lib/icons';

interface Props {
  onClose: () => void;
  onOpenConversation: (id: string) => void;
}

const SCOPES = [
  { id: 'all', label: 'All' },
  { id: 'conversations', label: 'Conversations' },
  { id: 'messages', label: 'Messages' },
  { id: 'knowledge_bases', label: 'Knowledge' },
  { id: 'files', label: 'Files' },
  { id: 'projects', label: 'Projects' },
];

export default function SearchModal({ onClose, onOpenConversation }: Props) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('all');
  const [results, setResults] = useState<SearchHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function run() {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError('');
    try {
      const scopes = scope === 'all' ? undefined : [scope];
      const hits = await searchWorkspace(q, scopes, 25);
      setResults(hits);
      setSearched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed');
    } finally {
      setLoading(false);
    }
  }

  function open(hit: SearchHit) {
    if (hit.type === 'conversation' || hit.type === 'message') {
      onOpenConversation(hit.id);
      onClose();
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg search-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Search workspace</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <form
            className="search-bar"
            onSubmit={(e) => {
              e.preventDefault();
              run();
            }}
          >
            <SearchIcon />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search conversations, messages, files, knowledge…"
            />
            <button type="submit" className="btn-small">
              Search
            </button>
          </form>
          <div className="search-scopes">
            {SCOPES.map((s) => (
              <button
                key={s.id}
                className={`scope-chip${scope === s.id ? ' active' : ''}`}
                onClick={() => setScope(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
          {error && <div className="form-error">{error}</div>}
          {loading && <div className="agents-empty">Searching…</div>}
          {!loading && searched && results.length === 0 && (
            <div className="agents-empty">No results for “{query}”.</div>
          )}
          {!loading && results.length > 0 && (
            <div className="search-results">
              {results.map((h) => (
                <button
                  key={h.type + h.id}
                  className="search-result"
                  onClick={() => open(h)}
                  title={h.url}
                >
                  <span className={`search-type t-${h.type}`}>{h.type}</span>
                  <span className="search-result-main">
                    <span className="search-result-title">{h.title}</span>
                    {h.snippet && <span className="search-result-snippet">{h.snippet}</span>}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
