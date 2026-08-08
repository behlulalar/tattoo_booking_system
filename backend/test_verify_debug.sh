#!/bin/bash
# Doğrulama kodu test ve debug script'i

echo "=========================================="
echo "  Doğrulama Kodu Debug Testi"
echo "=========================================="
echo ""

# 1. Kod gönder
echo "[1] Kod gönderiliyor (telefon: 5359708001)..."
SEND_RESPONSE=$(curl -s -X POST http://localhost:3000/api/send-code \
  -H "Content-Type: application/json" \
  -d '{"phone":"5359708001"}')

echo "Gönderim yanıtı: $SEND_RESPONSE"
echo ""

# 2. Backend loglarında kod kaydını kontrol et
echo "[2] Son backend logları (kod gönderimi)..."
sudo journalctl -u randevu-backend -n 20 --no-pager | grep -i "doğrulama\|verification\|5359708001" | tail -10
echo ""

# 3. Bekle (2 saniye)
sleep 2

# 4. Doğrulama dene (geçersiz kod ile - kod kaydının varlığını test et)
echo "[3] Doğrulama testi (geçersiz kod - kodun kayıtlı olup olmadığını kontrol eder)..."
VERIFY_RESPONSE=$(curl -s -X POST http://localhost:3000/api/verify-code \
  -H "Content-Type: application/json" \
  -d '{"phone":"5359708001","code":"999999"}')

echo "Doğrulama yanıtı: $VERIFY_RESPONSE"
echo ""

# Eğer "Doğrulama kodu yanlış" derse, kod kaydedilmiş demektir
# Eğer "Doğrulama kodu bulunamadı" derse, kod kaydedilmemiş demektir

if echo "$VERIFY_RESPONSE" | grep -q "yanlış"; then
    echo "✅ Kod kaydedilmiş (yanlış kod mesajı aldık)"
elif echo "$VERIFY_RESPONSE" | grep -q "bulunamadı"; then
    echo "❌ Kod kaydedilmemiş (kod bulunamadı mesajı aldık)"
fi

echo ""
echo "=========================================="
echo "  Test Tamamlandı"
echo "=========================================="
echo ""
echo "Not: Gerçek kodu test etmek için WhatsApp'tan gelen"
echo "kodu kullanın: curl -X POST http://localhost:3000/api/verify-code \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"phone\":\"5359708001\",\"code\":\"GERÇEK_KOD\"}'"

