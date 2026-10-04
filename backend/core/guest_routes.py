"""
guest_routes.py — Guest mode session management and guest-to-user conversion.

Guest sessions:
  - Created without authentication
  - Identified by a server-issued token (stored hashed in DB)
  - Expire after GUEST_SESSION_TTL_HOURS (default: 24h)
  - Isolated from other guest sessions (token-based access)
  - Limited by PLAN_LIMITS["guest"]

Guest-to-user conversion:
  - Guest signs up → new User + Workspace created
  - Guest datasets/sessions optionally transferred to new workspace
  - Guest session marked as converted
"""
import datetime
import hashlib
import logging
import secrets
import uuid
from typing import Optional
from fastapi import Response, APIRouter, Depends, HTTPException, Request, status, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import (
    GuestSession, User, Workspace, WorkspaceMember,
    Session as ChatSession, DatasetRegistry, Report, SavedAnalysis,
    EmailVerificationToken, AuditLog, UserSettings,
)
from core.auth import hash_password, hash_token, generate_random_token, create_access_token, REFRESH_TOKEN_EXPIRE_DAYS
from core.models import RefreshToken
from core.usage import PLAN_LIMITS, get_usage_summary
from core.email_service import send_verification_email
import os

logger = logging.getLogger("datapilot.guest")
router = APIRouter(prefix="/guest", tags=["guest"])

GUEST_SESSION_TTL_HOURS = int(os.getenv("GUEST_SESSION_TTL_HOURS", "24"))


# ─────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────

class GuestSessionResponse(BaseModel):
    guest_session_id: str
    guest_token: str
    expires_at: str
    limits: dict
    usage: dict


class ConvertGuestRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    workspace_name: Optional[str] = None
    preserve_data: bool = True


# ─────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────

def _get_guest_from_token(token: str, db: Session) -> Optional[GuestSession]:
    """Retrieve a valid, non-expired, non-converted guest session by raw token."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return db.query(GuestSession).filter(
        GuestSession.session_token == token_hash,
        GuestSession.expires_at > datetime.datetime.utcnow(),
        GuestSession.converted_to_user_id == None,
    ).first()


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/session", response_model=GuestSessionResponse, status_code=status.HTTP_201_CREATED)
def create_guest_session(request: Request, db: Session = Depends(get_db)):
    """
    Create a new guest session. Returns a guest token to be sent as X-Guest-Token header.
    No authentication required.
    """
    raw_token = generate_random_token()
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    guest_id = f"guest_{uuid.uuid4().hex[:12]}"
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=GUEST_SESSION_TTL_HOURS)

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:500]

    guest = GuestSession(
        guest_session_id=guest_id,
        session_token=token_hash,
        ip_address=ip,
        user_agent=ua,
        expires_at=expires_at,
    )
    db.add(guest)

    # Audit log
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        guest_session_id=guest_id,
        event_type="GUEST_SESSION_CREATED",
        description=f"Guest session created from IP: {ip}",
        ip_address=ip,
    ))
    db.commit()

    limits = PLAN_LIMITS["guest"]
    usage = {
        "upload_count": 0, "query_count": 0,
        "report_count": 0, "export_count": 0,
    }

    return GuestSessionResponse(
        guest_session_id=guest_id,
        guest_token=raw_token,
        expires_at=expires_at.isoformat(),
        limits={
            "upload_count": limits["upload_count"],
            "query_count": limits["query_count"],
            "report_count": limits["report_count"],
            "export_count": limits["export_count"],
            "max_file_size_bytes": limits["max_file_size_bytes"],
            "ttl_hours": GUEST_SESSION_TTL_HOURS,
        },
        usage=usage,
    )


@router.get("/session")
def get_guest_session_info(
    x_guest_token: Optional[str] = Header(None, alias="X-Guest-Token"),
    db: Session = Depends(get_db),
):
    """Get the current guest session info and usage."""
    if not x_guest_token:
        raise HTTPException(status_code=401, detail="X-Guest-Token header required.")

    guest = _get_guest_from_token(x_guest_token, db)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest session not found or expired.")

    limits = PLAN_LIMITS["guest"]
    return {
        "guest_session_id": guest.guest_session_id,
        "expires_at": guest.expires_at.isoformat(),
        "usage": {
            "upload_count": guest.upload_count,
            "query_count": guest.query_count,
            "report_count": guest.report_count,
            "export_count": guest.export_count,
        },
        "limits": {
            "upload_count": limits["upload_count"],
            "query_count": limits["query_count"],
            "report_count": limits["report_count"],
            "export_count": limits["export_count"],
            "max_file_size_bytes": limits["max_file_size_bytes"],
        },
        "is_expired": False,
    }


@router.post("/convert", status_code=status.HTTP_201_CREATED)
def convert_guest_to_user(
    payload: ConvertGuestRequest,
    response: Response,
    request: Request,
    x_guest_token: Optional[str] = Header(None, alias="X-Guest-Token"),
    db: Session = Depends(get_db),
):
    """
    Convert a guest session to an authenticated user account.
    Creates user, workspace, optionally transfers guest data.
    Returns JWT tokens immediately (auto-login after signup).
    """
    if not x_guest_token:
        raise HTTPException(status_code=400, detail="X-Guest-Token header required for conversion.")

    guest = _get_guest_from_token(x_guest_token, db)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest session not found or already converted.")

    # Check email not already registered
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered. Please log in instead.")

    # Create User
    user_id = str(uuid.uuid4())
    user = User(
        user_id=user_id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        is_active=True,
        email_verified=False,
    )
    db.add(user)

    # Create Workspace
    ws_id = str(uuid.uuid4())
    ws_name = payload.workspace_name or f"{payload.email.split('@')[0]}'s Workspace"
    workspace = Workspace(
        workspace_id=ws_id,
        name=ws_name,
        plan_tier="free",
        owner_id=user_id,
    )
    db.add(workspace)

    # Flush user + workspace to DB so FK constraints are satisfied
    db.flush()

    # Add owner membership
    db.add(WorkspaceMember(
        workspace_id=ws_id,
        user_id=user_id,
        role="Owner",
    ))

    # Create default user settings
    db.add(UserSettings(
        user_id=user_id,
        default_workspace_id=ws_id,
    ))

    # Email verification token
    raw_verify = generate_random_token()
    verify_hash = hash_token(raw_verify)
    db.add(EmailVerificationToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token_hash=verify_hash,
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=24),
    ))

    # Transfer guest data if requested
    transferred = {"sessions": 0, "messages": 0, "analyses": 0, "reports": 0, "datasets": 0, "templates": 0}
    if payload.preserve_data:
        # Guest resources are namespaced by workspace_id == guest_session_id (and
        # user_id == guest_session_id).  Move every one of them to the new account.
        transferred = transfer_guest_namespace(guest.guest_session_id, user_id, ws_id, db)

    # Mark guest session as converted
    guest.converted_to_user_id = user_id
    guest.converted_at = datetime.datetime.utcnow()

    # Issue refresh token
    raw_refresh = generate_random_token()
    refresh_hash = hash_token(raw_refresh)
    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token_hash=refresh_hash,
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        revoked=False,
        workspace_id=ws_id,
    ))

    # Audit log
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        workspace_id=ws_id,
        event_type="GUEST_CONVERTED",
        description=f"Guest session {guest.guest_session_id} converted to user account.",
    ))

    db.commit()

    access_token = create_access_token(user_id, payload.email, ws_id)
    from core.auth_routes import _browser_session, set_session_cookies
    set_session_cookies(response, access_token, raw_refresh, request=request)
    cookie_session = _browser_session(request)

    # Send email verification link
    sent = send_verification_email(
        to_email=payload.email,
        full_name=payload.full_name,
        raw_token=raw_verify,
    )
    if not sent:
        logger.warning(f"Failed to send verification email to {payload.email} after guest conversion.")
    else:
        logger.info(f"Verification email sent to {payload.email} after guest conversion.")

    return {
        "success": True,
        "message": "Account created successfully! Your guest data has been transferred.",
        # Browser sessions get the tokens only as HttpOnly cookies.
        "access_token": None if cookie_session else access_token,
        "refresh_token": None if cookie_session else raw_refresh,
        "token_type": "bearer",
        "user_id": user_id,
        "email": payload.email,
        "workspace_id": ws_id,
        "transferred": transferred,
        "verification_required": True,
    }


def transfer_guest_namespace(guest_id: str, user_id: str, workspace_id: str, db: Session) -> dict:
    """Re-scope all guest-owned rows to the new user/workspace (single transaction)."""
    from sqlalchemy import text as _text

    counts = {}
    for table, key in (("sessions", "sessions"), ("messages", "messages"), ("saved_analyses", "analyses"),
                       ("reports", "reports"), ("dataset_registry", "datasets"), ("templates", "templates")):
        res = db.execute(
            _text(f"UPDATE {table} SET user_id = :uid, workspace_id = :ws WHERE workspace_id = :gid"),
            {"uid": user_id, "ws": workspace_id, "gid": guest_id},
        )
        counts[key] = res.rowcount or 0
    db.execute(_text("UPDATE jobs SET workspace_id = :ws, user_id = :uid WHERE workspace_id = :gid"),
               {"uid": user_id, "ws": workspace_id, "gid": guest_id})
    db.execute(_text("UPDATE staged_transforms SET workspace_id = :ws WHERE workspace_id = :gid"),
               {"ws": workspace_id, "gid": guest_id})
    for table in ("sessions", "messages", "saved_analyses", "reports", "dataset_registry"):
        db.execute(_text(f"UPDATE {table} SET guest_session_id = NULL WHERE workspace_id = :ws"), {"ws": workspace_id})
    return counts
