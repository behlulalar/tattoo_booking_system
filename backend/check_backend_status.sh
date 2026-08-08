#!/bin/bash
# Backend Durum Kontrol Script'i
# Sunucuda çalıştırılmalı

echo "=========================================="
echo "  Backend Durum Kontrolü"
echo "=========================================="
echo ""

# 1. Service durumu
echo "[1] Service durumu:"
sudo systemctl status randevu-backend --no-pager -l | head -15

echo ""
echo "=========================================="

# 2. Son 30 satır log
echo "[2] Son 30 satır log:"
sudo journalctl -u randevu-backend -n 30 --no-pager

echo ""
echo "=========================================="

# 3. Health check
echo "[3] Health check:"
curl -s http://localhost:3000/api/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:3000/api/health

echo ""
echo "=========================================="

# 4. Veritabanı bağlantısı test
echo "[4] Veritabanı bağlantısı (backend loglarından):"
sudo journalctl -u randevu-backend --since "5 minutes ago" | grep -i "database\|veritabanı\|connection" | tail -10

echo ""
echo "=========================================="

# 5. Process kontrolü
echo "[5] Gunicorn process'leri:"
ps aux | grep gunicorn | grep -v grep

echo ""
echo "=========================================="

# 6. Port kontrolü
echo "[6] Port 3000 dinleniyor mu:"
netstat -tlnp 2>/dev/null | grep 3000 || ss -tlnp 2>/dev/null | grep 3000 || echo "Port kontrol edilemedi"

echo ""
echo "=========================================="

# 7. Wapio settings kontrolü
echo "[7] Wapio ayarları:"
if [ -f "/opt/randevu/backend/wapio_settings.json" ]; then
    echo "✅ wapio_settings.json bulundu:"
    cat /opt/randevu/backend/wapio_settings.json | python3 -m json.tool 2>/dev/null || cat /opt/randevu/backend/wapio_settings.json
else
    echo "❌ wapio_settings.json bulunamadı"
fi

echo ""
echo "=========================================="

# 8. .env dosyası kontrolü (sadece varlığını kontrol et, içeriğini gösterme)
echo "[8] .env dosyası:"
if [ -f "/opt/randevu/backend/.env" ]; then
    echo "✅ .env dosyası var"
    echo "   DATABASE_HOST: $(grep DATABASE_HOST /opt/randevu/backend/.env | cut -d'=' -f2 | head -c 30)..."
    echo "   WAPIO_INSTANCE_ID: $(grep WAPIO_INSTANCE_ID /opt/randevu/backend/.env | cut -d'=' -f2 | head -c 30)..."
else
    echo "❌ .env dosyası bulunamadı"
fi

echo ""
echo "✅ Kontrol tamamlandı"

