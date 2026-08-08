import { useEffect } from 'react';
import * as api from '../lib/api';

export default function AuthCallbackPage() {
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await api.refreshAccessToken();
      if (!cancelled) window.location.replace('/');
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return <div className="boot-screen">Signing you in…</div>;
}
