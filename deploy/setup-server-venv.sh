#!/usr/bin/env bash
# Sunucuda bir kez veya rsync sonrası venv yoksa çalıştır:
#   bash /opt/roof_tattoo/deploy/setup-server-venv.sh
set -euo pipefail

APP_DIR=/opt/roof_tattoo
VENV="$APP_DIR/venv"
REQ="$APP_DIR/backend/requirements.txt"

if [[ ! -f "$REQ" ]]; then
  echo "Hata: $REQ bulunamadı"
  exit 1
fi

echo "=== Python venv: $VENV ==="
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$REQ"

echo "=== Gunicorn ==="
"$VENV/bin/gunicorn" --version
ls -la "$VENV/bin/gunicorn"

echo "=== İzinler ==="
chown -R roofapp:www-data "$APP_DIR"

echo "Tamam. Şimdi: systemctl restart roof-tattoo-backend"
