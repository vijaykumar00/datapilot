"""Trust controls: AI off means nothing is sent, accounts can be deleted, data can be exported."""

import asyncio
import io
import json
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

import main
from core.ai_policy import AIDisabledError, DisabledLLM, client_for_workspace
from core.db import SessionLocal
from core.models import DatasetRegistry, Session as ChatSession, User, Workspace
from test_production_hardening import _make_user, _sse_events

CSV = b"region,revenue\nN,10\nS,20\nN,30\n"


def _upload(client, headers):
    up = client.post("/upload", headers=headers, files={"file": ("sales.csv", io.BytesIO(CSV), "text/csv")}).json()
    assert up["success"], up
    return up["file_id"]


def _set_ai(client, user, enabled):
    r = client.put(f"/workspaces/{user['workspace_id']}", headers=user["headers"], json={"ai_enabled": enabled})
    assert r.status_code == 200, r.text
    assert r.json()["workspace"]["ai_enabled"] is enabled


class _Spy:
    """Records every AI call; used to prove nothing is sent when AI is off."""
    calls = 0

    def __init__(self, *a, **k):
        from core.llm_client import LLMSettings
        self.settings = LLMSettings(provider="openai", api_key="sk-test", model="m")

    async def generate(self, *a, **k):
        _Spy.calls += 1
        return '{"sql": "SELECT 1 AS x", "explanation": "x"}'

    async def stream(self, *a, **k):
        _Spy.calls += 1
        yield "hi"


def test_ai_off_sends_nothing_but_engine_still_answers(monkeypatch):
    monkeypatch.setattr(main, "build_client", lambda *a, **k: _Spy())
    monkeypatch.setattr(main, "resolve_settings_for_user", lambda *a, **k: _Spy().settings)
    client = TestClient(main.app)
    owner = _make_user()
    fid = _upload(client, owner["headers"])
    _set_ai(client, owner, False)
    _Spy.calls = 0

    def ask(q):
        r = client.post("/chat/stream", headers=owner["headers"], json={"message": q, "file_ids": [fid]})
        return _sse_events(r.text)[-1]

    final = ask("total revenue by region")
    assert final["type"] != "error" and final["metadata"]["answered_by"] == "engine"
    final = ask("why did revenue fall in the south compared to last year?")  # needs AI
    assert final["type"] == "error" and "AI is turned off" in final["content"]
    ask("draw a chart of revenue")  # may be drawn without AI, or refused; never sent
    ask("hello, what can you do?")
    assert _Spy.calls == 0

    # Viewer/Member cannot flip the switch; turning it back on works for admins.
    member = _make_user(role="Member", workspace_id=owner["workspace_id"])
    r = client.put(f"/workspaces/{owner['workspace_id']}", headers=member["headers"], json={"ai_enabled": True})
    assert r.status_code in (403, 404)
    _set_ai(client, owner, True)


def test_disabled_client_never_calls_and_policy_defaults_on():
    with pytest.raises(AIDisabledError):
        asyncio.run(DisabledLLM().generate("x"))
    assert client_for_workspace(None, lambda: "real") == "real"  # guests / unknown → normal


def test_engine_answers_do_not_use_ai_questions_allowance():
    client = TestClient(main.app)
    owner = _make_user()
    fid = _upload(client, owner["headers"])
    before = client.get("/billing/usage", headers=owner["headers"]).json()
    for _ in range(3):
        r = client.post("/chat/stream", headers=owner["headers"],
                        json={"message": "total revenue by region", "file_ids": [fid]})
        assert _sse_events(r.text)[-1]["metadata"]["answered_by"] == "engine"
    after = client.get("/billing/usage", headers=owner["headers"]).json()
    assert json.dumps(before.get("usage", before)).count("query") >= 0
    used = lambda u: (u.get("usage") or u).get("query_count", 0)  # noqa: E731
    assert used(after) == used(before)


def test_delete_account_removes_user_workspace_and_data():
    client = TestClient(main.app)
    owner = _make_user()
    fid = _upload(client, owner["headers"])
    db = SessionLocal()
    db.add(ChatSession(session_id=str(uuid.uuid4()), name="c", user_id=owner["user_id"],
                       workspace_id=owner["workspace_id"], created_at="2026", updated_at="2026"))
    db.commit(); db.close()

    bad = client.request("DELETE", "/user/account", headers=owner["headers"],
                         json={"confirm_email": "wrong@example.com", "password": "SecurePassword123!"})
    assert bad.status_code == 400
    bad = client.request("DELETE", "/user/account", headers=owner["headers"],
                         json={"confirm_email": owner["email"], "password": "nope"})
    assert bad.status_code == 401
    ok = client.request("DELETE", "/user/account", headers=owner["headers"],
                        json={"confirm_email": owner["email"].upper(), "password": "SecurePassword123!"})
    assert ok.status_code == 200, ok.text
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.user_id == owner["user_id"]).first() is None
        assert db.query(Workspace).filter(Workspace.workspace_id == owner["workspace_id"]).first() is None
        assert db.query(DatasetRegistry).filter(DatasetRegistry.dataset_id == fid).first() is None
        assert db.query(ChatSession).filter(ChatSession.user_id == owner["user_id"]).count() == 0
    finally:
        db.close()
    assert client.get("/files", headers=owner["headers"]).status_code == 401


def test_delete_account_refused_for_shared_workspace():
    client = TestClient(main.app)
    owner = _make_user()
    _make_user(role="Member", workspace_id=owner["workspace_id"])
    r = client.request("DELETE", "/user/account", headers=owner["headers"],
                       json={"confirm_email": owner["email"], "password": "SecurePassword123!"})
    assert r.status_code == 409 and "other people use" in r.json()["error"]


def test_download_all_my_data():
    client = TestClient(main.app)
    owner = _make_user()
    _upload(client, owner["headers"])
    started = client.post("/user/export", headers=owner["headers"])
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    assert client.get(f"/jobs/{job_id}", headers=owner["headers"]).json()["status"] == "succeeded"
    dl = client.get(f"/jobs/{job_id}/download", headers=owner["headers"])
    assert dl.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    names = zf.namelist()
    assert {"README.txt", "account.json", "chats.json", "saved_answers.json", "reports.json"} <= set(names)
    csvs = [n for n in names if n.startswith("datasets/")]
    assert len(csvs) == 1 and zf.read(csvs[0]).decode().startswith("region,revenue")
    assert json.loads(zf.read("account.json"))["email"] == owner["email"]
    # Another user can't download it.
    other = _make_user()
    assert client.get(f"/jobs/{job_id}/download", headers=other["headers"]).status_code == 404


MIGRATION_SCRIPT = r"""
import os, sys, sqlite3
sys.path.insert(0, os.getcwd())
from alembic import command
from alembic.config import Config
from core.db import DATABASE_URL
cfg = Config("alembic.ini"); cfg.set_main_option("script_location", "alembic"); cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
command.upgrade(cfg, "e7a1c2d3b4f5")
path = DATABASE_URL.replace("sqlite:///", "")
c = sqlite3.connect(path)
c.execute("INSERT INTO users (user_id,email,password_hash,is_active,email_verified,created_at,updated_at) VALUES ('u1','a@b.c','x',1,1,'2026-01-01','2026-01-01')")
c.execute("INSERT INTO workspaces (workspace_id,name,plan_tier,owner_id,created_at,updated_at) VALUES ('w1','W','free','u1','2026-01-01','2026-01-01')")
c.execute("INSERT INTO workspace_members (workspace_id,user_id,role,joined_at) VALUES ('w1','u1','Owner','2026-01-01')")
c.commit(); c.close()
command.upgrade(cfg, "head")
c = sqlite3.connect(path)
print(c.execute("SELECT count(*) FROM workspace_members").fetchone()[0], c.execute("SELECT ai_enabled FROM workspaces").fetchone()[0])
"""


def test_ai_switch_migration_keeps_workspace_members_on_sqlite(tmp_path):
    """Regression: a table-rebuild migration on SQLite cascaded and wiped every membership."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'm.db'}", "RUN_MIGRATIONS_ON_STARTUP": "false"}
    out = subprocess.run([sys.executable, "-c", MIGRATION_SCRIPT], cwd=Path(__file__).parent, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "1 1"
