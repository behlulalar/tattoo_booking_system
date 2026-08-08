#!/usr/bin/env bash
# Sunucuda DB içeriğini kontrol et:
#   bash /opt/roof_tattoo/deploy/check-server-db.sh
set -euo pipefail

ENV_FILE=/opt/roof_tattoo/backend/.env
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Hata: $ENV_FILE yok"
  exit 1
fi

# shellcheck disable=SC1090
source <(grep -E '^DATABASE_' "$ENV_FILE" | sed 's/^/export /')

export PGPASSWORD="${DATABASE_PASSWORD}"

run_sql() {
  psql -h "${DATABASE_HOST}" -p "${DATABASE_PORT}" -U "${DATABASE_USER}" -d "${DATABASE_NAME}" -c "$1"
}

echo "========== SANATÇILAR / PERSONEL (artists) =========="
run_sql "SELECT id, name, phone, role, display_order, created_at FROM artists ORDER BY display_order, id;"

echo ""
echo "========== MÜŞTERİLER (son 10) =========="
run_sql "SELECT id, phone, name, surname, created_at FROM customers ORDER BY id DESC LIMIT 10;"

echo ""
echo "========== DÖVME TALEPLERİ (son 10) =========="
run_sql "SELECT id, customer_id, staff_id, status, size, body_area, created_at FROM tattoo_requests ORDER BY id DESC LIMIT 10;"

echo ""
echo "========== RANDEVULAR (son 10) =========="
run_sql "SELECT id, customer_id, staff_id, appointment_date, appointment_time, status FROM appointments ORDER BY id DESC LIMIT 10;"

echo ""
echo "========== ÖZET SAYILAR =========="
run_sql "SELECT
  (SELECT COUNT(*) FROM artists) AS artists,
  (SELECT COUNT(*) FROM customers) AS customers,
  (SELECT COUNT(*) FROM tattoo_requests) AS tattoo_requests,
  (SELECT COUNT(*) FROM appointments) AS appointments,
  (SELECT COUNT(*) FROM slot_offers) AS slot_offers;"
