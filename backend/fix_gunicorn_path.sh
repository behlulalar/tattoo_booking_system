#!/bin/bash
# Gunicorn Path Düzeltme - Basit ve Net
# Sunucuda çalıştır: bash fix_gunicorn_path.sh

echo "=========================================="
echo "  Gunicorn Path Düzeltme"
echo "=========================================="

cd /opt/roof_tattoo

# 1. Gunicorn nerede?
echo ""
echo "[1] Gunicorn dosyasını arıyorum..."

GUNICORN_PATH=""
if [ -f "/opt/roof_tattoo/venv/bin/gunicorn" ]; then
    GUNICORN_PATH="/opt/roof_tattoo/venv/bin/gunicorn"
    echo "✅ Bulundu: /opt/roof_tattoo/venv/bin/gunicorn"
elif [ -f "/opt/roof_tattoo/backend/venv/bin/gunicorn" ]; then
    GUNICORN_PATH="/opt/roof_tattoo/backend/venv/bin/gunicorn"
    echo "⚠️  Bulundu: /opt/roof_tattoo/backend/venv/bin/gunicorn (yanlış yerde!)"
elif [ -f "venv/bin/gunicorn" ]; then
    GUNICORN_PATH="$(pwd)/venv/bin/gunicorn"
    echo "✅ Bulundu: $GUNICORN_PATH"
elif [ -f "backend/venv/bin/gunicorn" ]; then
    GUNICORN_PATH="$(pwd)/backend/venv/bin/gunicorn"
    echo "⚠️  Bulundu: $GUNICORN_PATH (yanlış yerde!)"
else
    echo "❌ Gunicorn bulunamadı!"
    echo ""
    echo "Virtual environment oluşturuluyor..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install gunicorn flask flask-cors flask-limiter requests python-dotenv psycopg2-binary bcrypt pyjwt marshmallow apscheduler psutil
    GUNICORN_PATH="/opt/roof_tattoo/venv/bin/gunicorn"
fi

# 2. Eğer backend/venv'de varsa, doğru yere kopyala
if [ -f "/opt/roof_tattoo/backend/venv/bin/gunicorn" ] && [ ! -f "/opt/roof_tattoo/venv/bin/gunicorn" ]; then
    echo ""
    echo "[2] Virtual environment backend/ altında, doğru yere taşınıyor..."
    if [ -d "/opt/roof_tattoo/backend/venv" ]; then
        mv /opt/roof_tattoo/backend/venv /opt/roof_tattoo/venv
        GUNICORN_PATH="/opt/roof_tattoo/venv/bin/gunicorn"
        echo "✅ Taşındı: /opt/roof_tattoo/venv"
    fi
fi

# 3. /opt/roof_tattoo/venv/bin/gunicorn olmalı - kontrol et
if [ ! -f "/opt/roof_tattoo/venv/bin/gunicorn" ]; then
    echo ""
    echo "[3] /opt/roof_tattoo/venv/bin/gunicorn yok, oluşturuluyor..."
    if [ ! -d "/opt/roof_tattoo/venv" ]; then
        python3 -m venv /opt/roof_tattoo/venv
    fi
    source /opt/roof_tattoo/venv/bin/activate
    pip install --upgrade pip
    if [ -f "/opt/roof_tattoo/backend/requirements.txt" ]; then
        pip install -r /opt/roof_tattoo/backend/requirements.txt
    else
        pip install gunicorn flask flask-cors flask-limiter requests python-dotenv psycopg2-binary bcrypt pyjwt marshmallow apscheduler psutil
    fi
fi

# 4. Final kontrol
echo ""
echo "[4] Final kontrol..."
if [ -f "/opt/roof_tattoo/venv/bin/gunicorn" ]; then
    echo "✅ Gunicorn hazır: /opt/roof_tattoo/venv/bin/gunicorn"
    /opt/roof_tattoo/venv/bin/gunicorn --version
    echo ""
    echo "✅ TAMAM! Service'i başlatabilirsiniz:"
    echo "   sudo systemctl daemon-reload"
    echo "   sudo systemctl restart roof-tattoo-backend"
else
    echo "❌ Hala bulunamadı! Manuel kontrol edin."
    exit 1
fi

