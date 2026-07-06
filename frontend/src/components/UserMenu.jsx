/**
 * UserMenu.jsx — Avatar + dropdown for authenticated users.
 * Shows user info, workspace name, and logout option.
 */
import { useState, useRef, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';

function UserMenu({ onSettings }) {
  const { user, logout, isAuthenticated, isGuest } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!isAuthenticated && !isGuest) return null;

  const initials = user?.email ? user.email[0].toUpperCase() : 'G';
  const displayName = user?.full_name || user?.email?.split('@')[0] || 'Guest';

  return (
    <div className="user-menu" ref={ref}>
      <button
        className="user-avatar-btn"
        onClick={() => setOpen(v => !v)}
        aria-label="User menu"
        aria-expanded={open}
      >
        <div className="user-avatar">
          {user?.avatar_url
            ? <img src={user.avatar_url} alt={displayName} />
            : <span>{initials}</span>
          }
        </div>
        {isAuthenticated && <span className="user-name-chip">{displayName}</span>}
        {isGuest && <span className="guest-chip">Guest</span>}
        <span className="user-chevron">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="user-dropdown">
          {isAuthenticated && (
            <>
              <div className="user-dropdown-header">
                <div className="user-dropdown-avatar">{initials}</div>
                <div>
                  <div className="user-dropdown-name">{user?.full_name || displayName}</div>
                  <div className="user-dropdown-email">{user?.email}</div>
                </div>
              </div>
              <div className="user-dropdown-divider" />
              {onSettings && (
                <button className="user-dropdown-item" onClick={() => { setOpen(false); onSettings(); }}>
                  ⚙️ Settings
                </button>
              )}
              <button className="user-dropdown-item user-dropdown-logout" onClick={() => { setOpen(false); logout(); }}>
                🚪 Sign Out
              </button>
            </>
          )}
          {isGuest && (
            <div className="user-dropdown-guest">
              <p>You're browsing as a Guest.</p>
              <p>Sign up to save your work!</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default UserMenu;
