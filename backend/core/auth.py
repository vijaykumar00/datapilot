import datetime
import hashlib
import os
import secrets
from typing import Dict, Optional
import jwt

JWT_SECRET = os.getenv("JWT_SECRET", "datapilot-secret-jwt-key-2026-sprint-2")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7

def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256."""
    salt = os.urandom(16)
    rounds = 100000
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${key.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    """Verify password matches PBKDF2-HMAC-SHA256 hash."""
    try:
        parts = hashed.split('$')
        if len(parts) != 4 or parts[0] != 'pbkdf2_sha256':
            return False
        rounds = int(parts[1])
        salt = bytes.fromhex(parts[2])
        key_hex = parts[3]
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, rounds)
        return secrets.compare_digest(new_key.hex(), key_hex)
    except Exception:
        return False

def hash_token(token: str) -> str:
    """Hash a raw token with SHA-256 for database storage."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def generate_random_token() -> str:
    """Generate a high-entropy cryptographically secure random token."""
    return secrets.token_hex(32)

def create_access_token(user_id: str, email: str, current_workspace_id: str) -> str:
    """Create a minimal JWT access token."""
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "user_id": user_id,
        "email": email,
        "current_workspace_id": current_workspace_id,
        "token_type": "access",
        "exp": expire
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> Optional[Dict]:
    """Decode and validate a JWT access token, returning its claims if valid."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("token_type") != "access":
            return None
        return payload
    except jwt.PyJWTError:
        return None
