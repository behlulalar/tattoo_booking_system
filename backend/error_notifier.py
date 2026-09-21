"""
Kritik Hata E-posta Bildirim Modülü
Roof Tattoo Gallery - Randevu Sistemi

Bu modül kritik hatalarda e-posta bildirimi gönderir.
Rate limiting ile spam önlenir (aynı hata için saatte 1 e-posta).

Rate limit kaydı database'deki error_notification_cooldown tablosunda
tutulur (webhook_cooldown ile aynı desen: atomik INSERT ... ON CONFLICT
... WHERE ... RETURNING claim). Böylece Gunicorn'un birden fazla worker
process'i olsa da aynı hata için tüm sistemde saatte en fazla 1 e-posta
gider — önceden bu kayıt sadece bellekte (worker başına ayrı) tutulduğu
için her worker kendi saatlik hakkını kullanıyor, aynı hata için worker
sayısı kadar e-posta gidebiliyordu.

Database'e erişilemezse (ör. DB'nin kendisi çökmüşse), o an tam da
haber verilmesi gereken durum olduğu için bildirim engellenmez; bu
process'in kendi bellek içi kaydına düşülür (sadece bu worker için
doğru çalışır, ama e-postanın hiç gitmemesinden iyidir).
"""

import os
import smtplib
import socket
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv
import logging

import psycopg2

from config import DATABASE_CONFIG

load_dotenv()

logger = logging.getLogger(__name__)

_SERVER_LABEL = os.getenv('RANDEVU_URL') or socket.gethostname()

# E-posta yapılandırması (.env'den)
SMTP_HOST = os.getenv('EMAIL_SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('EMAIL_SMTP_PORT', '587'))
EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_RECIPIENT = os.getenv('EMAIL_RECIPIENT', '')

# Rate limiting - aynı hata için minimum bekleme süresi (saniye)
ERROR_COOLDOWN_SECONDS = 3600  # 1 saat

# DB'ye erişilemediğinde kullanılan bellek içi yedek kayıt: {error_key: timestamp}
# (sadece o anki worker process'i için geçerlidir, bkz. modül docstring'i)
_sent_errors = {}


def _claim_send_db(error_key):
    """DB'de atomik rate-limit claim'i dener.

    Dönüş: True (gönderilebilir, claim alındı), False (cooldown aktif),
    None (DB'ye erişilemedi, çağıran bellek içi fallback'e düşmeli).
    """
    conn = None
    try:
        conn = psycopg2.connect(connect_timeout=5, **DATABASE_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS error_notification_cooldown (
                error_key VARCHAR(255) PRIMARY KEY,
                last_sent_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO error_notification_cooldown (error_key, last_sent_at)
            VALUES (%s, NOW())
            ON CONFLICT (error_key) DO UPDATE
               SET last_sent_at = NOW()
             WHERE error_notification_cooldown.last_sent_at < NOW() - (%s || ' seconds')::interval
            RETURNING error_key
            """,
            (error_key, ERROR_COOLDOWN_SECONDS),
        )
        claimed = cursor.fetchone() is not None
        conn.commit()
        cursor.close()
        return claimed
    except Exception as e:
        logger.warning(f"error_notification_cooldown DB claim başarısız, bellek içi fallback kullanılacak: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def is_configured():
    """E-posta ayarlarının yapılıp yapılmadığını kontrol eder"""
    return all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT])


def _get_error_key(error_type, error_message):
    """Hata için benzersiz anahtar oluşturur"""
    return f"{error_type}:{error_message[:100]}"


def _should_send(error_key):
    """Rate limiting kontrolü - bu hata için e-posta gönderilmeli mi?

    Önce DB'deki paylaşımlı cooldown tablosu üzerinden atomik claim
    denenir (tüm worker'lar için doğru sonuç verir). DB'ye erişilemezse
    bu process'in kendi bellek içi kaydına düşülür.
    """
    claimed = _claim_send_db(error_key)
    if claimed is not None:
        return claimed

    current_time = time.time()
    last_sent = _sent_errors.get(error_key)
    if last_sent and current_time - last_sent < ERROR_COOLDOWN_SECONDS:
        return False

    _sent_errors[error_key] = current_time
    return True


def send_error_notification(error_type, error_message, details=None):
    """
    Kritik hata bildirimi gönderir.
    
    Args:
        error_type: Hata tipi (örn: "DatabaseError", "APIError")
        error_message: Hata mesajı
        details: Opsiyonel ek detaylar (dict)
    
    Returns:
        bool: E-posta gönderildiyse True
    """
    
    if not is_configured():
        logger.warning("E-posta ayarları yapılmamış, bildirim gönderilemedi")
        return False
    
    error_key = _get_error_key(error_type, error_message)
    
    if not _should_send(error_key):
        logger.info(f"Rate limit aktif, e-posta gönderilmedi: {error_type}")
        return False
    
    try:
        # E-posta içeriği oluştur
        subject = "Kritik Hata - Roof Tattoo Randevu Sistemi"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }}
                .container {{ background: white; padding: 30px; border-radius: 10px; max-width: 600px; margin: 0 auto; }}
                .header {{ background: #ef4444; color: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
                .header h1 {{ margin: 0; font-size: 18px; }}
                .error-box {{ background: #fef2f2; border-left: 4px solid #ef4444; padding: 15px; margin: 15px 0; }}
                .detail-row {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
                .label {{ color: #666; font-weight: bold; }}
                .footer {{ margin-top: 20px; font-size: 12px; color: #999; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Kritik Sistem Hatasi</h1>
                </div>
                
                <div class="error-box">
                    <p><strong>Hata Tipi:</strong> {error_type}</p>
                    <p><strong>Mesaj:</strong> {error_message}</p>
                </div>
                
                <div class="detail-row">
                    <span class="label">Tarih/Saat:</span> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
                </div>
                
                <div class="detail-row">
                    <span class="label">Sunucu:</span> {_SERVER_LABEL}
                </div>
                
                {"<div class='error-box'><pre>" + str(details) + "</pre></div>" if details else ""}
                
                <div class="footer">
                    <p>Bu otomatik bir bildirimdir. Lütfen sistemi kontrol edin.</p>
                    <p>Roof Tattoo Gallery - Randevu Sistemi</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # E-posta oluştur
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECIPIENT
        msg.attach(MIMEText(html_content, 'html'))
        
        # SMTP ile gönder
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        
        logger.info("Hata bildirimi gonderildi | error_type=%s", error_type)
        return True
        
    except Exception as e:
        logger.error(f"E-posta gönderilemedi: {e}")
        return False


def notify_database_error(error):
    """Veritabanı hatası bildirimi"""
    return send_error_notification(
        "DatabaseError",
        str(error),
        {"type": "PostgreSQL bağlantı veya sorgu hatası"}
    )


def notify_api_error(endpoint, error):
    """API hatası bildirimi"""
    return send_error_notification(
        "APIError",
        str(error),
        {"endpoint": endpoint}
    )


def notify_wapio_error(error):
    """Wapio API hatası bildirimi"""
    return send_error_notification(
        "WapioError",
        str(error),
        {"type": "WhatsApp mesaj gönderimi hatası"}
    )


# Test fonksiyonu
if __name__ == '__main__':
    print("=" * 50)
    print("🔔 Error Notifier Test")
    print("=" * 50)
    
    if is_configured():
        print("✅ E-posta ayarları yapılmış")
        print(f"   Gönderen: {EMAIL_SENDER}")
        print(f"   Alıcı: {EMAIL_RECIPIENT}")
        print()
        
        # Test e-postası gönder
        result = send_error_notification(
            "TestError",
            "Bu bir test hata mesajıdır.",
            {"test": True}
        )
        
        if result:
            print("✅ Test e-postası gönderildi!")
        else:
            print("❌ E-posta gönderilemedi")
    else:
        print("❌ E-posta ayarları eksik!")
        print()
        print("Lütfen .env dosyasına şu değerleri ekleyin:")
        print("  EMAIL_SMTP_HOST=smtp.gmail.com")
        print("  EMAIL_SMTP_PORT=587")
        print("  EMAIL_SENDER=your-email@gmail.com")
        print("  EMAIL_PASSWORD=your-app-password")
        print("  EMAIL_RECIPIENT=admin@example.com")
