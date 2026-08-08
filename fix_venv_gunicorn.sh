#!/bin/bash
# Virtual Environment ve Gunicorn Düzeltme Script'i
# Sunucuda çalıştırılmalı

echo "=========================================="
echo "  Virtual Environment ve Gunicorn Düzeltme"
echo "=========================================="
echo ""

cd /opt/randevu

# Virtual environment'i kontrol et
if [ ! -d "venv" ]; then
    echo "[1/4] Virtual environment bulunamadı, oluşturuluyor..."
    python3 -m venv venv
else
    echo "[1/4] Virtual environment mevcut, yeniden oluşturuluyor..."
    rm -rf venv
    python3 -m venv venv
fi

# Virtual environment'i aktif et
echo "[2/4] Virtual environment aktif ediliyor..."
source venv/bin/activate

# Pip'i güncelle
echo "[3/4] Pip güncelleniyor..."
pip install --upgrade pip setuptools wheel

# Tüm bağımlılıkları yükle
echo "[4/4] Bağımlılıklar yükleniyor (requirements.txt)..."

# requirements.txt dosyasını farklı konumlarda ara
REQ_FILE=""
if [ -f "backend/requirements.txt" ]; then
    REQ_FILE="backend/requirements.txt"
elif [ -f "/opt/randevu/backend/requirements.txt" ]; then
    REQ_FILE="/opt/randevu/backend/requirements.txt"
elif [ -f "requirements.txt" ]; then
    REQ_FILE="requirements.txt"
fi

if [ -n "$REQ_FILE" ]; then
    echo "📦 requirements.txt bulundu: $REQ_FILE"
    pip install -r "$REQ_FILE"
else
    echo "⚠️  requirements.txt bulunamadı, manuel yükleme yapılıyor..."
    echo "💡 Dosya konumlarını kontrol ediyorum..."
    echo "   - /opt/randevu/backend/requirements.txt: $([ -f /opt/randevu/backend/requirements.txt ] && echo '✅' || echo '❌')"
    echo "   - $(pwd)/backend/requirements.txt: $([ -f backend/requirements.txt ] && echo '✅' || echo '❌')"
    echo ""
    echo "📦 Gerekli paketler manuel olarak yükleniyor..."
    pip install flask>=3.0.0 flask-cors>=4.0.0 flask-limiter>=3.5.0 requests>=2.31.0 python-dotenv>=1.0.0 \
                psycopg2-binary>=2.9.9 PyJWT>=2.8.0 bcrypt>=4.1.2 APScheduler>=3.10.4 \
                marshmallow>=3.20.0 gunicorn>=21.2.0 psutil>=5.9.6
fi

# Gunicorn'un doğru yüklendiğini kontrol et
echo ""
echo "=========================================="
echo "  Kontrol"
echo "=========================================="
echo ""

if [ -f "venv/bin/gunicorn" ]; then
    echo "✅ Gunicorn bulundu"
    venv/bin/gunicorn --version
else
    echo "❌ Gunicorn bulunamadı!"
    exit 1
fi

echo ""
echo "✅ Virtual environment ve Gunicorn hazır!"
echo ""
echo "Test etmek için:"
echo "  source /opt/randevu/venv/bin/activate"
echo "  gunicorn --version"

