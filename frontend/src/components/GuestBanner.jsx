/**
 * GuestBanner.jsx — Sticky top banner for guest users showing usage limits
 * and upgrade prompts. Disappears when user is authenticated.
 */
import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';

function UsageBar({ label, current, limit, color = '#6366f1' }) {
  const pct = limit > 0 ? Math.min(100, (current / limit) * 100) : 0;
  const isWarning = pct >= 70;
  const isDanger = pct >= 90;
  const barColor = isDanger ? '#ef4444' : isWarning ? '#f59e0b' : color;

  return (
    <div className="guest-usage-item">
      <div className="guest-usage-label">
        <span>{label}</span>
        <span style={{ color: isDanger ? '#ef4444' : 'var(--text-secondary)' }}>
          {current}/{limit}
        </span>
      </div>
      <div className="guest-usage-track">
        <div
          className="guest-usage-bar"
          style={{ width: `${pct}%`, backgroundColor: barColor, transition: 'width 0.4s ease' }}
        />
      </div>
    </div>
  );
}

function GuestBanner({ onSignUp, onLogin }) {
  const { isGuest, isAuthenticated, guestUsage, guestLimits } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  if (!isGuest || isAuthenticated || dismissed) return null;

  // Check if any limit is near/exceeded
  const usageItems = [
    { label: 'Uploads', key: 'upload_count' },
    { label: 'Questions', key: 'query_count' },
    { label: 'Reports', key: 'report_count' },
    { label: 'Exports', key: 'export_count' },
  ];

  const anyNearLimit = usageItems.some(({ key }) => {
    const limit = guestLimits?.[key] ?? 0;
    const curr = guestUsage?.[key] ?? 0;
    return limit > 0 && curr / limit >= 0.6;
  });

  return (
    <div className={`guest-banner ${anyNearLimit ? 'guest-banner-warning' : ''}`}>
      <div className="guest-banner-main">
        <div className="guest-banner-left">
          <span className="guest-badge">GUEST MODE</span>
          <span className="guest-banner-msg">
            {anyNearLimit
              ? '⚠️ You\'re approaching your guest limits. Sign up to continue.'
              : '👋 Trying DataPilot as a guest — limited access.'}
          </span>
        </div>
        <div className="guest-banner-actions">
          <button
            className="guest-usage-toggle"
            onClick={() => setExpanded(v => !v)}
            aria-label="Toggle usage details"
          >
            {expanded ? '▲ Hide Usage' : '▼ View Usage'}
          </button>
          <button className="guest-login-btn" onClick={onLogin}>
            Sign In
          </button>
          <button className="guest-signup-btn" onClick={onSignUp}>
            ✨ Sign Up Free
          </button>
          <button className="guest-dismiss-btn" onClick={() => setDismissed(true)} aria-label="Dismiss banner">
            ✕
          </button>
        </div>
      </div>

      {expanded && (
        <div className="guest-banner-usage">
          <div className="guest-usage-grid">
            {usageItems.map(({ label, key }) => (
              <UsageBar
                key={key}
                label={label}
                current={guestUsage?.[key] ?? 0}
                limit={guestLimits?.[key] ?? 0}
              />
            ))}
          </div>
          <div className="guest-upgrade-card">
            <strong>🚀 Sign up free</strong>
            <ul>
              <li>✓ 20 file uploads/month</li>
              <li>✓ 200 AI questions/month</li>
              <li>✓ Unlimited saved reports</li>
              <li>✓ Persistent chat history</li>
              <li>✓ Team workspaces</li>
            </ul>
            <button className="guest-signup-btn-large" onClick={onSignUp}>
              Create Free Account →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default GuestBanner;
