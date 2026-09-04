import { useState } from 'react';

interface Props {
  url: string;
  alt?: string;
}

export default function ImageMessage({ url, alt }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  if (error) {
    return (
      <div style={{
        padding: '16px',
        background: 'var(--bg)',
        borderRadius: '12px',
        border: '1px solid var(--border)',
        color: 'var(--text-dim)',
        fontSize: '13px',
      }}>
        ⚠️ Image failed to load. <a href={url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>Open in browser</a>
      </div>
    );
  }

  return (
    <div style={{ margin: '8px 0' }}>
      {loading && (
        <div style={{
          padding: '40px',
          textAlign: 'center',
          background: 'var(--bg)',
          borderRadius: '12px',
          border: '1px solid var(--border)',
          color: 'var(--text-dim)',
          fontSize: '13px',
        }}>
          🎨 Loading image...
        </div>
      )}
      <img
        src={url}
        alt={alt || 'Generated image'}
        onLoad={() => setLoading(false)}
        onError={() => { setLoading(false); setError(true); }}
        style={{
          maxWidth: '100%',
          maxHeight: '512px',
          borderRadius: '12px',
          display: loading ? 'none' : 'block',
          border: '1px solid var(--border)',
        }}
      />
    </div>
  );
}
