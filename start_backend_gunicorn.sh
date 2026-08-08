#!/bin/bash
# Production Backend Başlatma Script'i (Gunicorn ile)
# Bu script production ortamında kullanılmalı

echo "========================================"
echo "   Backend Başlatılıyor (Gunicorn)..."
echo "========================================"
echo ""

cd "$(dirname "$0")/backend"

# Virtual environment'i aktif et
if [ -d "../venv" ]; then
    echo "[1/4] Virtual environment aktif ediliyor..."
    source ../venv/bin/activate
else
    echo "❌ Virtual environment bulunamadı! (../venv)"
    echo "Önce virtual environment oluşturun: python3 -m venv venv"
    exit 1
fi

# Gunicorn kontrolü
echo "[2/4] Gunicorn kontrol ediliyor..."
if ! command -v gunicorn &> /dev/null; then
    echo "⚠️  Gunicorn bulunamadı, yükleniyor..."
    pip install gunicorn
fi

# Bağımlılıkları kontrol et
echo "[3/4] Bağımlılıklar kontrol ediliyor..."
pip install -q -r requirements.txt 2>/dev/null || {
    echo "⚠️  Bağımlılıklar yükleniyor..."
    pip install -r requirements.txt
}

# Backend'i Gunicorn ile başlat
echo "[4/4] Backend başlatılıyor (Gunicorn - 4 worker, 2 thread)..."
echo ""
echo "========================================"
echo "   Backend Çalışıyor!"
echo "   Internal URL: http://localhost:3000"
echo "   External URL: http://randevu-al.sefapertev.com"
echo "   Health Check: http://randevu-al.sefapertev.com/api/health"
echo "   Workers: 4"
echo "   Threads per Worker: 2"
echo "   Total Capacity: 8 concurrent requests"
echo "========================================"
echo ""
echo "⚠️  Backend'i durdurmak için Ctrl+C basın"
echo ""

# Gunicorn ile başlat
# -w 4: 4 worker process
# --threads 2: Her worker'da 2 thread
# --timeout 120: 120 saniye timeout
# --max-requests 1000: Her worker 1000 request sonrası restart (memory leak önleme)
# --max-requests-jitter 50: Random jitter (tüm worker'lar aynı anda restart olmasın)
# --preload: Uygulamayı önce yükle (memory tasarrufu)
# --bind 0.0.0.0:3000: Tüm interface'lerde dinle
# --access-logfile -: Access log'ları stdout'a yaz
# --error-logfile -: Error log'ları stderr'a yaz
# --log-level info: Log seviyesi
gunicorn -w 4 \
  --threads 2 \
  --bind 0.0.0.0:3000 \
  --timeout 120 \
  --max-requests 1000 \
  --max-requests-jitter 50 \
  --preload \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  app:app

