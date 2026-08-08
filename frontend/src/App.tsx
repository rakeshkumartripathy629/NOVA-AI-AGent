import { AuthProvider, useAuth } from './context/AuthContext';
import LoginPage from './components/LoginPage';
import ChatPage from './components/ChatPage';
import ResetPasswordPage from './components/ResetPasswordPage';
import SharePage from './components/SharePage';
import AuthCallbackPage from './components/AuthCallbackPage';

function Root() {
  const { user, loading } = useAuth();

  if (window.location.pathname.startsWith('/reset-password')) {
    return <ResetPasswordPage />;
  }

  if (window.location.pathname.startsWith('/share/')) {
    const token = window.location.pathname.slice('/share/'.length).split('/')[0];
    return <SharePage token={token} />;
  }

  if (window.location.pathname.startsWith('/auth/callback')) {
    return <AuthCallbackPage />;
  }

  if (loading) {
    return <div className="boot-screen">Loading Nova AI…</div>;
  }

  return user ? <ChatPage /> : <LoginPage />;
}

export default function App() {
  return (
    <AuthProvider>
      <Root />
    </AuthProvider>
  );
}
