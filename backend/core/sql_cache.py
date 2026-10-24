"""
sql_cache.py — remembers SQL that already answered a question.

Keyed by (workspace, column layout, normalised question).  The table name is
stored as a placeholder so the same question on a re-uploaded file with the
same columns (e.g. next month's export) is answered without an AI call.

Only SQL that executed successfully and returned rows is stored.  Reused SQL is
still executed through the normal sandbox, so a stale entry can never return
data from another dataset or workspace: it only ever runs against the caller's
current table.  All failures are swallowed — the cache is an optimisation.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import random
import re
import uuid

import pandas as pd

logger = logging.getLogger("datapilot.sql_cache")

TABLE_PLACEHOLDER = "{{table}}"
RETENTION_DAYS = 90
_SOFT_WORDS = {"what", "whats", "is", "are", "the", "a", "an", "me", "show", "give", "tell", "please", "can",
               "you", "our", "my", "us", "i", "would", "like", "to", "see", "know"}


def schema_hash(df: pd.DataFrame) -> str:
    layout = [[str(c), str(t)] for c, t in zip(df.columns, df.dtypes)]
    return hashlib.sha256(json.dumps(layout).encode()).hexdigest()


def question_key(question: str) -> str:
    words = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", (question or "").lower())
    return " ".join(w for w in words if w not in _SOFT_WORDS)[:255]


def to_template(sql: str, table_name: str) -> str:
    return re.sub(r'"?\b' + re.escape(table_name) + r'\b"?', TABLE_PLACEHOLDER, sql)


def from_template(template: str, table_name: str) -> str:
    return template.replace(TABLE_PLACEHOLDER, f'"{table_name}"')


def lookup(workspace_id: str | None, df: pd.DataFrame, question: str, table_name: str) -> tuple[str, str] | None:
    """Return (sql, explanation) for a previously answered question, or None."""
    key = question_key(question)
    if not workspace_id or not key:
        return None
    try:
        from core.db import SessionLocal
        from core.models import QuestionSqlCache

        with SessionLocal() as db:
            row = (
                db.query(QuestionSqlCache)
                .filter(
                    QuestionSqlCache.workspace_id == workspace_id,
                    QuestionSqlCache.schema_hash == schema_hash(df),
                    QuestionSqlCache.question_key == key,
                )
                .first()
            )
            if row is None:
                return None
            row.hits = (row.hits or 0) + 1
            row.last_used_at = datetime.datetime.utcnow()
            sql, explanation = from_template(row.sql_template, table_name), row.explanation or ""
            db.commit()
            return sql, explanation
    except Exception as exc:  # pragma: no cover - cache must never break answers
        logger.warning("SQL cache lookup failed: %s", type(exc).__name__)
        return None


def store(workspace_id: str | None, df: pd.DataFrame, question: str, table_name: str, sql: str,
          explanation: str) -> None:
    key = question_key(question)
    if not workspace_id or not key or not sql:
        return
    try:
        from sqlalchemy.exc import IntegrityError

        from core.db import SessionLocal
        from core.models import QuestionSqlCache

        now = datetime.datetime.utcnow()
        with SessionLocal() as db:
            db.add(QuestionSqlCache(
                id=str(uuid.uuid4()), workspace_id=workspace_id, schema_hash=schema_hash(df), question_key=key,
                sql_template=to_template(sql, table_name), explanation=(explanation or "")[:1000],
                hits=0, created_at=now, last_used_at=now,
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # another request stored the same question first
            if random.random() < 0.01:
                cutoff = now - datetime.timedelta(days=RETENTION_DAYS)
                db.query(QuestionSqlCache).filter(QuestionSqlCache.last_used_at < cutoff).delete()
                db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("SQL cache store failed: %s", type(exc).__name__)


def forget(workspace_id: str | None, df: pd.DataFrame, question: str) -> None:
    """Drop a cached answer (e.g. after the user marks it as wrong)."""
    key = question_key(question)
    if not workspace_id or not key:
        return
    try:
        from core.db import SessionLocal
        from core.models import QuestionSqlCache

        with SessionLocal() as db:
            db.query(QuestionSqlCache).filter(
                QuestionSqlCache.workspace_id == workspace_id,
                QuestionSqlCache.schema_hash == schema_hash(df),
                QuestionSqlCache.question_key == key,
            ).delete()
            db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("SQL cache delete failed: %s", type(exc).__name__)
