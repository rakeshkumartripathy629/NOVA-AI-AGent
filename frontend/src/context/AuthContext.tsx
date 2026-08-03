import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import * as api from '../lib/api';

interface AuthState {
  user: api.User | null;
  organization: api.Organization | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (input: api.RegisterInput) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<api.User | null>(null);
  const [organization, setOrganization] = useState<api.Organization | null>(null);
  const [loading, setLoading] = useState(true);

  const applyAuth = useCallback((auth: api.AuthResponse) => {
    api.setToken(auth.access_token);
    setUser(auth.user);
    setOrganization(auth.organization);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!api.getToken()) {
        setLoading(false);
        return;
      }
      try {
        const me = await api.fetchMe();
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) {
          api.setToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const auth = await api.login(email, password);
      applyAuth(auth);
    },
    [applyAuth],
  );

  const signUp = useCallback(
    async (input: api.RegisterInput) => {
      const auth = await api.register(input);
      applyAuth(auth);
    },
    [applyAuth],
  );

  const signOut = useCallback(() => {
    api.logout();
    setUser(null);
    setOrganization(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, organization, loading, signIn, signUp, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
