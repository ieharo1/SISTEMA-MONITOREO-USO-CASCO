#!/bin/sh
set -e

python - <<'PY'
import os
import time
import psycopg

host = os.environ.get("POSTGRES_HOST", "postgres")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
name = os.environ.get("POSTGRES_DB", "casco")
user = os.environ.get("POSTGRES_USER", "casco")
password = os.environ.get("POSTGRES_PASSWORD", "casco")

for _ in range(30):
    try:
        conn = psycopg.connect(host=host, port=port, dbname=name, user=user, password=password)
        conn.close()
        print("Database ready")
        break
    except Exception as exc:
        print("Waiting for database...", exc)
        time.sleep(2)
else:
    raise SystemExit("Database not ready")
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"