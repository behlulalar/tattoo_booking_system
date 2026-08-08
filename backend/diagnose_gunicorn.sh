#!/bin/bash
# Gunicorn Diagnostik ve Düzeltme Script'i
# Sunucuda çalıştırılmalı

echo "=========================================="
echo "  Gunicorn Diagnostik ve Düzeltme"
echo "=========================================="
echo ""

cd /opt/randevu

# 1. Virtual environment var mı?
echo "[1/5] Virtual environment kontrolü..."
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment bulunamadı!"
    echo "   Oluşturuluyor..."
    python3 -m venv venv
else
    echo "✅ Virtual environment mevcut"
fi

# 2. Virtual environment'ı aktif et
echo ""
echo "[2/5] Virtual environment aktif ediliyor..."
source venv/bin/activate

# 3. Gunicorn dosyası var mı kontrol et
echo ""
echo "[3/5] Gunicorn dosyası kontrolü..."
if [ -f "venv/bin/gunicorn" ]; then
    echo "✅ Gunicorn dosyası bulundu: venv/bin/gunicorn"
    ls -la venv/bin/gunicorn
    echo ""
    echo "İçeriği:"
    head -1 venv/bin/gunicorn
else
    echo "❌ Gunicorn dosyası bulunamadı!"
    echo "   Yükleniyor..."
    pip install --upgrade pip
    pip install gunicorn>=21.2.0
    
    if [ -f "venv/bin/gunicorn" ]; then
        echo "✅ Gunicorn yüklendi!"
    else
        echo "❌ Gunicorn yüklenemedi!"
        exit 1
    fi
fi

# 4. Gunicorn çalışıyor mu test et
echo ""
echo "[4/5] Gunicorn testi..."
if venv/bin/gunicorn --version > /dev/null 2>&1; then
    echo "✅ Gunicorn çalışıyor!"
    venv/bin/gunicorn --version
else
    echo "❌ Gunicorn çalışmıyor!"
    echo "   Hata mesajı:"
    venv/bin/gunicorn --version 2>&1 || true
    exit 1
fi

# 5. Tüm bağımlılıkları kontrol et
echo ""
echo "[5/5] Bağımlılıklar kontrol ediliyor..."
if [ -f "backend/requirements.txt" ]; then
    echo "✅ requirements.txt bulundu"
    pip install -q -r backend/requirements.txt 2>&1 | grep -E "(Requirement|already|Successfully)" || true
else
    echo "⚠️  requirements.txt bulunamadı"
    echo "   Manuel yükleme yapılıyor..."
    pip install flask flask-cors flask-limiter requests python-dotenv psycopg2-binary bcrypt pyjwt marshmallow apscheduler psutil gunicorn
fi

echo ""
echo "=========================================="
echo "  ✅ Kontrol Tamamlandı!"
echo "=========================================="
echo ""
echo "Gunicorn path: $(which gunicorn)"
echo "Python path: $(which python)"
echo ""
echo "Test etmek için:"
echo "  /opt/randevu/venv/bin/gunicorn --version"

