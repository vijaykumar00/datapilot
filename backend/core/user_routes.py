"""
user_routes.py — User profile, settings, API key management, and usage endpoints.

API keys are AES-encrypted at the application layer before storage.
Plain text keys are NEVER stored, logged, or returned in API responses.
"""
import logging
import uuid
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import User, UserSettings, UserAPIKey, Workspace, WorkspaceMember, AuditLog
from core.rbac import get_current_user
from core.encryption import encrypt_value, decrypt_value, mask_key
from core.usage import get_usage_summary
from core.auth import hash_password, verify_password

logger = logging.getLogger("datapilot.user")
router = APIRouter(prefix="/user", tags=["user"])

VALID_PROVIDERS = {"openai", "gemini", "anthropic", "ollama"}


# ─────────────────────────────────────────────────────────────
# Request Schemas
# ─────────────────────────────────────────────────────────────

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UpdateSettingsRequest(BaseModel):
    default_workspace_id: Optional[str] = None
    theme: Optional[str] = None
    notification_email: Optional[bool] = None
    timezone: Optional[str] = None
    language: Optional[str] = None


class AddAPIKeyRequest(BaseModel):
    provider: str
    api_key: str
    label: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────

@router.get("/profile")
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get the current user's profile."""
    # Get workspace memberships
    memberships = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.user_id).all()
    workspace_list = []
    for m in memberships:
        ws = db.query(Workspace).filter(Workspace.workspace_id == m.workspace_id).first()
        if ws:
            workspace_list.append({
                "workspace_id": ws.workspace_id,
                "name": ws.name,
                "role": m.role,
                "plan_tier": ws.plan_tier,
            })

    return {
        "user_id": user.user_id,
        "email": user.email,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "email_verified": user.email_verified,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "workspaces": workspace_list,
    }


@router.put("/profile")
def update_profile(
    payload: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update user profile (name, avatar)."""
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.avatar_url is not None:
        user.avatar_url = payload.avatar_url
    user.updated_at = datetime.datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Profile updated."}


@router.put("/password")
def change_password(
    payload: UpdatePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change user password. Requires current password verification."""
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = datetime.datetime.utcnow()
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        event_type="PASSWORD_CHANGED",
        description="User changed their password.",
    ))
    db.commit()
    return {"success": True, "message": "Password updated successfully."}


# ─────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get user application settings."""
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.user_id).first()
    if not settings:
        # Create defaults
        settings = UserSettings(user_id=user.user_id)
        db.add(settings)
        db.commit()
    return {
        "user_id": user.user_id,
        "default_workspace_id": settings.default_workspace_id,
        "theme": settings.theme,
        "notification_email": settings.notification_email,
        "timezone": settings.timezone,
        "language": settings.language,
    }


@router.put("/settings")
def update_settings(
    payload: UpdateSettingsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update user application settings."""
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.user_id).first()
    if not settings:
        settings = UserSettings(user_id=user.user_id)
        db.add(settings)

    if payload.default_workspace_id is not None:
        # Verify user is a member of that workspace
        membership = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.user_id,
            WorkspaceMember.workspace_id == payload.default_workspace_id,
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        settings.default_workspace_id = payload.default_workspace_id

    if payload.theme is not None:
        if payload.theme not in ("dark", "light", "system"):
            raise HTTPException(status_code=400, detail="Theme must be: dark, light, or system.")
        settings.theme = payload.theme
    if payload.notification_email is not None:
        settings.notification_email = payload.notification_email
    if payload.timezone is not None:
        settings.timezone = payload.timezone
    if payload.language is not None:
        settings.language = payload.language

    settings.updated_at = datetime.datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Settings updated."}


# ─────────────────────────────────────────────────────────────
# API Keys (AES-encrypted storage)
# ─────────────────────────────────────────────────────────────

@router.get("/api-keys")
def list_api_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List user's stored API keys (masked — never returns plaintext)."""
    keys = db.query(UserAPIKey).filter(UserAPIKey.user_id == user.user_id).all()
    result = []
    for k in keys:
        # Never return the decrypted key — show masked version only
        try:
            decrypted = decrypt_value(k.encrypted_key)
            masked = mask_key(decrypted)
        except Exception:
            masked = "****"
        result.append({
            "id": k.id,
            "provider": k.provider,
            "label": k.label,
            "masked_key": masked,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "updated_at": k.updated_at.isoformat() if k.updated_at else None,
        })
    return {"api_keys": result, "total": len(result)}


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
def add_api_key(
    payload: AddAPIKeyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store a new API key (AES-encrypted). Plain text key is never stored."""
    if payload.provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {', '.join(VALID_PROVIDERS)}"
        )
    if not payload.api_key or len(payload.api_key) < 8:
        raise HTTPException(status_code=400, detail="API key is too short.")

    # Encrypt the key
    encrypted = encrypt_value(payload.api_key)

    # Check if key for this provider already exists — update it
    existing = db.query(UserAPIKey).filter(
        UserAPIKey.user_id == user.user_id,
        UserAPIKey.provider == payload.provider,
    ).first()

    if existing:
        existing.encrypted_key = encrypted
        existing.label = payload.label or existing.label
        existing.updated_at = datetime.datetime.utcnow()
        key_id = existing.id
    else:
        new_key = UserAPIKey(
            id=str(uuid.uuid4()),
            user_id=user.user_id,
            provider=payload.provider,
            label=payload.label or f"{payload.provider.capitalize()} API Key",
            encrypted_key=encrypted,
        )
        db.add(new_key)
        key_id = new_key.id

    db.add(AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        event_type="API_KEY_UPDATED",
        description=f"API key for provider '{payload.provider}' was saved.",
    ))
    db.commit()

    return {
        "success": True,
        "message": f"API key for {payload.provider} saved securely.",
        "id": key_id,
        "provider": payload.provider,
    }


@router.delete("/api-keys/{key_id}")
def delete_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a stored API key."""
    key = db.query(UserAPIKey).filter(
        UserAPIKey.id == key_id,
        UserAPIKey.user_id == user.user_id,  # Enforce ownership
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found.")

    provider = key.provider
    db.delete(key)
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        event_type="API_KEY_DELETED",
        description=f"API key for provider '{provider}' deleted.",
    ))
    db.commit()
    return {"success": True, "message": "API key deleted."}


# ─────────────────────────────────────────────────────────────
# Usage
# ─────────────────────────────────────────────────────────────

@router.get("/usage")
def get_usage(
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get usage statistics for the current workspace."""
    workspace_id = x_workspace_id
    if not workspace_id:
        # Default to user's first workspace
        membership = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.user_id
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="No workspace found.")
        workspace_id = membership.workspace_id

    # Verify membership (returns 404 for non-members)
    from core.rbac import get_workspace_member
    get_workspace_member(user, workspace_id, db)

    return get_usage_summary(workspace_id, db)
