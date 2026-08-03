import { AuthProvider, useAuth } from './context/AuthContext';
import LoginPage from './components/LoginPage';
import ChatPage from './components/ChatPage';
import ResetPasswordPage from './components/ResetPasswordPage';

function Root() {
  const { user, loading } = useAuth();

  if (window.location.pathname.startsWith('/reset-password')) {
    return <ResetPasswordPage />;
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
