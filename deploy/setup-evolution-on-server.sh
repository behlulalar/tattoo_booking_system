#!/usr/bin/env bash
# Sunucuda Evolution API (Docker) — Roof Tattoo ile aynı API key
set -euo pipefail

EVOLUTION_DIR="${EVOLUTION_DIR:-/opt/evolution-api}"
ROOF_ENV="${ROOF_ENV:-/opt/roof_tattoo/backend/.env}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "root olarak çalıştırın"; exit 1; }

if ! command -v docker >/dev/null 2>&1; then
  echo "→ Docker kuruluyor..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
  systemctl enable --now docker
fi

mkdir -p "$EVOLUTION_DIR"
cp "$SCRIPT_DIR/evolution-docker-compose.yml" "$EVOLUTION_DIR/docker-compose.yml"

ROOF_KEY=""
if [[ -f "$ROOF_ENV" ]]; then
  ROOF_KEY="$(grep -E '^EVOLUTION_API_KEY=' "$ROOF_ENV" | head -1 | cut -d= -f2- || true)"
fi
if [[ -z "$ROOF_KEY" ]]; then
  ROOF_KEY="$(openssl rand -hex 24)"
  echo "Uyarı: Roof .env içinde EVOLUTION_API_KEY yok; yeni key üretildi — Roof .env ile eşleştirin."
fi

POSTGRES_PASSWORD="$(openssl rand -hex 16)"
cat > "$EVOLUTION_DIR/.env" << EOF
SERVER_NAME=evolution
SERVER_TYPE=http
SERVER_PORT=8080
SERVER_URL=http://127.0.0.1:8080
CORS_ORIGIN=*
CORS_METHODS=GET,POST,PUT,DELETE
CORS_CREDENTIALS=true

DATABASE_PROVIDER=postgresql
DATABASE_CONNECTION_URI=postgresql://evolution:${POSTGRES_PASSWORD}@evolution-postgres:5432/evolution_db?schema=evolution_api
DATABASE_CONNECTION_CLIENT_NAME=evolution_api

DATABASE_SAVE_DATA_INSTANCE=true
DATABASE_SAVE_DATA_NEW_MESSAGE=true
DATABASE_SAVE_MESSAGE_UPDATE=true
DATABASE_SAVE_DATA_CONTACTS=true
DATABASE_SAVE_DATA_CHATS=true
DATABASE_SAVE_DATA_HISTORIC=true
DATABASE_SAVE_DATA_LABELS=true
DATABASE_SAVE_IS_ON_WHATSAPP=true
DATABASE_SAVE_IS_ON_WHATSAPP_DAYS=7
DATABASE_DELETE_MESSAGE=false

CACHE_REDIS_ENABLED=true
CACHE_REDIS_URI=redis://evolution-redis:6379/6
CACHE_REDIS_PREFIX_KEY=evolution-roof
CACHE_REDIS_TTL=604800
CACHE_REDIS_SAVE_INSTANCES=true
CACHE_LOCAL_ENABLED=true

AUTHENTICATION_API_KEY=${ROOF_KEY}
AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES=false

LOG_LEVEL=ERROR,WARN,INFO,WEBHOOKS
TELEMETRY_ENABLED=false

DEL_INSTANCE=false
DEL_TEMP_INSTANCES=true

POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
EOF

chmod 600 "$EVOLUTION_DIR/.env"

echo "→ Evolution container'ları başlatılıyor ($EVOLUTION_DIR)..."
cd "$EVOLUTION_DIR"
docker compose pull
docker compose up -d

echo "→ Evolution API hazır olana kadar bekleniyor..."
for i in $(seq 1 60); do
  if curl -sf -o /dev/null -H "apikey: ${ROOF_KEY}" "http://127.0.0.1:8080/" 2>/dev/null; then
    echo "Evolution API yanıt veriyor."
    break
  fi
  sleep 3
  if [[ $i -eq 60 ]]; then
    echo "Zaman aşımı — docker logs evolution_api"
    docker logs evolution_api --tail 40
    exit 1
  fi
done

# Roof .env senkronu
if [[ -f "$ROOF_ENV" ]]; then
  grep -q '^EVOLUTION_API_URL=' "$ROOF_ENV" || echo 'EVOLUTION_API_URL=http://127.0.0.1:8080' >> "$ROOF_ENV"
  grep -q '^EVOLUTION_INSTANCE_NAME=' "$ROOF_ENV" || echo 'EVOLUTION_INSTANCE_NAME=roof-tattoo' >> "$ROOF_ENV"
  if grep -q '^EVOLUTION_API_KEY=' "$ROOF_ENV"; then
    sed -i "s|^EVOLUTION_API_KEY=.*|EVOLUTION_API_KEY=${ROOF_KEY}|" "$ROOF_ENV"
  else
    echo "EVOLUTION_API_KEY=${ROOF_KEY}" >> "$ROOF_ENV"
  fi
  grep -q '^WHATSAPP_PROVIDER=' "$ROOF_ENV" || echo 'WHATSAPP_PROVIDER=evolution' >> "$ROOF_ENV"
  systemctl restart roof-tattoo-backend || true
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Evolution API kuruldu (127.0.0.1:8080)          ║"
echo "╚══════════════════════════════════════════════════╝"
echo "Admin panel: WhatsApp → Instance oluştur → QR → Webhook"
echo "Webhook: https://tattoo.roof.behlulalar.online/api/whatsapp/webhook"
docker compose ps
