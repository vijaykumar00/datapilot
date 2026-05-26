"""
Quick end-to-end verification test for DataPilot backend.
Tests: health, upload, clean agent (no LLM needed), forecast (no LLM needed).
"""
import json
import sys
import urllib.request
import urllib.parse

BASE = "http://localhost:8000"

def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
        return json.loads(r.read())

def post_json(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode()

def upload_csv(filepath):
    import mimetypes, uuid
    boundary = uuid.uuid4().hex
    with open(filepath, "rb") as f:
        file_data = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test_sales.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def read_sse_final(path, data):
    """POST and read SSE stream, returning the final event."""
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body,
                                  headers={"Content-Type": "application/json"})
    events = []
    with urllib.request.urlopen(req, timeout=20) as r:
        for line in r:
            line = line.decode().strip()
            if line.startswith("data: "):
                try:
                    evt = json.loads(line[6:])
                    events.append(evt)
                    if evt.get("is_final"):
                        return evt
                except Exception:
                    pass
    return events[-1] if events else {}

PASS = "✅"
FAIL = "❌"
results = []

# ── 1. Health ─────────────────────────────────────────────────────────────
try:
    h = get("/health")
    assert h["status"] == "ok"
    print(f"{PASS} /health → status=ok, ollama={h['ollama']}")
    results.append(True)
except Exception as e:
    print(f"{FAIL} /health failed: {e}")
    results.append(False)

# ── 2. Upload ─────────────────────────────────────────────────────────────
file_id = None
try:
    r = upload_csv("test_sales.csv")
    assert r["success"] is True
    file_id = r["file_id"]
    print(f"{PASS} /upload → file_id={file_id}, rows={r['row_count']}, cols={r['column_count']}")
    results.append(True)
except Exception as e:
    print(f"{FAIL} /upload failed: {e}")
    results.append(False)

# ── 3. /files list ────────────────────────────────────────────────────────
try:
    fl = get("/files")
    count = len(fl["files"])
    print(f"{PASS} /files → {count} file(s) loaded")
    results.append(True)
except Exception as e:
    print(f"{FAIL} /files failed: {e}")
    results.append(False)

if not file_id:
    print("Skipping chat tests — no file_id")
    sys.exit(1)

# ── 4. Clean agent (pure Python, no LLM) ─────────────────────────────────
try:
    evt = read_sse_final("/chat/stream", {
        "message": "check this data for quality issues",
        "file_ids": [file_id],
        "conversation_history": []
    })
    assert evt.get("type") == "clean", f"Expected 'clean', got '{evt.get('type')}'"
    assert "Data Quality Report" in evt.get("content", "") or "clean" in evt.get("content", "").lower()
    print(f"{PASS} Clean agent → type={evt['type']}, issues={evt.get('metadata', {}).get('total_issues', '?')}")
    results.append(True)
except Exception as e:
    print(f"{FAIL} Clean agent failed: {e}")
    results.append(False)

# ── 5. Forecast agent (statsmodels, no LLM) ───────────────────────────────
try:
    evt = read_sse_final("/chat/stream", {
        "message": "forecast the next 3 months",
        "file_ids": [file_id],
        "conversation_history": []
    })
    assert evt.get("type") == "forecast", f"Expected 'forecast', got '{evt.get('type')}'"
    assert evt.get("chart_data") is not None, "No chart_data in forecast response"
    print(f"{PASS} Forecast agent → type={evt['type']}, method={evt.get('metadata', {}).get('method', '?')}")
    results.append(True)
except Exception as e:
    print(f"{FAIL} Forecast agent failed: {e}")
    results.append(False)

# ── 6. Viz agent (pure Python, no LLM needed for keyword match) ───────────
try:
    evt = read_sse_final("/chat/stream", {
        "message": "show me a bar chart of revenue by product",
        "file_ids": [file_id],
        "conversation_history": []
    })
    assert evt.get("type") == "visualize", f"Expected 'visualize', got '{evt.get('type')}'"
    assert evt.get("chart_data") is not None, "No chart_data in viz response"
    print(f"{PASS} Viz agent → type={evt['type']}, chart={evt['chart_data']['layout'].get('title', {})}")
    results.append(True)
except Exception as e:
    print(f"{FAIL} Viz agent failed: {e}")
    results.append(False)

# ── Summary ───────────────────────────────────────────────────────────────
passed = sum(results)
total = len(results)
print(f"\n{'='*50}")
print(f"Results: {passed}/{total} tests passed")
if passed == total:
    print("🚀 All backend tests PASSED — DataPilot is ready!")
else:
    print("⚠️  Some tests failed — check output above")
sys.exit(0 if passed == total else 1)
