#!/bin/bash
# Migration uygulama script'i
# Webhook cooldown ve verification codes tablolarını oluşturur

cd /opt/randevu/backend

# .env dosyasından sadece database değişkenlerini güvenli şekilde al
export DATABASE_HOST=$(grep '^DATABASE_HOST=' .env 2>/dev/null | cut -d '=' -f2 | tr -d ' ' | tr -d '"' | tr -d "'" | head -1)
export DATABASE_PORT=$(grep '^DATABASE_PORT=' .env 2>/dev/null | cut -d '=' -f2 | tr -d ' ' | tr -d '"' | tr -d "'" | head -1)
export DATABASE_USER=$(grep '^DATABASE_USER=' .env 2>/dev/null | cut -d '=' -f2 | tr -d ' ' | tr -d '"' | tr -d "'" | head -1)
export DATABASE_NAME=$(grep '^DATABASE_NAME=' .env 2>/dev/null | cut -d '=' -f2 | tr -d ' ' | tr -d '"' | tr -d "'" | head -1)
export DATABASE_PASSWORD=$(grep '^DATABASE_PASSWORD=' .env 2>/dev/null | cut -d '=' -f2 | tr -d ' ' | tr -d '"' | tr -d "'" | head -1)

# Şifreyi PGPASSWORD olarak ayarla (psql için)
export PGPASSWORD=$DATABASE_PASSWORD

# Migration'ları uygula (ikisini de)
echo "Migration'lar uygulanıyor..."
echo "1. Webhook cooldown table..."
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -f migrations/add_webhook_cooldown_table.sql

if [ $? -eq 0 ]; then
    echo "✅ Webhook cooldown table oluşturuldu"
else
    echo "❌ Webhook cooldown migration hatası!"
    exit 1
fi

echo "2. Verification codes table..."
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -f migrations/add_verification_codes_table.sql

if [ $? -eq 0 ]; then
    echo "✅ Verification codes table oluşturuldu"
    echo ""
    echo "✅ Tüm migration'lar başarıyla uygulandı!"
    echo ""
    echo "Tabloları kontrol etmek için:"
    echo "  psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -c \"SELECT * FROM webhook_cooldown LIMIT 5;\""
    echo "  psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -c \"SELECT * FROM verification_codes LIMIT 5;\""
else
    echo "❌ Verification codes migration hatası!"
    exit 1
fi

