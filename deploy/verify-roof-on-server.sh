#!/usr/bin/env bash
# SADECE Roof Tattoo doğrulama — diğer sistemlere dokunmaz
# Sunucuda: bash /opt/roof_tattoo/deploy/verify-roof-on-server.sh

set -euo pipefail

DOMAIN="tattoo.roof.behlulalar.online"
DIR="/opt/roof_tattoo"
SOCKET="/opt/roof_tattoo/run/gunicorn.sock"
SERVICE="roof-tattoo-backend"

ERR=0
ok()  { echo "OK   $*"; }
fail(){ echo "HATA $*"; ERR=1; }

echo "=== Roof Tattoo Gallery — izole kontrol ==="

grep -q "$DOMAIN" /etc/nginx/sites-available/roof-tattoo.conf 2>/dev/null \
  && ok "nginx roof-tattoo.conf domain OK" || fail "roof-tattoo.conf eksik/yanlış"

grep -q "tattoo.behlulalar.online" /etc/nginx/sites-available/roof-tattoo.conf 2>/dev/null \
  && fail "roof-tattoo.conf manus domain içeriyor!" || ok "manus domain roof config'te yok"

TITLE=$(grep -o '<title>[^<]*</title>' "$DIR/frontend/index.html" 2>/dev/null || echo YOK)
[[ "$TITLE" == *"Roof"* ]] && ok "frontend: $TITLE" || fail "frontend yanlış: $TITLE"

systemctl is-active "$SERVICE" >/dev/null 2>&1 && ok "$SERVICE çalışıyor" || fail "$SERVICE çalışmıyor"

curl -sf --unix-socket "$SOCKET" "http://localhost/api/health" >/dev/null 2>&1 \
  && ok "API socket OK" || fail "API socket 502"

T=$(curl -s --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/" -k | grep -o '<title>[^<]*</title>' || true)
[[ "$T" == *"Roof"* ]] && ok "HTTPS: $T" || fail "HTTPS yanlış: ${T:-YOK}"

[[ $ERR -eq 0 ]] && echo "Roof sistem OK." || { echo "Sorun var → bash $DIR/deploy/fix-roof-only-on-server.sh"; exit 1; }
