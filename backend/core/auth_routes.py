import datetime
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import User, Workspace, WorkspaceMember, RefreshToken, EmailVerificationToken, PasswordResetToken, AuditLog
from core.auth import (
    hash_password,
    verify_password,
    hash_token,
    generate_random_token,
    create_access_token,
    decode_access_token,
    REFRESH_TOKEN_EXPIRE_DAYS
)
from core.email_service import send_verification_email, send_password_reset_email

logger = logging.getLogger("datapilot.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

# ─────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    workspace_name: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    workspace_id: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    workspace_id: str

class RefreshRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

class VerifyEmailRequest(BaseModel):
    token: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# ─────────────────────────────────────────────────────────────
# Helper: Extract current user from Authorization header
# ─────────────────────────────────────────────────────────────

def get_current_user_id(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization.split(" ")[1]
    claims = decode_access_token(token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        )
    return claims["user_id"]

# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is already registered",
        )

    # Create new User
    user_id = str(uuid.uuid4())
    new_user = User(
        user_id=user_id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        is_active=True,
        email_verified=False
    )
    db.add(new_user)

    # Create new Workspace
    ws_id = str(uuid.uuid4())
    ws_name = payload.workspace_name or f"{payload.email.split('@')[0]}'s Workspace"
    new_workspace = Workspace(
        workspace_id=ws_id,
        name=ws_name,
        plan_tier="free"
    )
    db.add(new_workspace)

    # Flush user + workspace to DB so FK constraints are satisfied
    db.flush()

    # Create Workspace Member (Owner role)
    member = WorkspaceMember(
        workspace_id=ws_id,
        user_id=user_id,
        role="Owner"
    )
    db.add(member)

    # Generate email verification token
    raw_verify_token = generate_random_token()
    verify_token_hash = hash_token(raw_verify_token)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    
    verification_entry = EmailVerificationToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token_hash=verify_token_hash,
        expires_at=expires_at
    )
    db.add(verification_entry)


    db.commit()

    # Send verification email (async-safe: uses SMTP or dev console)
    sent = send_verification_email(
        to_email=payload.email,
        full_name=None,  # SignupRequest has no full_name field
        raw_token=raw_verify_token,
    )
    if not sent:
        logger.warning(f"Failed to send verification email to {payload.email} — check SMTP config.")
    else:
        logger.info(f"Verification email sent to {payload.email}")

    return {
        "success": True,
        "message": "User registered successfully. Verification email sent.",
        "user_id": user_id,
        "email": payload.email,
        "workspace_id": ws_id,
        "verification_required": True
    }

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    # 1. Query user
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        # Audit failed login
        failed_log = AuditLog(
            id=str(uuid.uuid4()),
            user_id=user.user_id if user else None,
            event_type="LOGIN_FAILED",
            description=f"Failed login attempt for email: {payload.email}"
        )
        db.add(failed_log)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # 2. Check workspace membership
    membership = None
    if payload.workspace_id:
        membership = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.user_id,
            WorkspaceMember.workspace_id == payload.workspace_id
        ).first()
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is not a member of the requested workspace",
            )
    else:
        # Pick the user's first workspace
        membership = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.user_id
        ).first()
        if not membership:
            # Fallback (create workspace if none exists)
            ws_id = str(uuid.uuid4())
            new_workspace = Workspace(
                workspace_id=ws_id,
                name=f"{user.email.split('@')[0]}'s Workspace",
                plan_tier="free"
            )
            db.add(new_workspace)
            membership = WorkspaceMember(
                workspace_id=ws_id,
                user_id=user.user_id,
                role="Owner"
            )
            db.add(membership)
            db.commit()

    workspace_id = membership.workspace_id

    # 3. Generate tokens
    access_token = create_access_token(user.user_id, user.email, workspace_id)
    raw_refresh_token = generate_random_token()
    refresh_token_hash = hash_token(raw_refresh_token)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    # Save refresh token
    new_refresh = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        token_hash=refresh_token_hash,
        expires_at=expires_at,
        revoked=False
    )
    db.add(new_refresh)

    # Audit login success
    success_log = AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        workspace_id=workspace_id,
        event_type="LOGIN_SUCCESS",
        description=f"User successfully logged into workspace: {workspace_id}"
    )
    db.add(success_log)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh_token,
        user_id=user.user_id,
        email=user.email,
        workspace_id=workspace_id
    )

@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    hashed = hash_token(payload.refresh_token)
    token_entry = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hashed,
        RefreshToken.revoked == False
    ).first()

    if not token_entry or token_entry.expires_at < datetime.datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = db.query(User).filter(User.user_id == token_entry.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive or not found",
        )

    # Rotate refresh token: revoke old one
    token_entry.revoked = True

    # Find their first/current workspace
    membership = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.user_id).first()
    workspace_id = membership.workspace_id if membership else "default_workspace"

    # Generate new tokens
    new_access_token = create_access_token(user.user_id, user.email, workspace_id)
    new_raw_refresh_token = generate_random_token()
    new_refresh_hash = hash_token(new_raw_refresh_token)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    new_refresh = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        token_hash=new_refresh_hash,
        expires_at=expires_at,
        revoked=False
    )
    db.add(new_refresh)
    db.commit()

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_raw_refresh_token,
        user_id=user.user_id,
        email=user.email,
        workspace_id=workspace_id
    )

@router.post("/logout")
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    hashed = hash_token(payload.refresh_token)
    token_entry = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed).first()
    
    if token_entry:
        token_entry.revoked = True
        
        # Log audit event
        logout_log = AuditLog(
            id=str(uuid.uuid4()),
            user_id=token_entry.user_id,
            event_type="LOGOUT",
            description="User logged out"
        )
        db.add(logout_log)
        db.commit()

    return {"success": True, "message": "Successfully logged out"}

@router.post("/logout-all")
def logout_all(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    # Revoke/Delete all refresh tokens for this user
    tokens = db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked == False
    ).all()

    for token in tokens:
        token.revoked = True

    # Log audit event
    logout_log = AuditLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type="LOGOUT",
        description="User logged out from all devices"
    )
    db.add(logout_log)
    db.commit()

    return {"success": True, "message": "Successfully logged out from all devices"}

@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    hashed = hash_token(payload.token)
    token_entry = db.query(EmailVerificationToken).filter(
        EmailVerificationToken.token_hash == hashed
    ).first()

    if not token_entry or token_entry.expires_at < datetime.datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired email verification token",
        )

    # Set email_verified = True
    user = db.query(User).filter(User.user_id == token_entry.user_id).first()
    if user:
        user.email_verified = True
        # Clean token
        db.delete(token_entry)
        db.commit()
        return {"success": True, "message": "Email address successfully verified"}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="User not found",
    )

@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user:
        # Generate token
        raw_reset_token = generate_random_token()
        hashed = hash_token(raw_reset_token)
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)

        # Store token
        reset_entry = PasswordResetToken(
            id=str(uuid.uuid4()),
            user_id=user.user_id,
            token_hash=hashed,
            expires_at=expires_at
        )
        db.add(reset_entry)

        # Audit log request
        reset_request_log = AuditLog(
            id=str(uuid.uuid4()),
            user_id=user.user_id,
            event_type="PASSWORD_RESET_REQUEST",
            description=f"Password reset token requested for: {payload.email}"
        )
        db.add(reset_request_log)
        db.commit()

        # Send password reset email
        user_name = user.full_name if hasattr(user, 'full_name') else None
        sent = send_password_reset_email(
            to_email=payload.email,
            full_name=user_name,
            raw_token=raw_reset_token,
        )
        if not sent:
            logger.warning(f"Failed to send password reset email to {payload.email} — check SMTP config.")

    # Return success regardless to prevent account enumeration
    return {"success": True, "message": "If the email is registered, a password reset link has been generated."}

@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    hashed = hash_token(payload.token)
    token_entry = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == hashed
    ).first()

    if not token_entry or token_entry.expires_at < datetime.datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token",
        )

    user = db.query(User).filter(User.user_id == token_entry.user_id).first()
    if user:
        # Update password
        user.password_hash = hash_password(payload.new_password)
        # Delete token
        db.delete(token_entry)

        # Audit log completion
        reset_complete_log = AuditLog(
            id=str(uuid.uuid4()),
            user_id=user.user_id,
            event_type="PASSWORD_RESET_COMPLETE",
            description="User password successfully updated"
        )
        db.add(reset_complete_log)
        db.commit()

        return {"success": True, "message": "Password successfully updated"}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="User not found",
    )
