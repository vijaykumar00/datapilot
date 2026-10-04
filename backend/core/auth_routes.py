import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import uuid
from typing import Optional
from urllib.parse import urlencode, urlparse
from fastapi import APIRouter, Cookie, Depends, HTTPException, Header, Request, Response, status
import httpx
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import (
    User,
    Workspace,
    WorkspaceMember,
    RefreshToken,
    EmailVerificationToken,
    PasswordResetToken,
    PhoneOtpChallenge,
    AuditLog,
    OAuthIdentity,
)
from core.auth import (
    hash_password,
    verify_password,
    hash_token,
    generate_random_token,
    create_access_token,
    decode_access_token,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRE_DAYS,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from core.email_service import send_verification_email, send_password_reset_email

logger = logging.getLogger("datapilot.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

# ─────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128,
                          description="Password must be at least 8 characters.")
    full_name: str | None = None
    workspace_name: str | None = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    workspace_id: Optional[str] = None

class TokenResponse(BaseModel):
    # Browser sessions (X-Session-Mode: cookie, or a cookie-based refresh) receive the
    # tokens ONLY as HttpOnly cookies; these fields are then null.  API clients that
    # send credentials in the body keep receiving them here.
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    user_id: str
    email: str
    workspace_id: str
    full_name: str | None = None
    phone_number: str | None = None

class RefreshRequest(BaseModel):
    refresh_token: str | None = None
    workspace_id: str | None = None

class LogoutRequest(BaseModel):
    refresh_token: str | None = None

class VerifyEmailRequest(BaseModel):
    token: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128,
                              description="New password must be at least 8 characters.")

class OAuthStartRequest(BaseModel):
    redirect_uri: str = Field(..., max_length=500)
    next_path: str | None = Field("/app/analyze", max_length=200)

class OAuthCallbackRequest(BaseModel):
    code: str = Field(..., min_length=8, max_length=4096)
    state: str = Field(..., min_length=16, max_length=4096)
    redirect_uri: str = Field(..., max_length=500)

class PhoneOtpRequest(BaseModel):
    phone_number: str = Field(..., min_length=7, max_length=32)

class PhoneOtpVerifyRequest(BaseModel):
    phone_number: str = Field(..., min_length=7, max_length=32)
    code: str = Field(..., min_length=4, max_length=12)
    workspace_name: str | None = Field(None, max_length=255)


OAUTH_PROVIDERS = {
    "google": {
        "display_name": "Google",
        "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
        "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "microsoft": {
        "display_name": "Microsoft",
        "client_id_env": "MICROSOFT_OAUTH_CLIENT_ID",
        "client_secret_env": "MICROSOFT_OAUTH_CLIENT_SECRET",
        "authorization_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile",
    },
}

PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

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


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}


def _token_response_for_user(
    user: User,
    workspace_id: str,
    db: Session,
    event_type: str,
    description: str,
) -> TokenResponse:
    access_token = create_access_token(user.user_id, user.email, workspace_id)
    raw_refresh_token = generate_random_token()
    refresh_token_hash = hash_token(raw_refresh_token)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    db.add(RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        token_hash=refresh_token_hash,
        expires_at=expires_at,
        revoked=False,
        workspace_id=workspace_id,
    ))
    db.add(AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.user_id,
        workspace_id=workspace_id,
        event_type=event_type,
        description=description,
    ))
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh_token,
        user_id=user.user_id,
        email=user.email,
        workspace_id=workspace_id,
        full_name=user.full_name,
        phone_number=getattr(user, "phone_number", None),
    )


REFRESH_COOKIE = "dp_refresh"
ACCESS_COOKIE = "dp_access"
CSRF_COOKIE = "dp_csrf"
CSRF_HEADER = "x-csrf-token"
SESSION_MODE_HEADER = "x-session-mode"


REFRESH_REUSE_GRACE_SECONDS = int(os.getenv("REFRESH_REUSE_GRACE_SECONDS", "20"))


def _cookie_secure() -> bool:
    return _is_production() or os.getenv("COOKIE_SECURE", "").lower() in {"1", "true", "yes"}


def set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    """Refresh tokens travel in an HttpOnly, SameSite=Strict cookie (not readable by JS)."""
    response.set_cookie(
        REFRESH_COOKIE,
        raw_refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


def set_session_cookies(response: Response, access_token: str, raw_refresh_token: str,
                        request: Request | None = None, rotate_csrf: bool = True) -> None:
    """Browser session = HttpOnly access + refresh cookies plus a readable CSRF cookie.

    The CSRF cookie implements double-submit protection: unsafe requests that
    authenticate with the cookie must echo its value in ``X-CSRF-Token`` (a
    cross-site page can neither read the cookie nor set that header).
    """
    set_refresh_cookie(response, raw_refresh_token)
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    existing = request.cookies.get(CSRF_COOKIE) if request is not None else None
    csrf = existing if (existing and not rotate_csrf and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", existing)) \
        else secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=False,  # must be readable by the SPA to echo it in X-CSRF-Token
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


def clear_refresh_cookie(response: Response) -> None:
    """Clear every session cookie (refresh, access and CSRF)."""
    for name in (REFRESH_COOKIE, ACCESS_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")


def csrf_valid(request: Request) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE) or ""
    header = request.headers.get(CSRF_HEADER) or ""
    return bool(cookie) and hmac.compare_digest(cookie, header)


def _browser_session(request: Request | None) -> bool:
    return request is not None and (request.headers.get(SESSION_MODE_HEADER) or "").lower() == "cookie"


def _issue(response: Response, token: "TokenResponse", request: Request | None = None,
           cookie_only: bool = False, rotate_csrf: bool = True) -> "TokenResponse":
    set_session_cookies(response, token.access_token, token.refresh_token, request=request, rotate_csrf=rotate_csrf)
    if cookie_only or _browser_session(request):
        # Keep tokens out of JavaScript entirely: an XSS payload cannot exfiltrate them.
        token.access_token = None
        token.refresh_token = None
    return token


def revoke_all_refresh_tokens(user_id: str, db: Session) -> int:
    tokens = db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.revoked == False).all()  # noqa: E712
    for t in tokens:
        t.revoked = True
    return len(tokens)


def _first_or_create_workspace(user: User, db: Session, workspace_name: str | None = None) -> WorkspaceMember:
    membership = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.user_id).first()
    if membership:
        return membership

    ws_id = str(uuid.uuid4())
    new_workspace = Workspace(
        workspace_id=ws_id,
        name=workspace_name or f"{user.email.split('@')[0]}'s Workspace",
        plan_tier="free",
        owner_id=user.user_id,
    )
    membership = WorkspaceMember(
        workspace_id=ws_id,
        user_id=user.user_id,
        role="Owner",
    )
    db.add(new_workspace)
    db.add(membership)
    db.flush()
    return membership


def _allowed_redirect_origins() -> set[str]:
    raw = os.getenv("AUTH_ALLOWED_REDIRECT_ORIGINS") or os.getenv("ALLOWED_ORIGINS", "")
    origins = {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}
    if not _is_production():
        origins.update({
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
        })
    return origins


def _validate_redirect_uri(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid OAuth redirect URI.")
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if origin not in _allowed_redirect_origins():
        raise HTTPException(status_code=400, detail="OAuth redirect origin is not allowed.")
    if _is_production() and parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="OAuth redirect URI must use HTTPS in production.")
    return redirect_uri


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _encode_oauth_state(provider: str, redirect_uri: str, next_path: str | None) -> str:
    payload = {
        "provider": provider,
        "redirect_uri": redirect_uri,
        "next_path": next_path or "/app/analyze",
        "nonce": secrets.token_urlsafe(18),
        "iat": int(datetime.datetime.utcnow().timestamp()),
    }
    encoded_payload = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(JWT_SECRET.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_b64url(signature)}"


def _decode_oauth_state(state: str, provider: str, redirect_uri: str) -> dict:
    try:
        encoded_payload, encoded_sig = state.split(".", 1)
        expected = hmac.new(JWT_SECRET.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64url(encoded_sig), expected):
            raise ValueError("bad signature")
        payload = json.loads(_unb64url(encoded_payload).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    issued_at = int(payload.get("iat", 0))
    max_age = int(os.getenv("OAUTH_STATE_TTL_SECONDS", "600"))
    now = int(datetime.datetime.utcnow().timestamp())
    if now - issued_at > max_age:
        raise HTTPException(status_code=400, detail="OAuth state expired.")
    if payload.get("provider") != provider or payload.get("redirect_uri") != redirect_uri:
        raise HTTPException(status_code=400, detail="OAuth state does not match this request.")
    return payload


def _oauth_config(provider: str) -> dict:
    cfg = OAUTH_PROVIDERS.get(provider)
    if not cfg:
        raise HTTPException(status_code=404, detail="OAuth provider is not supported.")
    tenant = os.getenv("MICROSOFT_OAUTH_TENANT", "common")
    return {
        **cfg,
        "authorization_url": cfg["authorization_url"].format(tenant=tenant),
        "token_url": cfg["token_url"].format(tenant=tenant),
        "client_id": os.getenv(cfg["client_id_env"], ""),
        "client_secret": os.getenv(cfg["client_secret_env"], ""),
    }


def _require_oauth_config(provider: str) -> dict:
    cfg = _oauth_config(provider)
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(status_code=503, detail=f"{cfg['display_name']} sign-in is not configured.")
    return cfg


def _social_user_from_profile(provider: str, profile: dict, db: Session) -> User:
    """Resolve the local user for a verified OAuth identity.

    Accounts are linked by the provider's stable subject id.  An existing
    password account is only linked automatically when the provider *asserts
    the email is verified* (Google ``email_verified=true``).  Microsoft's
    ``preferred_username``/``email`` claims are not verified for every tenant,
    so they never auto-link to an existing account (prevents account takeover).
    """
    subject = str(profile.get("sub") or profile.get("oid") or profile.get("id") or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="OAuth provider did not return a subject identifier.")
    email = (profile.get("email") or (profile.get("preferred_username") if provider == "microsoft" else "") or "").strip().lower()
    email_verified = provider == "google" and profile.get("email_verified") is True

    identity = db.query(OAuthIdentity).filter(OAuthIdentity.provider == provider, OAuthIdentity.subject == subject).first()
    if identity:
        user = db.query(User).filter(User.user_id == identity.user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or not found.")
        return user

    if not email:
        raise HTTPException(status_code=400, detail="OAuth provider did not return an email address.")
    if provider == "google" and not email_verified:
        raise HTTPException(status_code=403, detail="Google email address is not verified.")

    full_name = profile.get("name") or profile.get("given_name")
    avatar_url = profile.get("picture")
    user = db.query(User).filter(User.email == email).first()
    if user:
        if not email_verified:
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists. Sign in with your password instead.",
            )
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or not found.")
        user.email_verified = True
        if full_name and not user.full_name:
            user.full_name = full_name
        if avatar_url and not user.avatar_url:
            user.avatar_url = avatar_url
    else:
        user = User(
            user_id=str(uuid.uuid4()),
            email=email,
            password_hash=hash_password(generate_random_token()),
            full_name=full_name,
            avatar_url=avatar_url,
            is_active=True,
            email_verified=email_verified,
        )
        db.add(user)
        db.flush()
    db.add(OAuthIdentity(id=str(uuid.uuid4()), provider=provider, subject=subject, user_id=user.user_id, email=email))
    db.flush()
    return user


def _normalize_phone_number(raw_phone: str) -> str:
    phone = re.sub(r"[\s().-]", "", raw_phone.strip())
    if phone.startswith("00"):
        phone = f"+{phone[2:]}"
    if not PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="Phone number must be in E.164 format, for example +15551234567.")
    return phone


def _phone_otp_enabled() -> bool:
    configured = os.getenv("PHONE_OTP_ENABLED")
    if configured is not None:
        return _truthy(configured)
    return not _is_production()


def _phone_otp_dev_mode() -> bool:
    configured = os.getenv("PHONE_OTP_DEV_MODE")
    if configured is not None:
        return _truthy(configured)
    return not _is_production()


def _send_phone_otp(phone_number: str, code: str) -> str:
    webhook_url = os.getenv("SMS_OTP_WEBHOOK_URL", "").strip()
    if webhook_url:
        headers = {"Content-Type": "application/json"}
        webhook_token = os.getenv("SMS_OTP_WEBHOOK_TOKEN", "").strip()
        if webhook_token:
            headers["Authorization"] = f"Bearer {webhook_token}"
        try:
            response = httpx.post(
                webhook_url,
                json={
                    "to": phone_number,
                    "message": f"Your DataPilot sign-in code is {code}. It expires in {OTP_TTL_MINUTES} minutes.",
                    "code": code,
                    "ttl_minutes": OTP_TTL_MINUTES,
                },
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            return "sent"
        except httpx.HTTPError as exc:
            logger.warning("Phone OTP delivery failed: %s", exc)
            raise HTTPException(status_code=502, detail="Could not send OTP. Please try again.")

    if _phone_otp_dev_mode():
        return "development"

    raise HTTPException(status_code=503, detail="Phone OTP sign-in is not configured.")


def _phone_email(phone_number: str) -> str:
    digest = hashlib.sha256(phone_number.encode("utf-8")).hexdigest()[:24]
    return f"phone-{digest}@phone.datapilot.local"


def _phone_user(phone_number: str, db: Session) -> User:
    user = db.query(User).filter(User.phone_number == phone_number).first()
    if user:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or not found.")
        return user

    email = _phone_email(phone_number)
    user = db.query(User).filter(User.email == email).first()
    if user:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or not found.")
        user.phone_number = phone_number
        db.flush()
        return user

    user = User(
        user_id=str(uuid.uuid4()),
        email=email,
        phone_number=phone_number,
        password_hash=hash_password(generate_random_token()),
        full_name=phone_number,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return user

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
        full_name=payload.full_name,
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
        plan_tier="free",
        owner_id=user_id
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
def login(payload: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    # 1. Query user
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
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

    return _issue(response, request=request, token=_token_response_for_user(
        user=user,
        workspace_id=membership.workspace_id,
        db=db,
        event_type="LOGIN_SUCCESS",
        description=f"User successfully logged into workspace: {membership.workspace_id}",
    ))


@router.get("/oauth/providers")
def oauth_providers():
    providers = []
    for provider, cfg in OAUTH_PROVIDERS.items():
        resolved = _oauth_config(provider)
        providers.append({
            "provider": provider,
            "display_name": cfg["display_name"],
            "enabled": bool(resolved["client_id"] and resolved["client_secret"]),
        })
    providers.append({
        "provider": "phone_otp",
        "display_name": "Phone OTP",
        "enabled": _phone_otp_enabled(),
    })
    return {"providers": providers}


@router.post("/oauth/{provider}/start")
def oauth_start(provider: str, payload: OAuthStartRequest):
    provider = provider.lower()
    cfg = _require_oauth_config(provider)
    redirect_uri = _validate_redirect_uri(payload.redirect_uri)
    state = _encode_oauth_state(provider, redirect_uri, payload.next_path)
    query = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
        "prompt": "select_account",
    }
    return {
        "authorization_url": f"{cfg['authorization_url']}?{urlencode(query)}",
        "provider": provider,
    }


@router.post("/oauth/{provider}/callback", response_model=TokenResponse)
def oauth_callback(provider: str, payload: OAuthCallbackRequest, response: Response, request: Request,
                   db: Session = Depends(get_db)):
    provider = provider.lower()
    cfg = _require_oauth_config(provider)
    redirect_uri = _validate_redirect_uri(payload.redirect_uri)
    _decode_oauth_state(payload.state, provider, redirect_uri)

    try:
        token_response = httpx.post(
            cfg["token_url"],
            data={
                "grant_type": "authorization_code",
                "code": payload.code,
                "redirect_uri": redirect_uri,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
            },
            timeout=10,
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="OAuth provider did not return an access token.")

        userinfo_response = httpx.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        userinfo_response.raise_for_status()
        profile = userinfo_response.json()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        logger.warning("OAuth provider rejected callback for %s: %s", provider, exc)
        raise HTTPException(status_code=400, detail="OAuth sign-in could not be completed.")
    except httpx.HTTPError as exc:
        logger.warning("OAuth provider request failed for %s: %s", provider, exc)
        raise HTTPException(status_code=502, detail="OAuth provider is temporarily unavailable.")

    user = _social_user_from_profile(provider, profile, db)
    membership = _first_or_create_workspace(user, db)
    return _issue(response, request=request, token=_token_response_for_user(
        user=user,
        workspace_id=membership.workspace_id,
        db=db,
        event_type="OAUTH_LOGIN",
        description=f"User signed in with {cfg['display_name']}.",
    ))


@router.post("/otp/request")
def request_phone_otp(payload: PhoneOtpRequest, db: Session = Depends(get_db)):
    if not _phone_otp_enabled():
        raise HTTPException(status_code=503, detail="Phone OTP sign-in is not enabled.")

    phone_number = _normalize_phone_number(payload.phone_number)
    code = f"{secrets.randbelow(1_000_000):06d}"
    delivery_mode = _send_phone_otp(phone_number, code)
    now = datetime.datetime.utcnow()

    db.add(PhoneOtpChallenge(
        id=str(uuid.uuid4()),
        phone_number=phone_number,
        code_hash=hash_token(f"{phone_number}:{code}"),
        expires_at=now + datetime.timedelta(minutes=OTP_TTL_MINUTES),
        consumed=False,
        attempt_count=0,
        created_at=now,
    ))
    db.commit()

    response = {
        "success": True,
        "message": "If that phone number can receive OTPs, a sign-in code has been sent.",
        "expires_in_seconds": OTP_TTL_MINUTES * 60,
    }
    if delivery_mode == "development":
        response["dev_otp"] = code
    return response


@router.post("/otp/verify", response_model=TokenResponse)
def verify_phone_otp(payload: PhoneOtpVerifyRequest, response: Response, request: Request,
                     db: Session = Depends(get_db)):
    if not _phone_otp_enabled():
        raise HTTPException(status_code=503, detail="Phone OTP sign-in is not enabled.")

    phone_number = _normalize_phone_number(payload.phone_number)
    now = datetime.datetime.utcnow()
    challenge = db.query(PhoneOtpChallenge).filter(
        PhoneOtpChallenge.phone_number == phone_number,
        PhoneOtpChallenge.consumed == False,
        PhoneOtpChallenge.expires_at >= now,
    ).order_by(PhoneOtpChallenge.created_at.desc()).first()

    if not challenge:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP code.")
    if challenge.attempt_count >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many OTP attempts. Request a new code.")

    challenge.attempt_count += 1
    submitted_hash = hash_token(f"{phone_number}:{payload.code.strip()}")
    if not secrets.compare_digest(challenge.code_hash, submitted_hash):
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired OTP code.")

    challenge.consumed = True
    user = _phone_user(phone_number, db)
    membership = _first_or_create_workspace(user, db, payload.workspace_name or "Phone Workspace")
    return _issue(response, request=request, token=_token_response_for_user(
        user=user,
        workspace_id=membership.workspace_id,
        db=db,
        event_type="PHONE_OTP_LOGIN",
        description="User signed in with phone OTP.",
    ))

@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    request: Request,
    payload: RefreshRequest | None = None,
    dp_refresh: str | None = Cookie(None),
    db: Session = Depends(get_db),
):
    body_token = payload.refresh_token if payload else None
    raw = body_token or dp_refresh
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    from_cookie = not body_token
    if from_cookie and not csrf_valid(request):
        # Cookie-authenticated request: require the double-submit CSRF token.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"message": "CSRF token missing or invalid.", "code": "CSRF_FAILED"})
    hashed = hash_token(raw)
    token_entry = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed).first()

    if token_entry and token_entry.revoked and token_entry.rotated_at is not None and (
        datetime.datetime.utcnow() - token_entry.rotated_at
    ).total_seconds() < REFRESH_REUSE_GRACE_SECONDS:
        # Benign race: two tabs/requests refreshed with the same cookie at once.  The
        # winner already set the new cookie, so do NOT clear it; the client retries.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"message": "Refresh token was just rotated; retry.", "code": "REFRESH_RACE"})

    if token_entry and token_entry.revoked:
        # A rotated (already used) token was replayed: assume theft and revoke the whole family.
        revoke_all_refresh_tokens(token_entry.user_id, db)
        db.add(AuditLog(id=str(uuid.uuid4()), user_id=token_entry.user_id, event_type="REFRESH_TOKEN_REUSE",
                        description="Revoked all sessions after refresh-token reuse was detected."))
        db.commit()
        clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    if not token_entry or token_entry.expires_at < datetime.datetime.utcnow():
        clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.user_id == token_entry.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or not found")

    token_entry.revoked = True  # rotate
    token_entry.rotated_at = datetime.datetime.utcnow()

    # Keep the workspace the user was working in (explicit request > token's workspace > first membership).
    membership = None
    for candidate in ((payload.workspace_id if payload else None), token_entry.workspace_id):
        if candidate:
            membership = db.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user.user_id, WorkspaceMember.workspace_id == candidate
            ).first()
            if membership:
                break
    if membership is None:
        membership = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.user_id).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return _issue(response, request=request, cookie_only=from_cookie, rotate_csrf=False, token=_token_response_for_user(
        user=user,
        workspace_id=membership.workspace_id,
        db=db,
        event_type="TOKEN_REFRESH",
        description="Refresh token rotated.",
    ))

@router.post("/logout")
def logout(response: Response, payload: LogoutRequest | None = None, dp_refresh: str | None = Cookie(None),
           db: Session = Depends(get_db)):
    clear_refresh_cookie(response)
    raw = (payload.refresh_token if payload else None) or dp_refresh
    token_entry = db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(raw)).first() if raw else None

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
def logout_all(response: Response, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    clear_refresh_cookie(response)
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
        # Update password, invalidate every reset token and every existing session.
        user.password_hash = hash_password(payload.new_password)
        db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.user_id).delete(synchronize_session=False)
        revoke_all_refresh_tokens(user.user_id, db)

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
