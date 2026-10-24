#!/bin/sh
# Starts the API (uvicorn) and nginx in one container; exits if either stops,
# so Hugging Face restarts the Space.
set -eu
cd /app

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "WARNING: GEMINI_API_KEY is not set. Add it as a secret in the Space settings; AI features will fail until then." >&2
fi

# Sessions only need to survive until the next restart (the SQLite database is
# wiped then too), so a per-boot secret is fine when none is configured.
if [ -z "${JWT_SECRET:-}" ]; then
  JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(64))')"
  export JWT_SECRET
  echo "JWT_SECRET not set; generated a temporary one for this boot." >&2
fi

python -m alembic upgrade head

uvicorn main:app \
  --host 127.0.0.1 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 \
  --timeout-keep-alive 75 --no-server-header &
API_PID=$!

nginx -c /app/nginx.conf -g 'daemon off;' &
NGINX_PID=$!

# Exit when either process dies.
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$NGINX_PID" 2>/dev/null; do
  sleep 5
done
echo "A process exited; stopping container." >&2
kill "$API_PID" "$NGINX_PID" 2>/dev/null || true
exit 1
