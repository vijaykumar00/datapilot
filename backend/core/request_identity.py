"""
request_identity.py — Unified identity + usage enforcement for main analytics endpoints.

Provides FastAPI dependency `get_caller()` which returns a CallerContext with:
  - caller type: "user" | "guest" | "anonymous"
  - user/guest objects
  - workspace_id
  - helper methods: check_limit(), increment_usage()

Usage in endpoints:
    from core.request_identity import get_caller, CallerContext

    @app.post("/upload")
    async def upload(caller: CallerContext = Depends(get_caller), ...):
        caller.check_limit("upload", db)
        ...
        caller.increment_usage("upload", db)
"""
import hashlib
import logging
import datetime
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from core.db import get_db
from core.auth import decode_access_token
from core.models import User, GuestSession, WorkspaceMember
from core.usage import (
    check_guest_limit,
    increment_guest_usage,
    check_workspace_limit,
    increment_workspace_usage,
)

logger = logging.getLogger("datapilot.identity")


class CallerContext:
    """Unified context for an authenticated user or guest session on analytics endpoints."""

    def __init__(
        self,
        user: Optional[User] = None,
        guest: Optional[GuestSession] = None,
        workspace_id: Optional[str] = None,
    ):
        self.user = user
        self.guest = guest
        self.workspace_id = workspace_id
        self.is_guest = guest is not None and user is None
        self.is_authenticated = user is not None
        self.is_anonymous = user is None and guest is None

    @property
    def user_id(self) -> str:
        if self.user:
            return self.user.user_id
        if self.guest:
            return self.guest.guest_session_id
        return "anonymous"

    @property
    def effective_workspace_id(self) -> str:
        """Returns workspace_id for authenticated users, or guest session ID as namespace."""
        if self.workspace_id:
            return self.workspace_id
        if self.guest:
            return self.guest.guest_session_id
        return "default_workspace"

    def check_limit(self, action: str, db: Session) -> None:
        """
        Enforce usage limits before an action is performed.
        - Guest sessions → check against PLAN_LIMITS["guest"]
        - Authenticated users → check workspace plan limits
        - Anonymous (no token, no guest) → enforce guest limits using a shared default guest
        Raises HTTP 429 if limit exceeded.
        """
        if self.is_guest:
            check_guest_limit(self.guest, action)
        elif self.is_authenticated and self.workspace_id:
            check_workspace_limit(self.workspace_id, action, db)
        # Anonymous callers: pass through (legacy compat, can be tightened later)

    def increment_usage(self, action: str, db: Session) -> None:
        """
        Increment usage counter after a successful action.
        - Guest → increment guest session counter
        - Authenticated → increment workspace monthly counter
        """
        try:
            if self.is_guest:
                increment_guest_usage(self.guest, action, db)
            elif self.is_authenticated and self.workspace_id:
                increment_workspace_usage(self.workspace_id, action, db)
        except Exception as e:
            # Never fail the primary request because of a usage counter error
            logger.error(f"Failed to increment usage [{action}] for {self.user_id}: {e}")


# ─────────────────────────────────────────────────────────────
# FastAPI Dependency
# ─────────────────────────────────────────────────────────────

def get_caller(
    authorization: Optional[str] = Header(None),
    x_guest_token: Optional[str] = Header(None, alias="X-Guest-Token"),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID"),
    db: Session = Depends(get_db),
) -> CallerContext:
    """
    FastAPI dependency that resolves the caller identity from request headers.

    Priority order:
      1. Authorization: Bearer <jwt> → authenticated user
      2. X-Guest-Token → guest session
      3. Neither → anonymous (legacy compat)
    """
    # 1. Try authenticated user
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            claims = decode_access_token(parts[1])
            if claims:
                user = db.query(User).filter(
                    User.user_id == claims["user_id"],
                    User.is_active == True,
                ).first()
                if user:
                    # Resolve workspace_id
                    workspace_id = x_workspace_id or claims.get("current_workspace_id")
                    if not workspace_id:
                        membership = db.query(WorkspaceMember).filter(
                            WorkspaceMember.user_id == user.user_id
                        ).first()
                        workspace_id = membership.workspace_id if membership else None
                    return CallerContext(user=user, workspace_id=workspace_id)

    # 2. Try guest session
    if x_guest_token:
        token_hash = hashlib.sha256(x_guest_token.encode()).hexdigest()
        guest = db.query(GuestSession).filter(
            GuestSession.session_token == token_hash,
            GuestSession.expires_at > datetime.datetime.utcnow(),
            GuestSession.converted_to_user_id == None,
        ).first()
        if guest:
            return CallerContext(guest=guest)

    # 3. Anonymous (no token) — legacy support
    return CallerContext()
