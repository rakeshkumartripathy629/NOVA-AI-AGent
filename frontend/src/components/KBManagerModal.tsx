import { useEffect, useState } from 'react';
import {
  deleteKnowledgeBase,
  deleteKnowledgeBaseDocument,
  listKnowledgeBaseDocuments,
  type KnowledgeBase,
  type KnowledgeBaseDocument,
} from '../lib/api';
import { TrashIcon } from '../lib/icons';

interface Props {
  knowledgeBases: KnowledgeBase[];
  selectedKb: string;
  onClose: () => void;
  onChanged: () => void;
}

export default function KBManagerModal({
  knowledgeBases,
  selectedKb,
  onClose,
  onChanged,
}: Props) {
  const [kbId, setKbId] = useState(selectedKb);
  const [docs, setDocs] = useState<KnowledgeBaseDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    setKbId(selectedKb);
  }, [selectedKb]);

  useEffect(() => {
    if (!kbId) {
      setDocs([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    listKnowledgeBaseDocuments(kbId)
      .then((d) => {
        if (!cancelled) setDocs(d);
      })
      .catch(() => {
        if (!cancelled) setDocs([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [kbId]);

  async function handleDeleteDoc(docId: string) {
    if (!window.confirm('Delete this document?')) return;
    setBusyId(docId);
    setMessage('');
    try {
      await deleteKnowledgeBaseDocument(kbId, docId);
      setDocs((d) => d.filter((x) => x.id !== docId));
      onChanged();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setBusyId('');
    }
  }

  async function handleDeleteKb() {
    if (!window.confirm('Delete this entire knowledge base and all its documents?'))
      return;
    setMessage('');
    try {
      await deleteKnowledgeBase(kbId);
      setKbId('');
      onChanged();
      onClose();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Delete failed');
    }
  }

  const kb = knowledgeBases.find((k) => k.id === kbId);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Knowledge base</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <select
            className="kb-manager-select"
            value={kbId}
            onChange={(e) => setKbId(e.target.value)}
          >
            {knowledgeBases.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
          {kb && (
            <div className="kb-manager-meta">
              {kb.document_count} documents · {kb.total_chunks} chunks
              {kb.is_indexed ? ' · indexed' : ' · not indexed'}
            </div>
          )}
          <div className="kb-manager-head">
            <span className="section-title">Documents</span>
            <button className="btn-small btn-danger" onClick={handleDeleteKb}>
              Delete KB
            </button>
          </div>
          {loading && <div className="agents-empty">Loading…</div>}
          {!loading && docs.length === 0 && (
            <div className="agents-empty">No documents in this knowledge base.</div>
          )}
          <div className="kb-manager-list">
            {docs.map((d) => (
              <div key={d.id} className="kb-manager-item">
                <div className="kb-manager-item-main">
                  <div className="kb-manager-item-name" title={d.title}>
                    {d.title}
                  </div>
                  <div className="kb-manager-item-meta">
                    {d.source_type} · {d.status} · {d.chunk_count} chunks
                  </div>
                </div>
                <button
                  className="agent-item-delete"
                  disabled={busyId === d.id}
                  onClick={() => handleDeleteDoc(d.id)}
                >
                  <TrashIcon /> {busyId === d.id ? '…' : ''}
                </button>
              </div>
            ))}
          </div>
          {message && <div className="form-error">{message}</div>}
        </div>
      </div>
    </div>
  );
}
