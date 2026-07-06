/**
 * AuthModal.jsx — Premium login/signup/forgot-password modal.
 * Three tabs: Login, Sign Up, Forgot Password.
 * Detects if user is a guest and shows conversion flow with data preservation option.
 */
import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';

function AuthModal({ open, onClose, defaultTab = 'login', title = null }) {
  const { login, signup, forgotPassword, convertGuest, isGuest, addToast } = useAuth();
  const [tab, setTab] = useState(defaultTab);
  const [form, setForm] = useState({
    email: '', password: '', confirmPassword: '', fullName: '', workspaceName: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    setTab(defaultTab);
    setError(''); setSuccess('');
  }, [open, defaultTab]);

  if (!open) return null;

  const update = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const handleLogin = async (e) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      await login(form.email, form.password);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally { setLoading(false); }
  };

  const handleSignup = async (e) => {
    e.preventDefault();
    setError('');
    if (form.password !== form.confirmPassword) return setError('Passwords do not match.');
    if (form.password.length < 8) return setError('Password must be at least 8 characters.');
    setLoading(true);
    try {
      if (isGuest) {
        // Convert guest → user with data preservation
        await convertGuest(form.email, form.password, form.fullName, form.workspaceName, true);
        onClose();
      } else {
        await signup(form.email, form.password, form.fullName, form.workspaceName);
        setSuccess('Account created! Please check your email to verify your account, then log in.');
        setTab('login');
      }
    } catch (err) {
      setError(err.message);
    } finally { setLoading(false); }
  };

  const handleForgot = async (e) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      await forgotPassword(form.email);
      setSuccess('If that email is registered, a reset link has been sent.');
    } catch (err) {
      setError(err.message);
    } finally { setLoading(false); }
  };

  return (
    <div className="auth-modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="auth-modal">
        {/* Header */}
        <div className="auth-modal-header">
          <div className="auth-modal-logo">
            <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="8" fill="url(#authGrad)" />
              <path d="M8 22L14 12L18 18L22 14L26 22" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              <defs>
                <linearGradient id="authGrad" x1="0" y1="0" x2="32" y2="32">
                  <stop stopColor="#6366f1"/>
                  <stop offset="1" stopColor="#8b5cf6"/>
                </linearGradient>
              </defs>
            </svg>
            <span>DataPilot</span>
          </div>
          <button className="auth-modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Guest upgrade prompt */}
        {isGuest && tab === 'signup' && (
          <div className="auth-guest-banner">
            <span>🎉</span>
            <div>
              <strong>Save your work!</strong>
              <p>Your uploaded files, analyses, and chat history will be preserved in your new account.</p>
            </div>
          </div>
        )}

        {/* Title */}
        <h2 className="auth-modal-title">
          {title || (tab === 'login' ? 'Welcome back' : tab === 'signup' ? (isGuest ? 'Create your free account' : 'Get started free') : 'Reset password')}
        </h2>
        {tab === 'login' && <p className="auth-modal-subtitle">Sign in to your DataPilot account</p>}
        {tab === 'signup' && <p className="auth-modal-subtitle">No credit card required · Free forever plan</p>}

        {/* Tabs */}
        <div className="auth-tabs">
          <button className={`auth-tab ${tab === 'login' ? 'active' : ''}`} onClick={() => { setTab('login'); setError(''); setSuccess(''); }}>
            Sign In
          </button>
          <button className={`auth-tab ${tab === 'signup' ? 'active' : ''}`} onClick={() => { setTab('signup'); setError(''); setSuccess(''); }}>
            Sign Up
          </button>
        </div>

        {/* Error / Success */}
        {error && <div className="auth-alert auth-alert-error">{error}</div>}
        {success && <div className="auth-alert auth-alert-success">{success}</div>}

        {/* Login Form */}
        {tab === 'login' && (
          <form className="auth-form" onSubmit={handleLogin} autoComplete="on">
            <div className="auth-field">
              <label>Email</label>
              <input type="email" placeholder="you@example.com" value={form.email} onChange={e => update('email', e.target.value)} required autoFocus />
            </div>
            <div className="auth-field">
              <label>Password</label>
              <div className="auth-password-wrapper">
                <input type={showPassword ? 'text' : 'password'} placeholder="••••••••" value={form.password} onChange={e => update('password', e.target.value)} required />
                <button type="button" className="auth-password-toggle" onClick={() => setShowPassword(v => !v)}>
                  {showPassword ? '🙈' : '👁️'}
                </button>
              </div>
            </div>
            <div className="auth-forgot-row">
              <button type="button" className="auth-link" onClick={() => { setTab('forgot'); setError(''); }}>
                Forgot password?
              </button>
            </div>
            <button type="submit" className="auth-submit-btn" disabled={loading}>
              {loading ? <span className="auth-spinner" /> : 'Sign In'}
            </button>
            <p className="auth-switch">
              Don't have an account?{' '}
              <button type="button" className="auth-link" onClick={() => { setTab('signup'); setError(''); }}>
                Sign up free
              </button>
            </p>
          </form>
        )}

        {/* Signup Form */}
        {tab === 'signup' && (
          <form className="auth-form" onSubmit={handleSignup} autoComplete="on">
            <div className="auth-field">
              <label>Full Name</label>
              <input type="text" placeholder="Your name" value={form.fullName} onChange={e => update('fullName', e.target.value)} />
            </div>
            <div className="auth-field">
              <label>Email <span className="auth-required">*</span></label>
              <input type="email" placeholder="you@example.com" value={form.email} onChange={e => update('email', e.target.value)} required autoFocus />
            </div>
            <div className="auth-field">
              <label>Password <span className="auth-required">*</span></label>
              <div className="auth-password-wrapper">
                <input type={showPassword ? 'text' : 'password'} placeholder="Min 8 characters" value={form.password} onChange={e => update('password', e.target.value)} required minLength={8} />
                <button type="button" className="auth-password-toggle" onClick={() => setShowPassword(v => !v)}>
                  {showPassword ? '🙈' : '👁️'}
                </button>
              </div>
            </div>
            <div className="auth-field">
              <label>Confirm Password <span className="auth-required">*</span></label>
              <input type="password" placeholder="Repeat password" value={form.confirmPassword} onChange={e => update('confirmPassword', e.target.value)} required />
            </div>
            <div className="auth-field">
              <label>Workspace Name <span className="auth-optional">(optional)</span></label>
              <input type="text" placeholder="My Workspace" value={form.workspaceName} onChange={e => update('workspaceName', e.target.value)} />
            </div>
            <button type="submit" className="auth-submit-btn" disabled={loading}>
              {loading ? <span className="auth-spinner" /> : (isGuest ? '✨ Save My Work & Sign Up' : 'Create Free Account')}
            </button>
            <p className="auth-switch">
              Already have an account?{' '}
              <button type="button" className="auth-link" onClick={() => { setTab('login'); setError(''); }}>
                Sign in
              </button>
            </p>
            <p className="auth-terms">By signing up you agree to our Terms of Service.</p>
          </form>
        )}

        {/* Forgot Password Form */}
        {tab === 'forgot' && (
          <form className="auth-form" onSubmit={handleForgot}>
            <p className="auth-forgot-desc">Enter your email and we'll send you a reset link.</p>
            <div className="auth-field">
              <label>Email</label>
              <input type="email" placeholder="you@example.com" value={form.email} onChange={e => update('email', e.target.value)} required autoFocus />
            </div>
            <button type="submit" className="auth-submit-btn" disabled={loading}>
              {loading ? <span className="auth-spinner" /> : 'Send Reset Link'}
            </button>
            <p className="auth-switch">
              <button type="button" className="auth-link" onClick={() => { setTab('login'); setError(''); }}>
                ← Back to Sign In
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}

export default AuthModal;
