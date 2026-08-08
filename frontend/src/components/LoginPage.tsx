import { type FormEvent, useEffect, useState } from 'react';
import * as api from '../lib/api';
import { useAuth } from '../context/AuthContext';

export default function LoginPage() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [fullName, setFullName] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [providers, setProviders] = useState<{ google: boolean; github: boolean } | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const oauthError = params.get('oauth_error');
    if (oauthError) {
      const messages: Record<string, string> = {
        provider_denied: 'Sign in with the provider was cancelled.',
        invalid_state: 'Login session expired. Please try again.',
        missing_code: 'The provider did not return an authorization code.',
        unsupported_provider: 'That login provider is not supported.',
        oauth_failed: 'Could not sign in with that provider. Please try again.',
      };
      setError(messages[oauthError] ?? 'Could not sign in with that provider.');
      window.history.replaceState({}, '', window.location.pathname);
    }
    api
      .getOAuthProviders()
      .then(setProviders)
      .catch(() => setProviders({ google: false, github: false }));
  }, []);

  const switchMode = (next: 'login' | 'register') => {
    setMode(next);
    setError('');
    setPassword('');
    setConfirm('');
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
    if (!emailOk) {
      setError('Please enter a valid email address.');
      return;
    }
    if (mode === 'register') {
      if (password.length < 8) {
        setError('Password must be at least 8 characters.');
        return;
      }
      if (password !== confirm) {
        setError('Passwords do not match.');
        return;
      }
    } else if (!password) {
      setError('Please enter your password.');
      return;
    }

    setBusy(true);
    try {
      if (mode === 'login') {
        await signIn(email.trim(), password);
      } else {
        await signUp({ email: email.trim(), password, full_name: fullName.trim() || undefined });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Something went wrong';
      setError(
        mode === 'login' && /login|401|credentials/i.test(msg)
          ? 'Incorrect email or password.'
          : msg,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="auth-logo">N</div>
          <h1>Nova AI</h1>
          <p>Conversational intelligence platform</p>
        </div>

        <div className="auth-tabs">
          <button
            type="button"
            className={mode === 'login' ? 'active' : ''}
            onClick={() => switchMode('login')}
          >
            Sign in
          </button>
          <button
            type="button"
            className={mode === 'register' ? 'active' : ''}
            onClick={() => switchMode('register')}
          >
            Create account
          </button>
        </div>

        {providers && (providers.google || providers.github) && (
          <div className="auth-oauth">
            {providers.google && (
              <button
                type="button"
                className="auth-oauth-btn"
                onClick={() => api.startOAuth('google')}
              >
                <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden="true">
                  <path
                    fill="#FFC107"
                    d="M43.6 20.1H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3l5.7-5.7C34 6.1 29.3 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z"
                  />
                  <path
                    fill="#FF3D00"
                    d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
                  />
                  <path
                    fill="#4CAF50"
                    d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"
                  />
                  <path
                    fill="#1976D2"
                    d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C36.9 40.2 44 36 44 24c0-1.3-.1-2.6-.4-3.9z"
                  />
                </svg>
                Continue with Google
              </button>
            )}
            {providers.github && (
              <button
                type="button"
                className="auth-oauth-btn"
                onClick={() => api.startOAuth('github')}
              >
                <svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"
                  />
                </svg>
                Continue with GitHub
              </button>
            )}
            <div className="auth-divider">
              <span>or</span>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          {mode === 'register' && (
            <label>
              Full name
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Ada Lovelace"
                autoComplete="name"
              />
            </label>
          )}
          <label>
            Email
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
            />
          </label>
          <label>
            Password
            <input
              type={showPassword ? 'text' : 'password'}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </label>
          {mode === 'register' && (
            <label>
              Confirm password
              <input
                type={showPassword ? 'text' : 'password'}
                required
                minLength={8}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="Re-enter your password"
                autoComplete="new-password"
              />
            </label>
          )}
          <label className="auth-show-password">
            <input
              type="checkbox"
              checked={showPassword}
              onChange={(e) => setShowPassword(e.target.checked)}
            />
            Show password
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button type="submit" className="auth-submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  );
}
