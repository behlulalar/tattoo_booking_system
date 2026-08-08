"""
Kritik Hata E-posta Bildirim Modülü
Sefa Pertev Hair Studio - Randevu Sistemi

Bu modül kritik hatalarda e-posta bildirimi gönderir.
Rate limiting ile spam önlenir (aynı hata için saatte 1 e-posta).
"""

import os
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

# E-posta yapılandırması (.env'den)
SMTP_HOST = os.getenv('EMAIL_SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('EMAIL_SMTP_PORT', '587'))
EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_RECIPIENT = os.getenv('EMAIL_RECIPIENT', '')

# Rate limiting - aynı hata için minimum bekleme süresi (saniye)
ERROR_COOLDOWN_SECONDS = 3600  # 1 saat

# Son gönderilen hataların kaydı: {error_key: timestamp}
_sent_errors = {}


def is_configured():
    """E-posta ayarlarının yapılıp yapılmadığını kontrol eder"""
    return all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT])


def _get_error_key(error_type, error_message):
    """Hata için benzersiz anahtar oluşturur"""
    return f"{error_type}:{error_message[:100]}"


def _should_send(error_key):
    """Rate limiting kontrolü - bu hata için e-posta gönderilmeli mi?"""
    current_time = time.time()
    
    if error_key in _sent_errors:
        last_sent = _sent_errors[error_key]
        if current_time - last_sent < ERROR_COOLDOWN_SECONDS:
            return False
    
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
        subject = f"🚨 Kritik Hata - Sefa Pertev Randevu Sistemi"
        
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
                    <h1>🚨 Kritik Sistem Hatası</h1>
                </div>
                
                <div class="error-box">
                    <p><strong>Hata Tipi:</strong> {error_type}</p>
                    <p><strong>Mesaj:</strong> {error_message}</p>
                </div>
                
                <div class="detail-row">
                    <span class="label">Tarih/Saat:</span> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
                </div>
                
                <div class="detail-row">
                    <span class="label">Sunucu:</span> localhost (Local Development)
                </div>
                
                {"<div class='error-box'><pre>" + str(details) + "</pre></div>" if details else ""}
                
                <div class="footer">
                    <p>Bu otomatik bir bildirimdir. Lütfen sistemi kontrol edin.</p>
                    <p>Sefa Pertev Hair Studio - Randevu Sistemi</p>
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
        
        # Rate limiting kaydı
        _sent_errors[error_key] = time.time()
        
        logger.info(f"✅ Hata bildirimi gönderildi: {error_type}")
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
