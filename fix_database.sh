#!/bin/bash
# Veritabanı Bağlantı Sorunu Düzeltme
# Sunucuda çalıştırılmalı

echo "=========================================="
echo "  Veritabanı Bağlantı Sorunu Düzeltme"
echo "=========================================="
echo ""

# 1. PostgreSQL servisi çalışıyor mu?
echo "[1] PostgreSQL servisi kontrolü:"
if systemctl is-active --quiet postgresql; then
    echo "✅ PostgreSQL çalışıyor"
    sudo systemctl status postgresql --no-pager -l | head -10
else
    echo "❌ PostgreSQL çalışmıyor!"
    echo "   Başlatılıyor..."
    sudo systemctl start postgresql
    sleep 2
    if systemctl is-active --quiet postgresql; then
        echo "✅ PostgreSQL başlatıldı"
    else
        echo "❌ PostgreSQL başlatılamadı!"
        exit 1
    fi
fi

echo ""
echo "=========================================="

# 2. Veritabanı bağlantısını test et
echo "[2] Veritabanı bağlantı testi:"
cd /opt/randevu/backend
source ../venv/bin/activate

# .env dosyasından veritabanı bilgilerini al
if [ -f ".env" ]; then
    DB_HOST=$(grep DATABASE_HOST .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    DB_PORT=$(grep DATABASE_PORT .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    DB_USER=$(grep DATABASE_USER .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    DB_NAME=$(grep DATABASE_NAME .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    
    echo "   Host: $DB_HOST"
    echo "   Port: $DB_PORT"
    echo "   User: $DB_USER"
    echo "   Database: $DB_NAME"
    
    # PostgreSQL bağlantı testi
    export PGPASSWORD=$(grep DATABASE_PASSWORD .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    if psql -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" > /dev/null 2>&1; then
        echo "✅ Veritabanı bağlantısı başarılı"
    else
        echo "❌ Veritabanı bağlantısı başarısız!"
        echo "   Manuel test için:"
        echo "   psql -h $DB_HOST -p ${DB_PORT:-5432} -U $DB_USER -d $DB_NAME"
    fi
    unset PGPASSWORD
else
    echo "❌ .env dosyası bulunamadı!"
fi

echo ""
echo "=========================================="

# 3. Backend'i yeniden başlat (connection pool'u temizlemek için)
echo "[3] Backend servisi yeniden başlatılıyor..."
sudo systemctl restart randevu-backend
sleep 3

if systemctl is-active --quiet randevu-backend; then
    echo "✅ Backend yeniden başlatıldı"
else
    echo "❌ Backend başlatılamadı!"
    sudo systemctl status randevu-backend --no-pager -l | tail -20
fi

echo ""
echo "=========================================="

# 4. Health check
echo "[4] Health check (5 saniye bekle...):"
sleep 5
curl -s http://localhost:3000/api/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:3000/api/health

echo ""
echo ""
echo "✅ Kontrol tamamlandı"
echo ""
echo "Eğer veritabanı hala bağlanamıyorsa:"
echo "  1. PostgreSQL loglarını kontrol et: sudo tail -50 /var/log/postgresql/postgresql-*.log"
echo "  2. .env dosyasındaki veritabanı bilgilerini kontrol et"
echo "  3. PostgreSQL'in dışarıdan erişilebilir olduğundan emin ol"

