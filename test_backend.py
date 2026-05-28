"""
End-to-end verification test for DataPilot backend.
Tests: health, upload, clean agent, forecast agent, viz agent.
Uses only ASCII output to avoid Windows cp1252 encoding issues.
"""
import json, sys, urllib.request, uuid

BASE = "http://localhost:8001"

def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
        return json.loads(r.read())

def upload_csv(filepath):
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
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=body,
        headers={"Content-Type": "application/json"}
    )
    events = []
    with urllib.request.urlopen(req, timeout=25) as r:
        for line in r:
            line = line.decode("utf-8").strip()
            if line.startswith("data: "):
                try:
                    evt = json.loads(line[6:])
                    events.append(evt)
                    if evt.get("is_final"):
                        return evt
                except Exception:
                    pass
    return events[-1] if events else {}

results = []

def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}{': ' + detail if detail else ''}")
    results.append(ok)

# 1. Health
try:
    h = get("/health")
    assert h["status"] == "ok"
    check("GET /health", True, f"ollama={h['ollama']}, files={h['files_loaded']}")
except Exception as e:
    check("GET /health", False, str(e))

# 2. Upload
file_id = None
try:
    r = upload_csv("test_sales.csv")
    assert r["success"] is True
    file_id = r["file_id"]
    check("POST /upload", True, f"file_id={file_id}, rows={r['row_count']}, cols={r['column_count']}")
except Exception as e:
    check("POST /upload", False, str(e))

# 3. Files list
try:
    fl = get("/files")
    check("GET /files", True, f"{len(fl['files'])} file(s)")
except Exception as e:
    check("GET /files", False, str(e))

if not file_id:
    print("SKIP: no file_id, cannot run chat tests")
    sys.exit(1)

# 4. Clean agent (pure Python, no LLM)
try:
    evt = read_sse_final("/chat/stream", {
        "message": "check this data for quality issues",
        "file_ids": [file_id],
        "conversation_history": []
    })
    ok = evt.get("type") == "clean"
    check("Clean agent", ok,
          f"type={evt.get('type')}, issues={evt.get('metadata', {}).get('total_issues', '?')}")
except Exception as e:
    check("Clean agent", False, str(e))

# 5. Forecast agent (statsmodels, no LLM)
try:
    evt = read_sse_final("/chat/stream", {
        "message": "forecast the next 3 months",
        "file_ids": [file_id],
        "conversation_history": []
    })
    ok = evt.get("type") == "forecast" and evt.get("chart_data") is not None
    check("Forecast agent", ok,
          f"type={evt.get('type')}, method={evt.get('metadata', {}).get('method', '?')}")
except Exception as e:
    check("Forecast agent", False, str(e))

# 6. Viz agent (keyword match -> no LLM needed)
try:
    evt = read_sse_final("/chat/stream", {
        "message": "show me a bar chart of revenue by product",
        "file_ids": [file_id],
        "conversation_history": []
    })
    ok = evt.get("type") == "visualize" and evt.get("chart_data") is not None
    chart_type = evt.get("chart_data", {}).get("data", [{}])[0].get("type", "?") if ok else "?"
    check("Viz agent", ok, f"type={evt.get('type')}, chart_type={chart_type}")
except Exception as e:
    check("Viz agent", False, str(e))

# 7. Summary agent (LLM needed - graceful degradation)
try:
    evt = read_sse_final("/chat/stream", {
        "message": "summarize this data",
        "file_ids": [file_id],
        "conversation_history": []
    })
    ok = evt.get("type") == "summary"
    check("Summary agent", ok, f"type={evt.get('type')}")
except Exception as e:
    check("Summary agent", False, str(e))

# Summary
passed = sum(results)
total  = len(results)
print(f"\n{'='*50}")
print(f"Results: {passed}/{total} passed")
if passed == total:
    print("ALL TESTS PASSED - DataPilot is ready!")
else:
    print(f"{total - passed} test(s) failed - see output above")
sys.exit(0 if passed == total else 1)
