"""Guest sessions: ending deletes everything, signing in can keep the work."""

import io
import uuid

from fastapi.testclient import TestClient

import main
from core.db import SessionLocal
from core.job_handlers import cleanup_expired_guests
from core.models import DatasetRegistry, GuestSession, Session as ChatSession
from test_production_hardening import _make_user

CSV = b"region,revenue\nN,10\nS,20\nN,30\n"


def _guest(client):
    guest = client.post("/guest/session").json()
    headers = {"X-Guest-Token": guest["guest_token"]}
    up = client.post("/upload", headers=headers, files={"file": ("sales.csv", io.BytesIO(CSV), "text/csv")}).json()
    assert up["success"], up
    return guest, headers, up["file_id"]


def _datasets(workspace_id):
    db = SessionLocal()
    try:
        return [r.dataset_id for r in db.query(DatasetRegistry).filter(DatasetRegistry.workspace_id == workspace_id)]
    finally:
        db.close()


def test_ending_a_guest_session_deletes_all_its_data():
    client = TestClient(main.app)
    guest, headers, file_id = _guest(client)
    gid = guest["guest_session_id"]
    db = SessionLocal()
    db.add(ChatSession(session_id=str(uuid.uuid4()), name="Chat", workspace_id=gid, user_id=gid, guest_session_id=gid,
                       created_at="2026-01-01", updated_at="2026-01-01"))
    db.commit()
    db.close()

    resp = client.delete("/guest/session", headers=headers)
    assert resp.status_code == 200 and resp.json()["deleted"]["datasets"] == 1
    assert _datasets(gid) == []
    db = SessionLocal()
    try:
        assert db.query(ChatSession).filter(ChatSession.workspace_id == gid).count() == 0
        assert db.query(GuestSession).filter(GuestSession.guest_session_id == gid).first() is None
    finally:
        db.close()
    # The old token no longer works, and ending twice is harmless.
    assert client.get(f"/files/{file_id}", headers=headers).status_code in (401, 404)
    assert client.delete("/guest/session", headers=headers).status_code == 200


def test_ending_one_guest_session_never_touches_another():
    client = TestClient(main.app)
    _, headers_a, _ = _guest(client)
    guest_b, headers_b, file_b = _guest(client)
    assert client.delete("/guest/session", headers=headers_a).status_code == 200
    assert _datasets(guest_b["guest_session_id"]) == [file_b]
    assert client.get(f"/files/{file_b}", headers=headers_b).status_code == 200


def test_signing_in_claims_guest_work_into_the_account():
    client = TestClient(main.app)
    guest, gh, file_id = _guest(client)
    owner = _make_user()
    resp = client.post("/guest/claim", headers={**owner["headers"], **gh})
    assert resp.status_code == 200, resp.text
    assert resp.json()["transferred"]["datasets"] == 1
    assert client.get(f"/files/{file_id}", headers=owner["headers"]).status_code == 200
    # The guest token is spent: it can't be claimed twice or used to read the data.
    assert client.post("/guest/claim", headers={**owner["headers"], **gh}).status_code == 404
    assert client.get(f"/files/{file_id}", headers=gh).status_code in (401, 404)
    # The claimed data is never purged as an expired guest.
    db = SessionLocal()
    try:
        db.query(GuestSession).filter(GuestSession.guest_session_id == guest["guest_session_id"]).update(
            {"expires_at": GuestSession.created_at})
        db.commit()
    finally:
        db.close()
    cleanup_expired_guests()
    assert client.get(f"/files/{file_id}", headers=owner["headers"]).status_code == 200


def test_claim_requires_a_signed_in_member():
    client = TestClient(main.app)
    _, gh, _ = _guest(client)
    assert client.post("/guest/claim", headers=gh).status_code == 401
    viewer = _make_user(role="Viewer")
    assert client.post("/guest/claim", headers={**viewer["headers"], **gh}).status_code == 403


def test_expired_guest_data_is_purged_by_the_worker():
    client = TestClient(main.app)
    guest, _, _ = _guest(client)
    gid = guest["guest_session_id"]
    db = SessionLocal()
    try:
        db.query(GuestSession).filter(GuestSession.guest_session_id == gid).update(
            {"expires_at": GuestSession.created_at})
        db.commit()
    finally:
        db.close()
    assert cleanup_expired_guests() >= 1
    assert _datasets(gid) == []


def test_bundled_sample_data_has_no_schema_warnings():
    """The sample file is the first thing many people see: it must look clean."""
    from pathlib import Path

    from core.error_intelligence import diagnose_schema
    from core.parsing import parse_file

    sample = Path(__file__).parent.parent / "frontend" / "public" / "samples" / "sample-sales.csv"
    df, _ = parse_file(sample, ".csv")
    assert diagnose_schema(df, sample.name) == []
    # Ambiguous text dates and numeric IDs are still flagged.
    import pandas as pd
    other = pd.DataFrame({"order_date": [f"0{m}/15/2025" for m in range(1, 9)], "customer_id": list(range(8))})
    codes = {w["code"] for w in diagnose_schema(other, "x.csv")}
    assert {"DATE_AS_TEXT", "ID_COLUMN_METRIC"} <= codes
