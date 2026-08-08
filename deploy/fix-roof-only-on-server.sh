#!/usr/bin/env bash
# SADECE Roof Tattoo Gallery — diğer sistemlere DOKUNMAZ
# Sunucuda: bash /opt/roof_tattoo/deploy/fix-roof-only-on-server.sh
#
# Etkilediği tek şeyler:
#   /opt/roof_tattoo
#   /etc/nginx/sites-available/roof-tattoo.conf (+ sites-enabled symlink)
#   roof-tattoo-backend systemd servisi

set -euo pipefail

ROOF_DOMAIN="tattoo.roof.behlulalar.online"
ROOF_DIR="/opt/roof_tattoo"
ROOF_SOCKET="/opt/roof_tattoo/run/gunicorn.sock"
ROOF_SERVICE="roof-tattoo-backend"
ROOF_USER="roofapp"
NGINX_CONF="/etc/nginx/sites-available/roof-tattoo.conf"

[[ $EUID -eq 0 ]] || { echo "root olarak çalıştırın"; exit 1; }

echo "=== Roof Tattoo ONLY fix (Manus/berber/guzellik dokunulmaz) ==="

id "$ROOF_USER" &>/dev/null || useradd --system --home "$ROOF_DIR" --shell /usr/sbin/nologin "$ROOF_USER"

mkdir -p "${ROOF_DIR}/run"
chown "$ROOF_USER":www-data "${ROOF_DIR}/run"
chmod 750 "${ROOF_DIR}/run"
chown -R "$ROOF_USER":www-data "$ROOF_DIR"

ENV_FILE="${ROOF_DIR}/backend/.env"
if [[ -f "$ENV_FILE" ]] && grep -q '^DATABASE_SSLMODE=require' "$ENV_FILE" 2>/dev/null; then
  sed -i '/^DATABASE_SSLMODE=/d' "$ENV_FILE"
  echo "DATABASE_SSLMODE kaldırıldı (yerel PostgreSQL)"
fi
chmod 640 "$ENV_FILE" 2>/dev/null || true
chown "$ROOF_USER":www-data "$ENV_FILE" 2>/dev/null || true

if [[ -f "${ROOF_DIR}/deploy/setup-server-venv.sh" ]]; then
  bash "${ROOF_DIR}/deploy/setup-server-venv.sh"
fi

if [[ -f "${ROOF_DIR}/backend/tattoo-randevu-backend.service.example" ]]; then
  cp "${ROOF_DIR}/backend/tattoo-randevu-backend.service.example" \
     "/etc/systemd/system/${ROOF_SERVICE}.service"
fi

echo "=== Nginx: sadece roof-tattoo.conf ==="
if [[ -f "/etc/letsencrypt/live/${ROOF_DOMAIN}/fullchain.pem" ]]; then
  cat > "$NGINX_CONF" <<EOF
# ROOF ONLY — ${ROOF_DOMAIN}
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${ROOF_DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${ROOF_DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${ROOF_DOMAIN}/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root ${ROOF_DIR}/frontend;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://unix:${ROOF_SOCKET}:;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120;
    }
}

server {
    listen 80;
    listen [::]:80;
    server_name ${ROOF_DOMAIN};
    return 301 https://\$host\$request_uri;
}
EOF
else
  echo "Uyarı: SSL sertifikası yok — HTTP modunda yazıldı"
  cat > "$NGINX_CONF" <<EOF
# ROOF ONLY — ${ROOF_DOMAIN} (HTTP)
server {
    listen 80;
    listen [::]:80;
    server_name ${ROOF_DOMAIN};

    root ${ROOF_DIR}/frontend;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://unix:${ROOF_SOCKET}:;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120;
    }
}
EOF
fi

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/roof-tattoo.conf

if grep -q "tattoo.behlulalar.online" "$NGINX_CONF"; then
  echo "HATA: roof config'e yanlışlıkla manus domain girdi!"
  exit 1
fi

nginx -t
systemctl reload nginx

systemctl daemon-reload
systemctl enable "$ROOF_SERVICE" 2>/dev/null || true
systemctl restart "$ROOF_SERVICE"
sleep 2

echo ""
echo "=== Doğrulama (sadece Roof) ==="
systemctl status "$ROOF_SERVICE" --no-pager || true
ls -la "$ROOF_SOCKET" 2>&1 || echo "Socket yok"
curl -sf --unix-socket "$ROOF_SOCKET" "http://localhost/api/health" && echo "" || echo "Socket health başarısız"
curl -s --resolve "${ROOF_DOMAIN}:443:127.0.0.1" "https://${ROOF_DOMAIN}/api/health" -k || true
echo ""
journalctl -u "$ROOF_SERVICE" -n 15 --no-pager
echo ""
echo "Tamam. Diğer sistemlere dokunulmadı."
