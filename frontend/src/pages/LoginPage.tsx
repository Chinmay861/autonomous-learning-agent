import React, { useRef, useState } from 'react';
import { useAuth } from '../context/AuthContext';

type Mode = 'signin' | 'create';

const LoginPage = () => {
  const [mode, setMode] = useState<Mode>('signin');
  const [identifier, setIdentifier] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const { login, register } = useAuth();

  const signInTabRef = useRef<HTMLButtonElement>(null);
  const createTabRef = useRef<HTMLButtonElement>(null);

  const switchMode = (next: Mode) => {
    setMode(next);
    setError('');
    setSuccessMsg('');
  };

  const handleTabKeys = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const next: Mode = mode === 'signin' ? 'create' : 'signin';
      switchMode(next);
      (next === 'signin' ? signInTabRef : createTabRef).current?.focus();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccessMsg('');
    setSubmitting(true);

    try {
      if (mode === 'signin') {
        const formData = new FormData();
        formData.append('username', identifier.trim());
        formData.append('password', password);
        await login(formData);
      } else {
        await register({
          username: username.trim(),
          email: email.trim(),
          password
        });
        setMode('signin');
        setIdentifier(username.trim());
        setSuccessMsg('Account created. Sign in to continue.');
      }
    } catch (err: any) {
      setError(err?.message || 'Unable to sign in. Check your details and try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-900 px-4 py-10">
      <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-800 p-6 shadow-xl sm:p-8">
        <div className="mb-6 text-center">
          <h1 className="mb-2 text-3xl font-bold text-emerald-300">Autonomous Agent</h1>
          <p className="text-sm text-slate-400">
            {mode === 'signin' ? 'Sign in to your workspace' : 'Create your account'}
          </p>
        </div>

        <div
          role="tablist"
          aria-label="Authentication"
          onKeyDown={handleTabKeys}
          className="mb-6 flex border-b border-slate-700"
        >
          <button
            ref={signInTabRef}
            type="button"
            role="tab"
            id="auth-tab-signin"
            aria-selected={mode === 'signin'}
            aria-controls="auth-panel"
            tabIndex={mode === 'signin' ? 0 : -1}
            onClick={() => switchMode('signin')}
            className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
              mode === 'signin'
                ? 'border-b-2 border-emerald-400 text-emerald-300'
                : 'border-b-2 border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Sign in
          </button>
          <button
            ref={createTabRef}
            type="button"
            role="tab"
            id="auth-tab-create"
            aria-selected={mode === 'create'}
            aria-controls="auth-panel"
            tabIndex={mode === 'create' ? 0 : -1}
            onClick={() => switchMode('create')}
            className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
              mode === 'create'
                ? 'border-b-2 border-emerald-400 text-emerald-300'
                : 'border-b-2 border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Create account
          </button>
        </div>

        {error && (
          <div
            role="alert"
            className="mb-6 rounded-lg border border-red-700/60 bg-red-950 px-4 py-3 text-sm text-red-200"
          >
            {error}
          </div>
        )}

        {successMsg && (
          <div
            role="status"
            className="mb-6 rounded-lg border border-emerald-700/60 bg-emerald-950 px-4 py-3 text-sm text-emerald-200"
          >
            {successMsg}
          </div>
        )}

        <form
          id="auth-panel"
          role="tabpanel"
          aria-labelledby={mode === 'signin' ? 'auth-tab-signin' : 'auth-tab-create'}
          onSubmit={handleSubmit}
          className="space-y-4"
        >
          {mode === 'signin' ? (
            <div>
              <label htmlFor="signin-identifier" className="label">
                Username or email
              </label>
              <input
                id="signin-identifier"
                name="username"
                type="text"
                autoComplete="username"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                placeholder="you@example.com"
                className="input"
                required
              />
            </div>
          ) : (
            <>
              <div>
                <label htmlFor="create-username" className="label">
                  Username
                </label>
                <input
                  id="create-username"
                  name="username"
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="your-username"
                  className="input"
                  required
                />
              </div>
              <div>
                <label htmlFor="create-email" className="label">
                  Email
                </label>
                <input
                  id="create-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="input"
                  required
                />
              </div>
            </>
          )}

          <div>
            <label htmlFor="auth-password" className="label">
              Password
            </label>
            <input
              id="auth-password"
              name="password"
              type="password"
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="input"
              minLength={mode === 'create' ? 8 : undefined}
              required
            />
            {mode === 'create' && (
              <span className="hint">Use at least 8 characters.</span>
            )}
          </div>

          <button type="submit" disabled={submitting} className="btn-primary mt-2 w-full">
            {submitting ? 'Signing in…' : mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>
      </div>
    </main>
  );
};

export default LoginPage;
