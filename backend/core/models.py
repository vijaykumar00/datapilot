import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, BigInteger
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# ─────────────────────────────────────────────────────────────
# 1. Core Auth & Multi-Tenancy Models
# ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    user_id = Column(String(50), primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    workspaces = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("UserAPIKey", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")
    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"

    workspace_id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=True, index=True)
    plan_tier = Column(String(50), default="free", nullable=False)  # free, pro, enterprise
    owner_id = Column(String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="workspace")
    usage_stats = relationship("UsageStats", back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id = Column(String(50), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(50), nullable=False)  # Owner, Admin, Member, Viewer
    joined_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="workspaces")
    workspace = relationship("Workspace", back_populates="members")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String(50), primary_key=True)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="refresh_tokens")


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(String(50), primary_key=True)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(String(50), primary_key=True)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class UserAPIKey(Base):
    __tablename__ = "user_api_keys"

    id = Column(String(50), primary_key=True)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(50), nullable=False)       # openai, gemini, anthropic
    label = Column(String(100), nullable=True)          # display name
    encrypted_key = Column(Text, nullable=False)        # AES-encrypted ciphertext
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="api_keys")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    default_workspace_id = Column(String(50), ForeignKey("workspaces.workspace_id", ondelete="SET NULL"), nullable=True)
    theme = Column(String(20), default="dark", nullable=False)          # dark, light
    notification_email = Column(Boolean, default=True, nullable=False)
    timezone = Column(String(50), default="UTC", nullable=False)
    language = Column(String(10), default="en", nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="settings")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(50), primary_key=True)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    workspace_id = Column(String(50), ForeignKey("workspaces.workspace_id", ondelete="SET NULL"), nullable=True)
    guest_session_id = Column(String(50), nullable=True)
    event_type = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=False)
    ip_address = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)

    user = relationship("User", back_populates="audit_logs")
    workspace = relationship("Workspace", back_populates="audit_logs")


# ─────────────────────────────────────────────────────────────
# 2. Guest Session Model
# ─────────────────────────────────────────────────────────────

class GuestSession(Base):
    __tablename__ = "guest_sessions"

    guest_session_id = Column(String(50), primary_key=True)
    session_token = Column(String(255), unique=True, nullable=False, index=True)  # hashed token for validation
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    # Usage counters (enforced limits)
    upload_count = Column(Integer, default=0, nullable=False)
    query_count = Column(Integer, default=0, nullable=False)
    report_count = Column(Integer, default=0, nullable=False)
    export_count = Column(Integer, default=0, nullable=False)
    # Conversion tracking
    converted_to_user_id = Column(String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    converted_at = Column(DateTime, nullable=True)
    # Expiry
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


# ─────────────────────────────────────────────────────────────
# 3. Usage Stats Model
# ─────────────────────────────────────────────────────────────

class UsageStats(Base):
    __tablename__ = "usage_stats"

    id = Column(String(50), primary_key=True)
    workspace_id = Column(String(50), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(20), nullable=False)          # YYYY-MM (monthly) or YYYY-WW (weekly)
    upload_count = Column(Integer, default=0, nullable=False)
    query_count = Column(Integer, default=0, nullable=False)
    report_count = Column(Integer, default=0, nullable=False)
    export_count = Column(Integer, default=0, nullable=False)
    storage_bytes = Column(BigInteger, default=0, nullable=False)
    ai_tokens_used = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="usage_stats")


# ─────────────────────────────────────────────────────────────
# 4. Existing Analytics & Storage Models
# ─────────────────────────────────────────────────────────────

class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    pinned = Column(Integer, default=0, nullable=False)
    user_id = Column(String(50), nullable=True)
    workspace_id = Column(String(50), nullable=True)
    guest_session_id = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)

    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    saved_analyses = relationship("SavedAnalysis", back_populates="session", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(50), primary_key=True)
    session_id = Column(String(50), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(50), nullable=False)
    chart_data = Column(Text, nullable=True)
    table_data = Column(Text, nullable=True)
    meta = Column("metadata", Text, nullable=True)
    user_id = Column(String(50), nullable=True)
    workspace_id = Column(String(50), nullable=True)
    guest_session_id = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=False)

    session = relationship("Session", back_populates="messages")


class SavedAnalysis(Base):
    __tablename__ = "saved_analyses"

    analysis_id = Column(String(50), primary_key=True)
    session_id = Column(String(50), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    type = Column(String(50), default="insight", nullable=False)
    chart_data = Column(Text, nullable=True)
    table_data = Column(Text, nullable=True)
    meta = Column("metadata", Text, nullable=True)
    file_id = Column(String(50), nullable=True)
    filename = Column(String(255), nullable=True)
    tags = Column(Text, nullable=True)
    starred = Column(Integer, default=0, nullable=False)
    user_id = Column(String(50), nullable=True)
    workspace_id = Column(String(50), nullable=True)
    guest_session_id = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)

    session = relationship("Session", back_populates="saved_analyses")


class Report(Base):
    __tablename__ = "reports"

    report_id = Column(String(50), primary_key=True)
    session_id = Column(String(50), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="", nullable=True)
    version = Column(Integer, default=1, nullable=False)
    parent_report_id = Column(String(50), ForeignKey("reports.report_id", ondelete="SET NULL"), nullable=True)
    prompt = Column(Text, default="", nullable=True)
    content = Column(Text, nullable=False)
    report_type = Column(String(50), default="insight", nullable=False)
    chart_data = Column(Text, nullable=True)
    table_data = Column(Text, nullable=True)
    kpis = Column(Text, nullable=True)
    meta = Column("metadata", Text, default="{}", nullable=False)
    file_id = Column(String(50), nullable=True)
    filename = Column(String(255), nullable=True)
    tags = Column(Text, default="[]", nullable=False)
    starred = Column(Integer, default=0, nullable=False)
    scheduled = Column(Integer, default=0, nullable=False)
    schedule_cron = Column(String(100), nullable=True)
    export_formats = Column(Text, default="[]", nullable=False)
    user_id = Column(String(50), nullable=True)
    workspace_id = Column(String(50), nullable=True)
    guest_session_id = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)

    session = relationship("Session", back_populates="reports")


class DatasetRegistry(Base):
    __tablename__ = "dataset_registry"

    dataset_id = Column(String(50), primary_key=True)
    filename = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, default="", nullable=True)
    tags = Column(Text, default="[]", nullable=False)
    row_count = Column(Integer, default=0, nullable=True)
    column_count = Column(Integer, default=0, nullable=True)
    sheet_count = Column(Integer, default=1, nullable=True)
    file_size_bytes = Column(Integer, default=0, nullable=True)
    archived = Column(Integer, default=0, nullable=False)
    upload_date = Column(String(50), nullable=False)
    last_query_date = Column(String(50), nullable=True)
    session_id = Column(String(50), nullable=True)
    column_summary = Column(Text, default="{}", nullable=False)
    schema_warnings = Column(Text, default="[]", nullable=False)
    user_id = Column(String(50), nullable=True)
    workspace_id = Column(String(50), nullable=True)
    guest_session_id = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class Template(Base):
    __tablename__ = "templates"

    template_id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="", nullable=True)
    category = Column(String(100), nullable=False)
    steps = Column(Text, nullable=False)
    is_builtin = Column(Integer, default=0, nullable=False)
    user_id = Column(String(50), nullable=True)
    workspace_id = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)


class ErrorLog(Base):
    __tablename__ = "error_logs"

    id = Column(String(50), primary_key=True)
    request_id = Column(String(50), nullable=True)
    endpoint = Column(String(255), nullable=False)
    error_type = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    traceback = Column(Text, nullable=True)
    dataset_id = Column(String(50), nullable=True)
    session_id = Column(String(50), nullable=True)
    user_id = Column(String(50), nullable=True)
    workspace_id = Column(String(50), nullable=True)
    timestamp = Column(String(50), nullable=False)


# ── Billing & Subscriptions Models ──────────────────────────────────────────

class Plan(Base):
    __tablename__ = "plans"

    plan_id = Column(String(50), primary_key=True)  # free, pro, business
    name = Column(String(100), nullable=False)
    monthly_price_cents = Column(Integer, nullable=False)
    annual_price_cents = Column(Integer, nullable=False)
    query_limit = Column(Integer, nullable=False)
    upload_limit = Column(Integer, nullable=False)
    file_size_limit_bytes = Column(BigInteger, nullable=False)
    storage_limit_bytes = Column(BigInteger, nullable=False)
    report_limit = Column(Integer, nullable=False)
    export_limit = Column(Integer, nullable=False)
    member_limit = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class BillingCustomer(Base):
    __tablename__ = "billing_customers"

    id = Column(String(50), primary_key=True)
    workspace_id = Column(String(50), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), unique=True, nullable=False)
    stripe_customer_id = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String(50), primary_key=True)
    workspace_id = Column(String(50), ForeignKey("workspaces.workspace_id", ondelete="CASCADE"), nullable=False)
    stripe_subscription_id = Column(String(255), unique=True, nullable=False)
    status = Column(String(50), nullable=False)  # active, trialing, past_due, canceled, incomplete
    plan_id = Column(String(50), ForeignKey("plans.plan_id"), nullable=False)
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    plan = relationship("Plan")


class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"

    id = Column(String(50), primary_key=True)
    stripe_subscription_id = Column(String(255), nullable=False)
    event_type = Column(String(100), nullable=False)
    payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(String(50), primary_key=True)
    stripe_event_id = Column(String(255), unique=True, nullable=False)
    processed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

