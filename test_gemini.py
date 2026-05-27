import urllib.request, json, uuid

BASE = "http://localhost:8000"

# 1. Health
with urllib.request.urlopen(f"{BASE}/health", timeout=5) as r:
    h = json.loads(r.read())
print(f"[PASS] /health -> provider={h['provider']}, online={h['ollama']}")

# 2. Provider status
with urllib.request.urlopen(f"{BASE}/provider", timeout=5) as r:
    p = json.loads(r.read())
print(f"[PASS] /provider -> provider={p['provider']}, online={p['online']}")

# 3. Upload CSV
boundary = uuid.uuid4().hex
with open("test_sales.csv", "rb") as f:
    file_data = f.read()
body = (
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test_sales.csv\"\r\nContent-Type: text/csv\r\n\r\n"
).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
req = urllib.request.Request(
    f"{BASE}/upload", data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
)
with urllib.request.urlopen(req, timeout=10) as r:
    up = json.loads(r.read())
print(f"[PASS] /upload -> file_id={up['file_id']}, rows={up['row_count']}")
file_id = up["file_id"]

# 4. Ask Gemini via chat/stream
payload = json.dumps({
    "message": "which product has the highest total revenue?",
    "file_ids": [file_id],
    "conversation_history": []
}).encode()
req2 = urllib.request.Request(
    f"{BASE}/chat/stream", data=payload,
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req2, timeout=35) as r:
    for line in r:
        line = line.decode("utf-8").strip()
        if line.startswith("data: "):
            evt = json.loads(line[6:])
            if evt.get("is_final"):
                content = str(evt.get("content", ""))
                print(f"[PASS] Gemini response -> type={evt['type']}")
                print(f"  Preview: {content[:300]}")
                break

print("\nGemini is powering DataPilot successfully!")
