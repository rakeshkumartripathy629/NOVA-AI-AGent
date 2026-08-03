import { type FormEvent, useEffect, useState } from 'react';
import { resetPassword } from '../lib/api';

export default function ResetPasswordPage() {
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setToken(params.get('token') ?? '');
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setMessage('');
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match');
      return;
    }
    if (!token) {
      setError('Missing reset token. Open the link from your email again.');
      return;
    }
    setBusy(true);
    try {
      const resp = await resetPassword(token, password);
      setMessage(resp.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  };

  if (message) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-brand">
            <div className="auth-logo">N</div>
            <h1>Nova AI</h1>
            <p>Password reset</p>
          </div>
          <div className="auth-error" style={{ background: 'rgba(40, 167, 69, 0.12)', color: 'inherit' }}>
            {message}
          </div>
          <a href="/" className="auth-submit" style={{ display: 'block', textAlign: 'center' }}>
            Go to login
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="auth-logo">N</div>
          <h1>Nova AI</h1>
          <p>Reset your password</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <label>
            New password
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
            />
          </label>
          <label>
            Confirm password
            <input
              type="password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
            />
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button type="submit" className="auth-submit" disabled={busy}>
            {busy ? 'Please wait…' : 'Reset password'}
          </button>
          <a href="/" className="auth-error" style={{ textAlign: 'center', display: 'block' }}>
            Back to login
          </a>
        </form>
      </div>
    </div>
  );
}
