"""
test_backup_scripts.py — backup/restore drill for the bash and PowerShell scripts.

Runs only when real tools are available (they are not mocked):
  BACKUP_TEST_PG     libpq URL of a Postgres server database usable for CREATE/DROP DATABASE
  pg_dump/pg_restore/psql on PATH, and bash and/or pwsh
  BACKUP_TEST_S3_ENDPOINT (optional) S3-compatible endpoint + `aws` on PATH for the S3 variant
"""

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PG = os.getenv("BACKUP_TEST_PG")

pytestmark = pytest.mark.skipif(
    not PG or not all(shutil.which(t) for t in ("pg_dump", "pg_restore", "psql")),
    reason="BACKUP_TEST_PG and PostgreSQL client tools are required for the backup drill",
)

SHELLS = [s for s in ("bash", "pwsh") if shutil.which(s)]


def _db_url(name: str) -> str:
    # Replace the database name in a URL like postgresql://u@/postgres?host=...
    head, _, tail = PG.partition("?")
    base = head.rsplit("/", 1)[0]
    return f"{base}/{name}" + (f"?{tail}" if tail else "")


def _psql(url: str, sql: str) -> str:
    return subprocess.run(["psql", url, "-Atc", sql], check=True, capture_output=True, text=True).stdout.strip()


def _run(shell: str, script: str, args: list[str], env: dict) -> subprocess.CompletedProcess:
    if shell == "bash":
        cmd = ["bash", str(SCRIPTS / f"{script}.sh"), *args]
    else:
        cmd = ["pwsh", "-NoLogo", "-NoProfile", "-File", str(SCRIPTS / f"{script}.ps1"), *args]
    return subprocess.run(cmd, env={**os.environ, **env}, capture_output=True, text=True)


def _ps_or_sh(shell: str, sh_flag: str, ps_flag: str) -> str:
    return sh_flag if shell == "bash" else ps_flag


@pytest.fixture
def databases():
    src, dst = f"bk_src_{uuid.uuid4().hex[:8]}", f"bk_dst_{uuid.uuid4().hex[:8]}"
    for name in (src, dst):
        _psql(PG, f"CREATE DATABASE {name}")
    _psql(_db_url(src), "CREATE TABLE datasets(id text primary key, n int); INSERT INTO datasets VALUES ('a',1),('b',2)")
    yield _db_url(src), _db_url(dst)
    for name in (src, dst):
        _psql(PG, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.mark.parametrize("shell", SHELLS)
def test_backup_and_restore_include_local_object_store(shell, databases, tmp_path):
    src, dst = databases
    store = tmp_path / "store"
    (store / "objects" / "workspace" / "w1" / "datasets" / "d1" / "versions").mkdir(parents=True)
    (store / "objects" / "workspace" / "w1" / "datasets" / "d1" / "versions" / "1-abc.parquet").write_bytes(b"PAR1data")
    backups = tmp_path / "backups"
    env = {"DATABASE_URL": src.replace("postgresql://", "postgresql+psycopg2://"),  # SQLAlchemy-style URL
           "STORAGE_PROVIDER": "local", "LOCAL_STORAGE_DIR": str(store)}

    res = _run(shell, "backup-postgres", [_ps_or_sh(shell, "--dir", "-BackupDir"), str(backups),
                                          _ps_or_sh(shell, "--with-objects", "-WithObjects")], env)
    assert res.returncode == 0, res.stderr + res.stdout
    dump = next(backups.glob("datapilot-*.dump"))
    manifest = json.loads(next(backups.glob("datapilot-*.manifest.json")).read_text(encoding="utf-8-sig"))
    assert manifest["database"]["included"] is True and manifest["objects"]["included"] is True
    assert manifest["objects"]["files"] == 1
    objects_dir = next(backups.glob("objects-*"))

    # Lose everything, then restore database + objects from the same backup into a fresh place.
    shutil.rmtree(store)
    restore_env = {**env, "DATABASE_URL": dst}
    res = _run(shell, "restore-postgres", [str(dump)], restore_env)
    assert res.returncode != 0  # refuses without explicit confirmation
    res = _run(shell, "restore-postgres", [str(dump), _ps_or_sh(shell, "--objects-dir", "-ObjectsDir"), str(objects_dir),
                                           _ps_or_sh(shell, "--yes", "-Yes")], restore_env)
    assert res.returncode == 0, res.stderr + res.stdout
    assert _psql(dst, "SELECT string_agg(id || ':' || n, ',' ORDER BY id) FROM datasets") == "a:1,b:2"
    restored = store / "objects" / "workspace" / "w1" / "datasets" / "d1" / "versions" / "1-abc.parquet"
    assert restored.read_bytes() == b"PAR1data"

    # Tampered archives are rejected.
    with open(dump, "ab") as fh:
        fh.write(b"tamper")
    res = _run(shell, "restore-postgres", [str(dump), _ps_or_sh(shell, "--verify-only", "-VerifyOnly")], restore_env)
    assert res.returncode != 0 and "Checksum mismatch" in (res.stderr + res.stdout)


@pytest.mark.parametrize("shell", SHELLS)
def test_backup_without_objects_warns_and_records_it(shell, databases, tmp_path):
    src, _ = databases
    backups = tmp_path / "backups"
    res = _run(shell, "backup-postgres", [_ps_or_sh(shell, "--dir", "-BackupDir"), str(backups)],
               {"DATABASE_URL": src, "STORAGE_PROVIDER": "s3", "S3_BUCKET": "unused"})
    assert res.returncode == 0, res.stderr + res.stdout
    assert "NOT backed up" in (res.stderr + res.stdout)
    manifest = json.loads(next(backups.glob("datapilot-*.manifest.json")).read_text(encoding="utf-8-sig"))
    assert manifest["objects"]["included"] is False


@pytest.mark.skipif(not (os.getenv("BACKUP_TEST_S3_ENDPOINT") and shutil.which("aws")),
                    reason="BACKUP_TEST_S3_ENDPOINT and the aws CLI are required for the S3 variant")
@pytest.mark.parametrize("shell", SHELLS)
def test_backup_and_restore_s3_object_store(shell, databases, tmp_path):
    src, dst = databases
    bucket = f"bk-{uuid.uuid4().hex[:8]}"
    endpoint = os.environ["BACKUP_TEST_S3_ENDPOINT"]
    aws_env = {**os.environ, "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID", "test"),
               "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY", "test"), "AWS_DEFAULT_REGION": "us-east-1"}
    aws = ["aws", "--endpoint-url", endpoint, "s3"]
    subprocess.run([*aws, "mb", f"s3://{bucket}"], check=True, env=aws_env, capture_output=True)
    obj = tmp_path / "v.parquet"
    obj.write_bytes(b"PAR1s3")
    subprocess.run([*aws, "cp", str(obj), f"s3://{bucket}/workspace/w/datasets/d/versions/1-x.parquet"],
                   check=True, env=aws_env, capture_output=True)
    env = {k: aws_env[k] for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION")}
    env.update({"DATABASE_URL": src, "STORAGE_PROVIDER": "s3", "S3_BUCKET": bucket, "S3_ENDPOINT_URL": endpoint})
    backups = tmp_path / "backups"
    res = _run(shell, "backup-postgres", [_ps_or_sh(shell, "--dir", "-BackupDir"), str(backups),
                                          _ps_or_sh(shell, "--with-objects", "-WithObjects")], env)
    assert res.returncode == 0, res.stderr + res.stdout
    subprocess.run([*aws, "rm", f"s3://{bucket}", "--recursive"], check=True, env=aws_env, capture_output=True)
    res = _run(shell, "restore-postgres", [str(next(backups.glob("datapilot-*.dump"))),
                                           _ps_or_sh(shell, "--objects-dir", "-ObjectsDir"), str(next(backups.glob("objects-*"))),
                                           _ps_or_sh(shell, "--yes", "-Yes")], {**env, "DATABASE_URL": dst})
    assert res.returncode == 0, res.stderr + res.stdout
    listing = subprocess.run([*aws, "ls", f"s3://{bucket}", "--recursive"], check=True, env=aws_env,
                             capture_output=True, text=True).stdout
    assert "workspace/w/datasets/d/versions/1-x.parquet" in listing
