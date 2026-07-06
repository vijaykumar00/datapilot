"""
rbac.py — Role-Based Access Control middleware and FastAPI dependencies.

Roles (in ascending permission order):
  Viewer   — read-only dashboard access
  Member   — upload, query, save own reports
  Admin    — manage datasets, reports, members
  Owner    — full workspace management

Security rules:
  - Cross-workspace access returns 404 (not 403) to prevent enumeration.
  - JWT claims are minimal; roles are always validated from the database.
  - Guest sessions have their own separate isolation chain.
"""
import logging
from typing import Optional, Literal
from fastapi import Depends, Header, HTTPException, status, Request
from sqlalchemy.orm import Session

from core.db import get_db
from core.auth import decode_access_token
from core.models import User, WorkspaceMember, GuestSession
import datetime
import hashlib

logger = logging.getLogger("datapilot.rbac")

ROLE_HIERARCHY = {"Viewer": 1, "Member": 2, "Admin": 3, "Owner": 4}

RoleType = Literal["Viewer", "Member", "Admin", "Owner"]


# ─────────────────────────────────────────────────────────────
# Token Extraction
# ─────────────────────────────────────────────────────────────

def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Extract Bearer token from Authorization header."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


# ─────────────────────────────────────────────────────────────
# Current User Dependencies
# ─────────────────────────────────────────────────────────────

def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Returns the current user if authenticated, or None for guests."""
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    claims = decode_access_token(token)
    if not claims:
        return None
    user = db.query(User).filter(
        User.user_id == claims["user_id"],
        User.is_active == True
    ).first()
    return user


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Requires authentication. Raises 401 if not authenticated."""
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_access_token(token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(
        User.user_id == claims["user_id"],
        User.is_active == True,
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or deactivated.",
        )
    return user


def get_current_user_id(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """Returns just the user_id string. Raises 401 if not authenticated."""
    return get_current_user(authorization=authorization, db=db).user_id


# ─────────────────────────────────────────────────────────────
# Workspace + Role Validation
# ─────────────────────────────────────────────────────────────

def get_workspace_member(
    user: User,
    workspace_id: str,
    db: Session,
    required_role: Optional[RoleType] = None,
) -> WorkspaceMember:
    """
    Validates that a user is a member of the given workspace.
    Returns 404 (not 403) to prevent resource enumeration.
    Optionally enforces a minimum role level.
    """
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.user_id,
        WorkspaceMember.workspace_id == workspace_id,
    ).first()

    if not member:
        # Return 404 to prevent workspace enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )

    if required_role:
        user_level = ROLE_HIERARCHY.get(member.role, 0)
        required_level = ROLE_HIERARCHY.get(required_role, 999)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {required_role}, your role: {member.role}.",
            )

    return member


# ─────────────────────────────────────────────────────────────
# Role-specific FastAPI Dependency Factories
# ─────────────────────────────────────────────────────────────

def _make_workspace_dep(required_role: RoleType):
    """Factory that creates a FastAPI dependency enforcing a workspace role."""
    def dep(
        workspace_id: str,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> WorkspaceMember:
        return get_workspace_member(user, workspace_id, db, required_role)
    dep.__name__ = f"require_{required_role.lower()}"
    return dep


# Use these as FastAPI dependencies in route handlers:
#   member: WorkspaceMember = Depends(require_viewer("workspace_id"))
require_viewer  = _make_workspace_dep("Viewer")
require_member  = _make_workspace_dep("Member")
require_admin   = _make_workspace_dep("Admin")
require_owner   = _make_workspace_dep("Owner")


# ─────────────────────────────────────────────────────────────
# Guest Session Dependencies
# ─────────────────────────────────────────────────────────────

def get_guest_session(
    x_guest_token: Optional[str] = Header(None, alias="X-Guest-Token"),
    db: Session = Depends(get_db),
) -> Optional[GuestSession]:
    """Returns the guest session if the X-Guest-Token header is valid, else None."""
    if not x_guest_token:
        return None
    token_hash = hashlib.sha256(x_guest_token.encode()).hexdigest()
    guest = db.query(GuestSession).filter(
        GuestSession.session_token == token_hash,
        GuestSession.expires_at > datetime.datetime.utcnow(),
        GuestSession.converted_to_user_id == None,
    ).first()
    return guest


def require_guest_session(
    x_guest_token: Optional[str] = Header(None, alias="X-Guest-Token"),
    db: Session = Depends(get_db),
) -> GuestSession:
    """Requires a valid guest session token. Raises 401 if missing or expired."""
    guest = get_guest_session(x_guest_token=x_guest_token, db=db)
    if not guest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid guest session required. Please start a guest session.",
        )
    return guest


# ─────────────────────────────────────────────────────────────
# Unified Context: Either Auth User OR Guest
# ─────────────────────────────────────────────────────────────

class RequestContext:
    """Unified context holding either an authenticated user or a guest session."""
    def __init__(
        self,
        user: Optional[User] = None,
        guest: Optional[GuestSession] = None,
        workspace_id: Optional[str] = None,
    ):
        self.user = user
        self.guest = guest
        self.workspace_id = workspace_id
        self.is_guest = guest is not None
        self.is_authenticated = user is not None

    @property
    def user_id(self) -> Optional[str]:
        return self.user.user_id if self.user else None

    @property
    def guest_session_id(self) -> Optional[str]:
        return self.guest.guest_session_id if self.guest else None


def get_request_context(
    authorization: Optional[str] = Header(None),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID"),
    x_guest_token: Optional[str] = Header(None, alias="X-Guest-Token"),
    db: Session = Depends(get_db),
) -> RequestContext:
    """
    Returns a RequestContext with either authenticated user or guest session.
    Used for endpoints that support both modes.
    """
    # Try authenticated user first
    user = get_current_user_optional(authorization=authorization, db=db)
    if user:
        workspace_id = x_workspace_id
        if not workspace_id:
            # Default to user's first workspace
            from core.models import WorkspaceMember
            membership = db.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user.user_id
            ).first()
            workspace_id = membership.workspace_id if membership else None
        return RequestContext(user=user, workspace_id=workspace_id)

    # Try guest session
    if x_guest_token:
        token_hash = hashlib.sha256(x_guest_token.encode()).hexdigest()
        guest = db.query(GuestSession).filter(
            GuestSession.session_token == token_hash,
            GuestSession.expires_at > datetime.datetime.utcnow(),
            GuestSession.converted_to_user_id == None,
        ).first()
        if guest:
            return RequestContext(guest=guest)

    # Anonymous (no context)
    return RequestContext()
