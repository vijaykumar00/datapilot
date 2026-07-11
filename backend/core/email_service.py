"""
email_service.py — Email sending service for DataPilot.

Supports:
  - SMTP (production): configured via SMTP_* env vars
  - Console/dev mode (fallback): prints emails to stdout when SMTP_HOST is not configured

Usage:
    from core.email_service import send_verification_email, send_password_reset_email
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("datapilot.email")

# ─────────────────────────────────────────────────────────────
# Configuration from environment
# ─────────────────────────────────────────────────────────────

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "noreply@datapilot.ai")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "DataPilot")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

APP_URL = os.getenv("APP_URL", "http://localhost:5173")
EMAIL_DEV_MODE = not bool(SMTP_HOST)  # True when no SMTP server is configured


# ─────────────────────────────────────────────────────────────
# Core send function
# ─────────────────────────────────────────────────────────────

def _send_email(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """
    Send an email. Uses SMTP if configured, otherwise logs to console (dev mode).
    Returns True on success, False on failure.
    """
    if EMAIL_DEV_MODE:
        # Development mode: print the email to the console (UTF-8 safe for Windows)
        separator = "=" * 70
        divider = "-" * 70
        dev_output = (
            f"\n{separator}\n"
            f"[DEV EMAIL] To: {to_email}\n"
            f"Subject: {subject}\n"
            f"{divider}\n"
            f"{text_body}\n"
            f"{separator}"
        )
        logger.info(dev_output)
        try:
            print(dev_output)
        except UnicodeEncodeError:
            # Fallback for Windows consoles that don't support UTF-8
            safe_output = dev_output.encode("ascii", errors="replace").decode("ascii")
            print(safe_output)
        return True

    # Production SMTP send
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = to_email

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        if SMTP_USE_TLS:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                if SMTP_USERNAME and SMTP_PASSWORD:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())
        else:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                if SMTP_USERNAME and SMTP_PASSWORD:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())

        logger.info(f"Email sent to {to_email}: {subject}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(f"SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD.")
        return False
    except smtplib.SMTPConnectError:
        logger.error(f"Could not connect to SMTP server {SMTP_HOST}:{SMTP_PORT}.")
        return False
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# Email Templates
# ─────────────────────────────────────────────────────────────

def send_verification_email(to_email: str, full_name: Optional[str], raw_token: str) -> bool:
    """Send an email address verification link."""
    name = full_name or to_email.split("@")[0]
    verify_url = f"{APP_URL}/verify-email?token={raw_token}"

    subject = "Verify your DataPilot email address"

    text_body = f"""Hi {name},

Welcome to DataPilot! Please verify your email address to activate your account.

Click the link below (expires in 24 hours):
{verify_url}

If you did not create an account, you can safely ignore this email.

— The DataPilot Team
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f1117; color:#e2e8f0; padding:40px 20px;">
  <div style="max-width:520px; margin:0 auto; background:#1a1d27; border-radius:16px; padding:40px; border:1px solid rgba(255,255,255,0.08);">
    <div style="text-align:center; margin-bottom:32px;">
      <div style="display:inline-block; background:linear-gradient(135deg,#6366f1,#4f46e5); border-radius:12px; padding:12px 20px;">
        <span style="font-size:20px; font-weight:700; color:white;">DataPilot</span>
      </div>
    </div>
    <h1 style="font-size:24px; font-weight:700; color:#f1f5f9; margin:0 0 8px;">Verify your email</h1>
    <p style="color:#94a3b8; margin:0 0 32px; line-height:1.6;">Hi {name}, welcome to DataPilot! Click the button below to verify your email address and activate your account.</p>
    <div style="text-align:center; margin:32px 0;">
      <a href="{verify_url}" style="display:inline-block; background:linear-gradient(135deg,#6366f1,#4f46e5); color:white; text-decoration:none; padding:14px 32px; border-radius:10px; font-weight:600; font-size:15px;">Verify Email Address</a>
    </div>
    <p style="color:#64748b; font-size:13px; margin:24px 0 0; text-align:center;">Link expires in 24 hours. If you didn't sign up, ignore this email.</p>
    <hr style="border:none; border-top:1px solid rgba(255,255,255,0.06); margin:24px 0;">
    <p style="color:#475569; font-size:12px; text-align:center; margin:0;">Or copy this URL:<br><a href="{verify_url}" style="color:#6366f1; word-break:break-all;">{verify_url}</a></p>
  </div>
</body>
</html>"""

    return _send_email(to_email, subject, html_body, text_body)


def send_password_reset_email(to_email: str, full_name: Optional[str], raw_token: str) -> bool:
    """Send a password reset link."""
    name = full_name or to_email.split("@")[0]
    reset_url = f"{APP_URL}/reset-password?token={raw_token}"

    subject = "Reset your DataPilot password"

    text_body = f"""Hi {name},

We received a request to reset the password for your DataPilot account.

Click the link below (expires in 1 hour):
{reset_url}

If you did not request a password reset, you can safely ignore this email. Your password will not change.

— The DataPilot Team
"""

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f1117; color:#e2e8f0; padding:40px 20px;">
  <div style="max-width:520px; margin:0 auto; background:#1a1d27; border-radius:16px; padding:40px; border:1px solid rgba(255,255,255,0.08);">
    <div style="text-align:center; margin-bottom:32px;">
      <div style="display:inline-block; background:linear-gradient(135deg,#6366f1,#4f46e5); border-radius:12px; padding:12px 20px;">
        <span style="font-size:20px; font-weight:700; color:white;">DataPilot</span>
      </div>
    </div>
    <h1 style="font-size:24px; font-weight:700; color:#f1f5f9; margin:0 0 8px;">Reset your password</h1>
    <p style="color:#94a3b8; margin:0 0 32px; line-height:1.6;">Hi {name}, we received a request to reset your DataPilot account password. Click below to set a new one.</p>
    <div style="text-align:center; margin:32px 0;">
      <a href="{reset_url}" style="display:inline-block; background:linear-gradient(135deg,#ef4444,#dc2626); color:white; text-decoration:none; padding:14px 32px; border-radius:10px; font-weight:600; font-size:15px;">Reset Password</a>
    </div>
    <p style="color:#64748b; font-size:13px; margin:24px 0 0; text-align:center;">This link expires in 1 hour. If you didn't request this, ignore this email — your password won't change.</p>
    <hr style="border:none; border-top:1px solid rgba(255,255,255,0.06); margin:24px 0;">
    <p style="color:#475569; font-size:12px; text-align:center; margin:0;">Or copy this URL:<br><a href="{reset_url}" style="color:#6366f1; word-break:break-all;">{reset_url}</a></p>
  </div>
</body>
</html>"""

    return _send_email(to_email, subject, html_body, text_body)
