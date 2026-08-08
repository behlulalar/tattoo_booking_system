#!/bin/bash
# verify-code endpoint kontrolü

echo "=========================================="
echo "  verify-code Endpoint Kontrolü"
echo "=========================================="
echo ""

# 1. Endpoint'in var olup olmadığını kontrol et
echo "[1] Backend'de verify-code endpoint'ini kontrol ediyoruz..."
if grep -q "@app.route('/api/verify-code'" /opt/randevu/backend/app.py; then
    echo "✅ Endpoint tanımlı: /api/verify-code"
else
    echo "❌ Endpoint bulunamadı!"
    exit 1
fi

echo ""

# 2. Route'u göster
echo "[2] Route detayları:"
grep -A 5 "@app.route('/api/verify-code'" /opt/randevu/backend/app.py | head -10
echo ""

# 3. Son logları kontrol et
echo "[3] Son verify-code istekleri (loglar):"
sudo journalctl -u randevu-backend --since "5 minutes ago" | grep -i "verify-code\|verify_code\|POST.*verify" | tail -10
echo ""

# 4. Test isteği gönder
echo "[4] Test isteği gönderiliyor..."
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST http://localhost:3000/api/verify-code \
  -H "Content-Type: application/json" \
  -d '{"phone":"5359708001","code":"999999"}')

HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d':' -f2)
BODY=$(echo "$RESPONSE" | grep -v "HTTP_CODE:")

echo "HTTP Status Code: $HTTP_CODE"
echo "Response Body: $BODY"
echo ""

if [ "$HTTP_CODE" == "404" ]; then
    echo "❌ 404 hatası alındı - Endpoint bulunamıyor!"
    echo ""
    echo "Olası nedenler:"
    echo "  1. Backend yeniden başlatılmamış"
    echo "  2. Gunicorn worker'ları eski kodu çalıştırıyor"
    echo ""
    echo "Çözüm:"
    echo "  sudo systemctl restart randevu-backend"
elif [ "$HTTP_CODE" == "400" ] || [ "$HTTP_CODE" == "200" ]; then
    echo "✅ Endpoint çalışıyor (HTTP $HTTP_CODE)"
else
    echo "⚠️  Beklenmeyen HTTP kodu: $HTTP_CODE"
fi

echo ""
echo "=========================================="

