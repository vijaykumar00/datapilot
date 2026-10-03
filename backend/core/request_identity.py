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
    PLAN_LIMITS,
    check_ai_budget,
    check_guest_limit,
    check_upload_allowed,
    check_workspace_limit,
    consume_guest,
    consume_workspace,
    effective_plan,
    guest_features,
    increment_guest_usage,
    increment_workspace_usage,
    release_guest,
    release_workspace,
)

ROLE_HIERARCHY = {"Viewer": 1, "Member": 2, "Admin": 3, "Owner": 4}

logger = logging.getLogger("datapilot.identity")


class CallerContext:
    """Unified context for an authenticated user or guest session on analytics endpoints."""

    def __init__(
        self,
        user: Optional[User] = None,
        guest: Optional[GuestSession] = None,
        workspace_id: Optional[str] = None,
        role: Optional[str] = None,
    ):
        self.user = user
        self.guest = guest
        self.workspace_id = workspace_id
        self.role = role if user is not None else ("Owner" if guest is not None else None)
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication or guest session required.",
        )

    def require_active_context(self) -> None:
        """Require either an authenticated workspace or a valid guest session."""
        if self.is_anonymous:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication or guest session required.",
            )
        if self.is_authenticated and not self.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found.",
            )

    # ── Authorization ───────────────────────────────────────────────────
    def require_role(self, minimum: str = "Member") -> None:
        """Mutating routes require at least *minimum* (Viewers are read-only)."""
        self.require_active_context()
        if ROLE_HIERARCHY.get(self.role or "", 0) < ROLE_HIERARCHY.get(minimum, 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {minimum} role in this workspace.",
            )

    # ── Plan / quota ────────────────────────────────────────────────────
    def plan(self, db: Session) -> tuple[str, dict, dict]:
        if self.is_guest:
            return "guest", dict(PLAN_LIMITS["guest"]), guest_features()
        plan_id, limits, features, _ = effective_plan(self.workspace_id, db)
        return plan_id, limits, features

    def require_feature(self, feature_key: str, db: Session, label: str | None = None) -> None:
        plan_id, _, features = self.plan(db)
        if not features.get(feature_key, False):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "FEATURE_NOT_IN_PLAN",
                    "feature": feature_key,
                    "plan": plan_id,
                    "message": f"{label or feature_key.replace('_', ' ')} is not included in your current plan.",
                    "upgrade_prompt": True,
                },
            )

    def check_upload(self, size: int, db: Session) -> None:
        _, limits, _ = self.plan(db)
        check_upload_allowed(self.effective_workspace_id, size, limits, db)

    def check_ai_budget(self, db: Session) -> None:
        if self.is_authenticated and self.workspace_id:
            check_ai_budget(self.workspace_id, db)

    def consume(self, action: str, db: Session, amount: int = 1) -> None:
        """Atomically reserve quota (raises 429 when the limit would be exceeded)."""
        if self.is_guest:
            consume_guest(self.guest, action, db, amount)
        elif self.is_authenticated and self.workspace_id:
            consume_workspace(self.workspace_id, action, db, amount)
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication or guest session required.")

    def release(self, action: str, db: Session, amount: int = 1) -> None:
        """Return quota reserved by :meth:`consume` when the work failed."""
        try:
            if self.is_guest:
                release_guest(self.guest.guest_session_id, action, db, amount)
            elif self.is_authenticated and self.workspace_id:
                release_workspace(self.workspace_id, action, db, amount)
        except Exception as e:
            logger.error("Failed to release usage [%s] for %s: %s", action, self.user_id, e)

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
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication or guest session required.")

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
                    if workspace_id:
                        membership = db.query(WorkspaceMember).filter(
                            WorkspaceMember.user_id == user.user_id,
                            WorkspaceMember.workspace_id == workspace_id,
                        ).first()
                        if not membership:
                            raise HTTPException(
                                status_code=status.HTTP_404_NOT_FOUND,
                                detail="Workspace not found.",
                            )
                    else:
                        membership = db.query(WorkspaceMember).filter(
                            WorkspaceMember.user_id == user.user_id
                        ).first()
                        workspace_id = membership.workspace_id if membership else None
                    return CallerContext(user=user, workspace_id=workspace_id,
                                         role=membership.role if membership else None)
            # A bearer token was supplied but is invalid/expired: never silently
            # downgrade to guest/anonymous — the client must refresh.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token is invalid or expired.",
                headers={"WWW-Authenticate": "Bearer"},
            )

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
