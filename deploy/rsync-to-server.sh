#!/usr/bin/env bash
# Production deploy: proje dosyalarını sunucuya gönder (.env dahil)
set -euo pipefail

SERVER="${DEPLOY_SERVER:-root@45.141.150.48}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/opt/roof_tattoo}"
EXPECTED_DIR="/opt/roof_tattoo"
EXPECTED_TITLE="Roof Tattoo Gallery"
DOMAIN="tattoo.roof.behlulalar.online"
SERVICE="roof-tattoo-backend"
# Proje kökü (bu script deploy/ altında)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$ROOT/backend/.env" ]]; then
  echo "Hata: backend/.env bulunamadı."
  exit 1
fi

if ! grep -q "$EXPECTED_TITLE" "$ROOT/frontend/index.html" 2>/dev/null; then
  echo "HATA: Bu script sadece ROOF projesi içindir (Manus projesinden çalıştırmayın)."
  exit 1
fi

if [[ "$REMOTE_DIR" != "$EXPECTED_DIR" ]]; then
  echo "HATA: REMOTE_DIR=$REMOTE_DIR — beklenen: $EXPECTED_DIR"
  exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ROOF TATTOO GALLERY                             ║"
echo "║  Domain : $DOMAIN"
echo "║  Hedef  : $SERVER:$REMOTE_DIR"
echo "╚══════════════════════════════════════════════════╝"
echo ""
read -r -p "Doğru projeyi deploy ediyorsunuz. Devam? [y/N] " confirm
[[ "${confirm:-N}" =~ ^[yY]$ ]] || exit 0

if grep -q 'SUNUCU_POSTGRES_SIFRESI' "$ROOT/backend/.env" 2>/dev/null; then
  echo "Uyarı: backend/.env içinde DATABASE_PASSWORD hâlâ SUNUCU_POSTGRES_SIFRESI."
  echo "       Sunucudaki gerçek PostgreSQL şifresini yazın, sonra tekrar çalıştırın."
  read -r -p "Yine de devam edilsin mi? [y/N] " ans
  [[ "${ans:-N}" =~ ^[yY]$ ]] || exit 1
fi

echo "→ $SERVER:$REMOTE_DIR"

rsync -avz --delete \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude 'venv/' \
  --exclude 'backend/.venv/' \
  --exclude 'backend/__pycache__/' \
  --exclude 'backend/*.log' \
  --exclude 'backend/app.log.*' \
  --exclude 'backend/backups/' \
  --exclude 'backend/.env.local' \
  --exclude 'backend/dump_*.sql' \
  --exclude 'backend/*_pgadmin.sql' \
  --exclude '.cursor/' \
  "$ROOT/" "$SERVER:$REMOTE_DIR/"

echo ""
echo "Sunucuda (SADECE Roof — diğer sistemlere dokunmaz):"
echo "  bash $REMOTE_DIR/deploy/fix-roof-only-on-server.sh"
echo "  bash $REMOTE_DIR/deploy/verify-roof-on-server.sh"
echo "  curl -s --resolve ${DOMAIN}:443:127.0.0.1 https://${DOMAIN}/api/health -k"
