from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
from dotenv import load_dotenv
from config import DATABASE_CONFIG, WAPIO_CONFIG, CODE_EXPIRATION_SECONDS, SITE_CONFIG, get_site_settings, save_site_settings, get_evolution_config, save_evolution_config, get_google_calendar_config, save_google_calendar_config
# Wapio (legacy — dosyalar repoda; runtime devre dışı)
# from config import get_wapio_config, save_wapio_config
# from wapio_compat import run_wapio_compat_check
# from wapio_api_contract import CONTRACT_VERSION
# from wapio_client import (
#     check_session_status as wapio_check_session_status,
#     create_device as wapio_create_device,
#     extract_qr_image,
#     extract_session_id_from_response,
#     get_qr as wapio_get_qr,
#     interpret_session_status,
#     send_text as wapio_send_text,
#     update_webhook as wapio_update_webhook,
# )
from whatsapp_messages import (
    build_aftercare_reminder_message,
    build_appointment_cancelled_message,
    build_appointment_confirmed_message,
    build_appointment_created_customer_message,
    build_appointment_created_staff_message,
    build_appointment_reminder_message,
    build_customer_cancel_confirmation_message,
    build_staff_cancel_notification_message,
    build_tattoo_request_received_message,
    build_tattoo_request_staff_message,
    build_verification_code_message,
    build_welcome_message,
    get_reminder_hours_before,
    get_webhook_cooldown_seconds,
    get_webhook_url,
)
from google_calendar_sync import (
    on_appointment_created,
    on_appointment_status_changed,
    on_appointment_cancelled,
    is_google_calendar_enabled,
    credentials_file_ok,
    get_service_account_email,
    probe_google_calendar,
    list_accessible_calendars,
)
from whatsapp_provider import (
    WAPIO_INTEGRATION_ENABLED,
    check_whatsapp_health,
    get_whatsapp_provider,
    is_whatsapp_demo_mode,
    send_whatsapp_message,
    welcome_message_enabled,
)
from evolution_webhook import parse_evolution_inbound
from evolution_client import (
    connect_instance as evolution_connect_instance,
    create_instance as evolution_create_instance,
    extract_instance_name_from_response,
    extract_qr_image as evolution_extract_qr_image,
    interpret_connection_status as evolution_interpret_connection_status,
    resolve_evolution_connection,
    set_webhook as evolution_set_webhook,
)

def _wapio_disabled_json():
    """Wapio admin/health uçları — WAPIO_INTEGRATION_ENABLED=False iken."""
    return jsonify({
        'success': False,
        'status': 'disabled',
        'message': 'Wapio devre dışı. Evolution API kullanılıyor.',
    }), 503

from loyalty_points import (
    LoyaltyCodeError,
    apply_percent_discount,
    attach_loyalty_code_to_request,
    award_loyalty_on_completion,
    build_loyalty_summary,
    get_request_loyalty_discount,
    mark_redemption_used_for_offer,
    redeem_loyalty_discount,
    validate_loyalty_code_for_customer,
)
import os
import json
import random
import time
import psycopg2
from psycopg2 import pool
import hashlib
import secrets
import bcrypt
import jwt
import logging
import re
import atexit
from functools import wraps
from datetime import datetime, timedelta, time as dt_time
from urllib.parse import urlparse
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from threading import Lock
from marshmallow import Schema, fields, validate, ValidationError, validates
import psutil

from logging_setup import setup_logging, log_error, log_warning
from error_codes import (
    E_AUTH_001,
    E_BKP_001,
    E_BOOK_001,
    E_DB_001,
    E_DB_002,
    E_DB_003,
    E_REQ_001,
    E_SCH_001,
    E_WA_002,
    E_WA_003,
    E_WA_004,
    W_CFG_001,
)

load_dotenv()

# =============================================
# LOGGING CONFIGURATION
# =============================================
import sys

# Force UTF-8 encoding for stdout/stderr
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

setup_logging()
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload size

def build_cors_origins():
    """CORS origin listesini env + varsayılanlardan üret."""
    defaults = [
        "http://localhost", "http://localhost:80", "http://127.0.0.1", "http://127.0.0.1:80",
        "http://localhost:8000", "http://localhost:8080", "http://127.0.0.1:8000", "http://127.0.0.1:8080",
        "https://randevu-al.sefapertev.com", "http://randevu-al.sefapertev.com"
    ]

    env_list = []
    raw_origins = (os.getenv('CORS_ALLOWED_ORIGINS') or '').strip()
    if raw_origins:
        env_list = [o.strip() for o in raw_origins.split(',') if o.strip()]

    # Env tanımlı olsa bile lokal geliştirme origin'lerini koru (sadece prod URL ile ezme)
    origins = list(dict.fromkeys((env_list or []) + defaults))

    frontend_origin = (os.getenv('FRONTEND_ORIGIN') or '').strip()
    if frontend_origin and frontend_origin not in origins:
        origins.append(frontend_origin)

    randevu_url = (SITE_CONFIG.get('randevu_url') or '').strip().rstrip('/')
    if randevu_url and randevu_url not in origins:
        origins.append(randevu_url)

    return origins


CORS(app, resources={r"/api/*": {
    "origins": build_cors_origins(),
    "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"],
    "supports_credentials": True,
    "max_age": 600
}})

# =============================================
# RATE LIMITING
# =============================================
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://",
    strategy="fixed-window"
)
logger.info("Rate limiter initialized") 

# JWT Secret Key
JWT_SECRET = os.getenv('JWT_SECRET', 'sefa-admin-secret-key-2024')

# Bot Phone Number (webhook filtreleme için)
BOT_PHONE_NUMBER = os.getenv('BOT_PHONE_NUMBER', '5359708001')

# Verification codes storage (thread-safe dictionary with automatic cleanup)
verification_codes = {}
verification_lock = Lock()  # Thread safety için Lock
VERIFICATION_CODES_MAX_SIZE = 10000  # Maksimum entry sayısı (memory leak önleme)

# Doğrulama kodu gönderme istatistikleri (Uptime Robot monitoring için)
verification_stats = []  # List of {'timestamp': float, 'success': bool}
verification_stats_lock = Lock()  # Thread safety için Lock
VERIFICATION_STATS_MAX_AGE = 600  # 10 dakika (sadece son 10 dakikanın istatistikleri tutulur)

admin_tokens = {}  # token -> {'staff_id': int, 'expires_at': float} mapping
admin_tokens_lock = Lock()  # Thread safety için Lock
ADMIN_TOKEN_EXPIRY_HOURS = 168  # 7 gün (hafta)

# Generic error messages - never expose system details to users
ERROR_MESSAGES = {
    'general': 'Bir hata oluştu. Lütfen tekrar deneyin.',
    'not_found': 'Kayıt bulunamadı.',
    'invalid_input': 'Geçersiz veri girişi.',
    'unauthorized': 'Bu işlem için yetkiniz yok.',
    'database': 'Veritabanı hatası. Lütfen daha sonra tekrar deneyin.',
    'validation': 'Girdiğiniz bilgiler geçerli değil.',
    'duplicate': 'Bu kayıt zaten mevcut.',
}

# =============================================
# INPUT VALIDATION SCHEMAS (Marshmallow)
# =============================================
class AppointmentSchema(Schema):
    """Randevu oluşturma için input validation schema"""
    phone = fields.String(required=True, validate=validate.Length(equal=10, error='Telefon numarası 10 haneli olmalıdır'))
    staff_id = fields.Integer(required=True, validate=validate.Range(min=1, error='Geçersiz personel ID'))
    service_id = fields.Integer(required=True, validate=validate.Range(min=1, error='Geçersiz hizmet ID'))
    date = fields.String(required=True, validate=validate.Regexp(r'^\d{2}\.\d{2}\.\d{4}$', error='Tarih formatı DD.MM.YYYY olmalıdır'))
    time = fields.String(required=True, validate=validate.Regexp(r'^\d{2}:\d{2}$', error='Saat formatı HH:MM olmalıdır'))
    payment_method = fields.String(required=True, validate=validate.OneOf(['nakit', 'havale'], error='Ödeme yöntemi nakit veya havale olmalıdır'))
    
    @validates('time')
    def validate_time_format(self, value):
        """Saat formatını ve geçerliliğini kontrol et"""
        try:
            hour, minute = map(int, value.split(':'))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValidationError('Geçersiz saat değeri')
            # 30 dakikalık slot kontrolü
            if minute not in [0, 30]:
                raise ValidationError('Saat 30 dakikalık slotlar halinde olmalıdır (örn: 09:00, 09:30)')
        except (ValueError, AttributeError):
            raise ValidationError('Geçersiz saat formatı')


class SendCodeSchema(Schema):
    """Doğrulama kodu gönderme için input validation schema"""
    phone = fields.String(required=True, validate=validate.Length(equal=10, error='Telefon numarası 10 haneli olmalıdır'))

# =============================================
# DATABASE CONNECTION POOL
# =============================================
# Connection pool ayarları (100+ eşzamanlı kullanıcı için optimize edildi)
DB_POOL_MIN_CONN = int(os.getenv('DB_POOL_MIN_CONN', '10'))  # Minimum bağlantı sayısı
DB_POOL_MAX_CONN = int(os.getenv('DB_POOL_MAX_CONN', '50'))  # Maksimum bağlantı sayısı (20'den 50'ye çıkarıldı)
DB_CONNECTION_TIMEOUT = int(os.getenv('DB_CONNECTION_TIMEOUT', '10'))  # Bağlantı alma timeout (saniye)

# Connection pool - her worker process başladığında oluşturulacak
# --preload ile paylaşılan pool yerine, her worker'ın kendi pool'u olacak
db_pool = None

def init_db_pool():
    """Veritabanı bağlantı havuzunu başlat (worker başlangıcında çağrılır)"""
    global db_pool
    if db_pool is None:
        try:
            db_pool = pool.ThreadedConnectionPool(
                minconn=DB_POOL_MIN_CONN,
                maxconn=DB_POOL_MAX_CONN,
                **DATABASE_CONFIG
            )
            logger.info(
                "Veritabani baglanti havuzu olusturuldu | min=%s max=%s",
                DB_POOL_MIN_CONN,
                DB_POOL_MAX_CONN,
            )
        except Exception as e:
            log_error(
                logger,
                E_DB_001,
                "Veritabani baglanti havuzu olusturulamadi",
                exc=e,
            )
            if 'SSL' in str(e) and os.getenv('DATABASE_SSLMODE'):
                log_warning(
                    logger,
                    W_CFG_001,
                    "Yerel PostgreSQL kullaniliyorsa .env icinden DATABASE_SSLMODE satirini kaldirin",
                )
            db_pool = None

# İlk başlatma
init_db_pool()


def _is_connection_alive(conn):
    """Havuzdan gelen bağlantının gerçekten çalıştığını doğrula."""
    try:
        prev_autocommit = conn.autocommit
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
        conn.autocommit = prev_autocommit
        return True
    except Exception:
        return False


def get_db_connection(timeout=None):
    """
    Havuzdan veritabanı bağlantısı al
    
    Args:
        timeout: Bağlantı alma timeout süresi (saniye). None ise DB_CONNECTION_TIMEOUT kullanılır.
    
    Returns:
        psycopg2 connection object
        
    Raises:
        Exception: Veritabanı havuzu kullanılamıyor veya timeout
    """
    if db_pool is None:
        raise Exception("Veritabanı havuzu kullanılamıyor")
    
    timeout = timeout or DB_CONNECTION_TIMEOUT
    start_time = time.time()
    
    try:
        # getconn() blocking bir çağrı - timeout kontrolü için manuel kontrol
        # Not: psycopg2 pool'un kendi timeout mekanizması yok, bu yüzden manuel kontrol
        while True:
            try:
                conn = db_pool.getconn()
                if conn:
                    # Havuzdan kapalı/bozuk bağlantı geldiyse at ve yenisini iste
                    if getattr(conn, 'closed', 0) or not _is_connection_alive(conn):
                        try:
                            db_pool.putconn(conn, close=True)
                        except Exception:
                            pass
                        continue
                    conn.autocommit = False
                    elapsed = time.time() - start_time
                    if elapsed > 0.5:  # 0.5 saniyeden fazla beklediyse logla
                        logger.warning(f"DB bağlantısı {elapsed:.2f} saniyede alındı (yavaş)")
                    return conn
            except pool.PoolError:
                # Pool exhausted - kısa bir süre bekle ve tekrar dene
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    log_error(
                        logger,
                        E_DB_002,
                        "Veritabani baglanti havuzu doldu",
                        timeout_s=timeout,
                    )
                    raise Exception("Sistem yoğun, lütfen tekrar deneyin")
                time.sleep(0.1)  # 100ms bekle
                
    except Exception as e:
        if str(e) == "Sistem yoğun, lütfen tekrar deneyin":
            raise
        log_error(logger, E_DB_002, "Veritabani baglantisi alinamadi", exc=e)
        raise


def release_db_connection(conn, close=False):
    """Bağlantıyı havuza geri ver (hatalı bağlantıları close=True ile kapat)."""
    if db_pool and conn:
        try:
            if close or getattr(conn, 'closed', 0):
                db_pool.putconn(conn, close=True)
            else:
                db_pool.putconn(conn)
        except Exception as e:
            log_error(logger, E_DB_003, "Veritabani baglantisi havuza geri verilemedi", exc=e)


# =============================================
# HEALTH CHECK ENDPOINT (UptimeRobot için)
# =============================================
@app.route('/api/health', methods=['GET'])
def health_check():
    """Sistem sağlık kontrolü - UptimeRobot için"""
    status = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'database': {'connected': False},  # Dictionary olarak başlat
        'services': {
            'flask': True,
            'scheduler': scheduler.running if scheduler else False
        }
    }
    
    # Veritabanı bağlantı kontrolü
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        status['database']['connected'] = True
    except Exception as e:
        status['status'] = 'unhealthy'
        status['database_error'] = str(e)
        logger.error(f"Health check - DB hatası: {e}")
    finally:
        release_db_connection(conn)
    
    # Memory kullanımı (monitoring için)
    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        status['memory'] = {
            'rss_mb': round(memory_info.rss / 1024 / 1024, 2),  # Resident Set Size (MB)
            'vms_mb': round(memory_info.vms / 1024 / 1024, 2),  # Virtual Memory Size (MB)
            'percent': round(process.memory_percent(), 2)  # Memory kullanım yüzdesi
        }
        
        # Dictionary boyutları (memory leak takibi için)
        # Verification codes artık database'de, count al
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM verification_codes WHERE expires_at > NOW()")
            verification_count = cursor.fetchone()[0]
            cursor.close()
            status['memory']['verification_codes_count'] = verification_count
        except Exception as e:
            status['memory']['verification_codes_count'] = -1
            logger.warning(f"Verification codes count hatası: {e}")
        finally:
            release_db_connection(conn)
        # Database'deki webhook cooldown kayıt sayısı
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM webhook_cooldown")
            webhook_count = cursor.fetchone()[0]
            cursor.close()
            status['database']['webhook_cooldown_count'] = webhook_count
        except Exception as e:
            status['database']['webhook_cooldown_count'] = -1
            logger.warning(f"Webhook cooldown count hatası: {e}")
        finally:
            release_db_connection(conn)
        status['memory']['webhook_processed_ids_count'] = len(webhook_processed_message_ids)
        
    except Exception as e:
        logger.warning(f"Memory monitoring hatası: {e}")
        status['memory'] = {'error': 'Could not retrieve memory info'}
    
    http_status = 200 if status['status'] == 'healthy' else 503
    return jsonify(status), http_status


@app.route('/api/health/verification-codes', methods=['GET'])
@limiter.exempt  # Monitoring endpoint'i rate limit'ten muaf
def health_check_verification_codes():
    """Doğrulama kodu gönderme sağlık kontrolü - UptimeRobot için
    
    Son 10 dakika içindeki başarı/başarısızlık oranını kontrol eder.
    Başarısızlık oranı %50'den fazlaysa veya son 5 dakika içinde hiç başarılı gönderim yoksa 503 döndürür.
    """
    current_time = time.time()
    
    with verification_stats_lock:
        # Son 10 dakika içindeki istatistikleri al
        cutoff_time_10min = current_time - VERIFICATION_STATS_MAX_AGE
        recent_stats = [stat for stat in verification_stats if stat['timestamp'] > cutoff_time_10min]
        
        # Son 5 dakika içindeki istatistikleri al
        cutoff_time_5min = current_time - 300  # 5 dakika
        recent_5min_stats = [stat for stat in recent_stats if stat['timestamp'] > cutoff_time_5min]
    
    # İstatistikleri hesapla
    total_count = len(recent_stats)
    success_count = sum(1 for stat in recent_stats if stat['success'])
    failure_count = total_count - success_count
    
    total_5min_count = len(recent_5min_stats)
    success_5min_count = sum(1 for stat in recent_5min_stats if stat['success'])
    
    # Başarı oranı
    success_rate = (success_count / total_count * 100) if total_count > 0 else 100.0
    
    status_data = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'last_10_minutes': {
            'total': total_count,
            'success': success_count,
            'failure': failure_count,
            'success_rate': round(success_rate, 2)
        },
        'last_5_minutes': {
            'total': total_5min_count,
            'success': success_5min_count,
            'failure': total_5min_count - success_5min_count
        }
    }
    
    # Sağlık kontrolü kriterleri
    # 1. Son 10 dakika içinde en az 3 deneme varsa ve başarı oranı %50'den düşükse
    # 2. VEYA son 5 dakika içinde en az 2 deneme varsa ama hiç başarılı gönderim yoksa
    is_unhealthy = False
    
    if total_count >= 3 and success_rate < 50:
        is_unhealthy = True
        status_data['status'] = 'unhealthy'
        status_data['reason'] = f'Başarı oranı çok düşük: %{round(success_rate, 2)}'
    
    if total_5min_count >= 2 and success_5min_count == 0:
        is_unhealthy = True
        status_data['status'] = 'unhealthy'
        status_data['reason'] = 'Son 5 dakika içinde hiç başarılı gönderim yok'
    
    http_status = 503 if is_unhealthy else 200
    return jsonify(status_data), http_status


@app.route('/api/health/whatsapp', methods=['GET'])
@limiter.exempt
def health_check_whatsapp():
    """Aktif WhatsApp sağlayıcısı (Evolution veya Wapio) — UptimeRobot."""
    try:
        debug_mode = request.args.get('debug', '').lower() == 'true'
        result = check_whatsapp_health()
        healthy = bool(result.get('healthy'))
        response_data = {
            'status': 'healthy' if healthy else 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'provider': result.get('provider'),
            'connection': result.get('connection'),
        }
        if debug_mode:
            response_data['http_status'] = result.get('http_status')
        if not healthy:
            response_data['reason'] = result.get('reason') or 'WhatsApp bağlantısı yok'
            return jsonify(response_data), 503
        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"WhatsApp health check hatası: {e}")
        return jsonify({
            'status': 'unhealthy',
            'reason': str(e),
            'timestamp': datetime.now().isoformat(),
        }), 503


@app.route('/api/health/wapio', methods=['GET'])
@limiter.exempt  # Monitoring endpoint'i rate limit'ten muaf
def health_check_wapio():
    """Legacy Wapio health — devre dışı; /api/health/whatsapp kullanın."""
    return jsonify({
        'status': 'disabled',
        'provider': get_whatsapp_provider(),
        'message': 'Wapio devre dışı — /api/health/whatsapp kullanın',
        'timestamp': datetime.now().isoformat(),
    }), 200


def cleanup_expired_verification_codes():
    """
    Expire olan doğrulama kodlarını temizle (Database tabanlı)
    Her 5 dakikada bir çalışır (scheduler ile)
    Artık database tabanlı olduğu için worker'lar arası paylaşımlı
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Süresi dolan kodları sil
        cursor.execute("DELETE FROM verification_codes WHERE expires_at < NOW()")
        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        
        if deleted_count > 0:
            logger.info(f"Expired verification codes cleaned: {deleted_count}")
        
        return deleted_count
    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
        logger.error(f"cleanup_expired_verification_codes hatası: {e}")
        return 0
    finally:
        release_db_connection(conn)


def cleanup_expired_webhook_messages():
    """
    Expire olan webhook cooldown kayıtlarını temizle (Database tabanlı)
    Cooldown süresi (24 saat) geçmiş kayıtları sil
    Her 1 saatte bir çalışır (scheduler ile)
    Artık database tabanlı olduğu için worker'lar arası paylaşımlı ve memory leak sorunu yok
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 24 saatten eski kayıtları sil
        cursor.execute("""
            DELETE FROM webhook_cooldown 
            WHERE last_sent_at < NOW() - INTERVAL '%s seconds'
        """, (WEBHOOK_COOLDOWN_SECONDS,))
        
        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        
        if deleted_count > 0:
            logger.info(f"Expired webhook cooldown records cleaned: {deleted_count}")
        
        return deleted_count
    except Exception as e:
        if conn:
            conn.rollback()
            cursor.close()
        logger.error(f"cleanup_expired_webhook_messages hatası: {e}")
        return 0
    finally:
        release_db_connection(conn)


def cleanup_expired_pending_appointments():
    """Geçmiş tarihli ve hala 'pending' durumundaki randevuları sil (iptal yerine direkt sil)"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Bugünden önceki tarihli ve pending durumundaki randevuları sil (iptal yerine direkt sil)
        cursor.execute("""
            DELETE FROM appointments 
            WHERE status = 'pending' 
              AND appointment_date < CURRENT_DATE
            RETURNING id, appointment_date
        """)
        
        deleted = cursor.fetchall()
        conn.commit()
        cursor.close()
        
        if deleted:
            logger.info(f"Geçmiş tarihli {len(deleted)} bekleyen randevu otomatik silindi: {deleted}")
        
        return len(deleted)
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"cleanup_expired_pending_appointments hatası: {e}")
        return 0
    finally:
        release_db_connection(conn)


def cleanup_old_cancelled_appointments():
    """30 günden eski cancelled randevuları sil (veritabanı şişmesini önler)"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 30 günden eski cancelled randevuları sil
        cursor.execute("""
            DELETE FROM appointments 
            WHERE status = 'cancelled' 
            AND created_at < NOW() - INTERVAL '30 days'
            RETURNING id, appointment_date, appointment_time
        """)
        
        deleted = cursor.fetchall()
        conn.commit()
        cursor.close()
        
        if deleted:
            logger.info(f"{len(deleted)} eski cancelled randevu temizlendi (30+ gün)")
        
        return len(deleted)
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"cleanup_old_cancelled_appointments hatası: {e}")
        return 0
    finally:
        release_db_connection(conn)


def cleanup_expired_admin_tokens():
    """Expired admin token'ları temizle (memory leak önleme)"""
    current_time = time.time()
    expired_count = 0
    
    with admin_tokens_lock:
        # Expired token'ları bul
        expired_tokens = [
            token for token, data in admin_tokens.items()
            if isinstance(data, dict) and current_time > data.get('expires_at', 0)
        ]
        
        # Expired token'ları sil
        for token in expired_tokens:
            admin_tokens.pop(token, None)
            expired_count += 1
        
        # Eğer dictionary çok büyüdüyse (memory leak önleme), en eski token'ları sil
        if len(admin_tokens) > 1000:
            # En eski token'ları bul ve sil
            sorted_items = sorted(
                admin_tokens.items(),
                key=lambda x: x[1].get('expires_at', 0) if isinstance(x[1], dict) else 0
            )
            items_to_remove = sorted_items[:len(admin_tokens) - 1000 + 100]
            for token, _ in items_to_remove:
                admin_tokens.pop(token, None)
                expired_count += 1
            logger.warning(f"Admin tokens dict çok büyüdü, en eski {len(items_to_remove)} token temizlendi")
    
    if expired_count > 0:
        logger.info(f"Expired admin tokens cleaned: {expired_count} (remaining: {len(admin_tokens)})")
    
    return expired_count


# Uygulama başlatıldığında temizlik yap
try:
    cleanup_expired_pending_appointments()
except Exception as e:
    logger.warning(f"Başlangıç temizliği yapılamadı: {e}")


def get_phone_from_lid(lid_number):
    """@lid numarası — OpenAPI'de GetContact yok; numara olduğu gibi kullanılır."""
    logger.info(f"@lid formatı korunuyor (GetContact OpenAPI'de yok): {lid_number}")
    return None


def send_wapio_message(phone, message, retry_count=0, **kwargs):
    """Giden WhatsApp mesajı — aktif sağlayıcıya yönlendirilir (Evolution)."""
    return send_whatsapp_message(phone, message, retry_count, **kwargs)


# =============================================
# PASSWORD HASHING (bcrypt + backwards compatible)
# =============================================
def hash_password_bcrypt(password):
    """Hash password with bcrypt (recommended)"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password, stored_hash):
    """Verify password - supports both bcrypt and legacy SHA256"""
    if stored_hash.startswith('$2'):
        try:
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        except (ValueError, TypeError) as e:
            logger.warning(f"Password verification error (bcrypt): {e}")
            return False
    legacy_hash = hashlib.sha256(password.encode()).hexdigest()
    return password == stored_hash or legacy_hash == stored_hash


def hash_password(password):
    """Legacy hash function for backwards compatibility"""
    return hashlib.sha256(password.encode()).hexdigest()


def passwords_too_similar(old_password, new_password):
    """Yeni şifre mevcut şifre ile aynı veya çok benzer mi?"""
    if not old_password or not new_password:
        return False
    old_pw = old_password.strip()
    new_pw = new_password.strip()
    if old_pw == new_pw:
        return True
    if old_pw.lower() == new_pw.lower():
        return True
    old_low, new_low = old_pw.lower(), new_pw.lower()
    if len(old_low) >= 3 and old_low in new_low:
        return True
    if len(new_low) >= 3 and new_low in old_low:
        return True
    from difflib import SequenceMatcher
    if SequenceMatcher(None, old_low, new_low).ratio() >= 0.72:
        return True
    return False


def token_required(f):
    """Decorator to require valid JWT token for admin endpoints"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token gerekli'}), 401
        
        try:
            # Remove 'Bearer ' prefix if present
            if token.startswith('Bearer '):
                token = token[7:]
            
            data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            request.staff_id = data['staff_id']
            request.staff_role = data['role']
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Token süresi dolmuş'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Geçersiz token'}), 401
        
        return f(*args, **kwargs)
    return decorated


STUDIO_ADMIN_ROLES = ('super_admin', 'tech_support')
ALLOWED_STAFF_ROLES = ('super_admin', 'staff', 'tech_support')


def is_studio_admin(role=None):
    """Super Admin ve Teknik Destek: stüdyo genelinde işlem yapabilir."""
    r = request.staff_role if role is None else role
    return r in STUDIO_ADMIN_ROLES


def can_access_income(role=None):
    """Gelir raporu / kazanç detayı yalnızca Super Admin."""
    r = request.staff_role if role is None else role
    return r == 'super_admin'


def can_access_tattoo_requests(role=None):
    """Dövme talepleri: personel ve super admin. Teknik destek göremez."""
    r = request.staff_role if role is None else role
    return r in ('super_admin', 'staff')


def _role_assignment_error(desired_role=None, existing_role=None):
    if desired_role is not None and desired_role not in ALLOWED_STAFF_ROLES:
        return jsonify({'success': False, 'message': 'Geçersiz rol'}), 400
    if can_access_income():
        return None
    if desired_role == 'super_admin':
        return jsonify({'success': False, 'message': 'Super Admin rolü atayamazsınız'}), 403
    if existing_role == 'super_admin':
        return jsonify({'success': False, 'message': 'Super Admin hesabı üzerinde işlem yapamazsınız'}), 403
    return None


def customer_token_required(f):
    """Decorator to require valid JWT token for customer endpoints"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Giriş gerekli'}), 401
        
        try:
            # Remove 'Bearer ' prefix if present
            if token.startswith('Bearer '):
                token = token[7:]
            
            data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            # Customer token içerir: customer_id, phone, type='customer'
            if data.get('type') != 'customer':
                return jsonify({'success': False, 'message': 'Geçersiz kullanıcı tipi'}), 401
            
            request.customer_id = data['customer_id']
            request.customer_phone = data['phone']
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Oturum süresi dolmuş. Lütfen tekrar giriş yapın'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Geçersiz oturum'}), 401
        
        return f(*args, **kwargs)
    return decorated


def build_slot_select_url(token):
    """Müşteri saat seçimi sayfası linki."""
    base_url = (SITE_CONFIG.get('randevu_url') or '').strip().rstrip('/')
    if base_url:
        return f"{base_url}/slot-select.html?token={token}"
    return f"/slot-select.html?token={token}"


def _fetch_customer_pending_slot_selections(cursor, customer_id):
    """Onaylanmış ama saat seçilmemiş dövme talepleri (aktif slot teklifi)."""
    cursor.execute("""
        SELECT
            tr.id,
            tr.reference_number,
            tr.size,
            tr.body_area,
            tr.tattoo_style,
            tr.estimated_price,
            tr.description,
            so.token,
            so.duration_minutes,
            so.price,
            so.expires_at,
            s.id,
            s.name
        FROM tattoo_requests tr
        JOIN artists s ON tr.staff_id = s.id
        JOIN LATERAL (
            SELECT token, duration_minutes, price, expires_at
            FROM slot_offers
            WHERE tattoo_request_id = tr.id
              AND used_at IS NULL
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY id DESC
            LIMIT 1
        ) so ON TRUE
        WHERE tr.customer_id = %s AND tr.status = 'offered'
        ORDER BY tr.created_at DESC
    """, (customer_id,))
    rows = cursor.fetchall()
    items = []
    for row in rows:
        (tr_id, ref_num, size, body_area, tattoo_style, estimated_price, description,
         token, duration_minutes, offer_price, expires_at, staff_id, staff_name) = row
        items.append({
            'type': 'slot_selection',
            'tattoo_request_id': tr_id,
            'reference_number': ref_num,
            'status': 'slot_pending',
            'slot_select_url': build_slot_select_url(token),
            'duration_minutes': int(duration_minutes or 0),
            'price': float(offer_price or 0),
            'expires_at': expires_at.strftime('%d.%m.%Y %H:%M') if expires_at else None,
            'staff': {'id': staff_id, 'name': staff_name},
            'tattoo': {
                'request_id': tr_id,
                'size': size,
                'body_area': body_area,
                'tattoo_style': tattoo_style,
                'estimated_price': float(estimated_price) if estimated_price is not None else None,
                'description': description,
            },
        })
    return items


# =============================================
# WHATSAPP WEBHOOK - GELEN MESAJLARI İŞLE
# =============================================

# Son mesaj gönderilen numaraları takip et (spam önleme)
# NOT: Memory-based cooldown yerine artık database tabanlı cooldown kullanılıyor
# Bu sayede worker'lar arasında cooldown paylaşılır (multi-worker desteği)
webhook_processed_message_ids = set()  # Processed message IDs (memory-based, sadece aynı worker içinde)
webhook_lock = Lock()  # Webhook thread safety için Lock (sadece message_id kontrolü için)
WEBHOOK_COOLDOWN_SECONDS = get_webhook_cooldown_seconds()


def _handle_whatsapp_welcome_inbound(
    phone,
    body,
    cooldown_key,
    is_whatsapp_id_format,
    message_id=None,
    remote_jid=None,
    remote_jid_alt=None,
):
    """Gelen müşteri mesajına karşılama (Evolution / Wapio ortak mantık)."""
    if not phone:
        logger.warning("Boş telefon numarası/WhatsApp ID")
        return jsonify({'success': True, 'message': 'Geçersiz numara'}), 200

    if not is_whatsapp_id_format and len(str(phone)) < 10:
        logger.warning(f"Geçersiz telefon numarası: {phone}")
        return jsonify({'success': True, 'message': 'Geçersiz numara'}), 200

    if BOT_PHONE_NUMBER and BOT_PHONE_NUMBER in str(phone):
        logger.info(f"Kendi numaramızdan mesaj ({BOT_PHONE_NUMBER}), işlenmeyecek")
        return jsonify({'success': True, 'message': 'Kendi numara'}), 200

    logger.info(f"WhatsApp mesajı alındı: {phone} - {body}")

    if not body or len(str(body).strip()) == 0:
        logger.info(f"Boş mesaj içeriği, karşılama mesajı gönderilmeyecek: {phone}")
        return jsonify({'success': True, 'message': 'Boş mesaj, işlenmedi'}), 200

    if len(str(body).strip()) < 2:
        logger.info(f"Çok kısa mesaj içeriği, karşılama mesajı gönderilmeyecek: {phone}")
        return jsonify({'success': True, 'message': 'Geçersiz mesaj, işlenmedi'}), 200

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_sent_at FROM webhook_cooldown WHERE phone_key = %s",
            (cooldown_key,),
        )
        row = cursor.fetchone()
        if row:
            last_sent_at = row[0]
            time_diff = (datetime.now() - last_sent_at).total_seconds()
            if time_diff < WEBHOOK_COOLDOWN_SECONDS:
                logger.info(
                    f"Cooldown aktif ({time_diff:.1f}s < {WEBHOOK_COOLDOWN_SECONDS}s), mesaj gonderilmedi: {cooldown_key}"
                )
                cursor.close()
                return jsonify({'success': True, 'message': 'Cooldown aktif'}), 200
        cursor.close()
    except Exception as e:
        logger.error(f"Cooldown kontrolü hatası: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            release_db_connection(conn)

    if message_id and message_id in webhook_processed_message_ids:
        logger.info(f"Bu mesaj zaten işlendi (ID: {message_id}), atlanıyor")
        return jsonify({'success': True, 'message': 'Already processed'}), 200

    if not welcome_message_enabled():
        logger.info("Otomatik karsilama mesaji kapali, gonderilmedi | phone=%s", phone)
        return jsonify({'success': True, 'message': 'Karşılama mesajı devre dışı'}), 200

    # Paralel webhook tekrarında aynı message_id ile çift gönderimi azalt
    if message_id:
        webhook_processed_message_ids.add(message_id)

    from evolution_client import normalize_phone_for_send

    send_to = phone if is_whatsapp_id_format else normalize_phone_for_send(phone)
    karsilama_mesaji = build_welcome_message()
    mesaj_gonderildi = send_wapio_message(
        send_to,
        karsilama_mesaji,
        remote_jid=remote_jid,
        remote_jid_alt=remote_jid_alt,
    )

    if mesaj_gonderildi:
        logger.info(f"Karşılama mesajı gönderildi: {cooldown_key}")
        if len(webhook_processed_message_ids) > 1000:
            webhook_processed_message_ids.clear()
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO webhook_cooldown (phone_key, last_sent_at)
                VALUES (%s, NOW())
                ON CONFLICT (phone_key)
                DO UPDATE SET last_sent_at = NOW()
                """,
                (cooldown_key,),
            )
            conn.commit()
            cursor.close()
        except Exception as e:
            logger.error(f"Cooldown kaydetme hatası: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            if conn:
                release_db_connection(conn)
    else:
        logger.warning(f"Mesaj gönderilemedi: {cooldown_key} (cooldown kaydedilmedi)")
        if message_id:
            webhook_processed_message_ids.discard(message_id)

    return jsonify({'success': True, 'message': 'Webhook alındı'}), 200


@app.route('/api/whatsapp/webhook', methods=['POST'])
@limiter.exempt
def whatsapp_webhook():
    """WhatsApp gelen mesaj webhook — Evolution API (MESSAGES_UPSERT)."""
    try:
        if not request.is_json:
            return jsonify({'success': True, 'message': 'Evolution JSON webhook bekleniyor'}), 200
        data = request.get_json()
        event_name = data.get("event") if isinstance(data, dict) else type(data).__name__
        logger.info("WhatsApp webhook alindi | event=%s", event_name)
        if not isinstance(data, dict):
            return jsonify({'success': True, 'message': 'Geçersiz payload'}), 200

        inbound = parse_evolution_inbound(data)
        if inbound is None:
            return jsonify({'success': True, 'message': 'Evolution event ignored'}), 200
        return _handle_whatsapp_welcome_inbound(
            inbound.phone,
            inbound.body,
            inbound.cooldown_key,
            inbound.is_whatsapp_id_format,
            inbound.message_id,
            inbound.remote_jid,
            inbound.remote_jid_alt,
        )

    except Exception as e:
        log_error(logger, E_WA_002, "WhatsApp webhook islenemedi", exc=e)
        return jsonify({'success': False, 'error': str(e)}), 500


def generate_code():
    code = random.randint(100000, 999999)
    return code


def normalize_phone_for_storage(phone):
    """Telefon numarasını storage için normalize et (tutarlı format için)"""
    phone = str(phone).strip()
    
    # WhatsApp ID formatları (@c.us, @lid) - olduğu gibi bırak
    if '@' in phone:
        return phone
    
    # 0 ile başlıyorsa kaldır
    if phone.startswith('0'):
        phone = phone[1:]
    
    # 90 ile başlamıyorsa ve 10 haneli ise ekle
    if not phone.startswith('90') and len(phone) == 10:
        phone = f"90{phone}"
    
    # Sonuç: 90 ile başlayan 12 haneli numara veya WhatsApp ID formatı
    return phone


def customer_phone_for_db(phone):
    """customers.phone — 10 hane (5XXXXXXXXX), DB VARCHAR(10) ile uyumlu."""
    if '@' in str(phone):
        return str(phone).strip()
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith('90') and len(digits) >= 12:
        digits = digits[2:]
    elif digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


_TR_NAME_TO_LOWER = str.maketrans('Iİ', 'ıi')
_TR_NAME_FIRST_UPPER = {'i': 'İ', 'ı': 'I'}


def format_person_name(value):
    """Ad/soyad: her kelimenin ilk harfi büyük, kalanı küçük (Türkçe İ/ı)."""
    if value is None:
        return None
    text = ' '.join(str(value).split())
    if not text:
        return None
    words = []
    for word in text.split(' '):
        lowered = word.translate(_TR_NAME_TO_LOWER).lower()
        first, rest = lowered[:1], lowered[1:]
        first = _TR_NAME_FIRST_UPPER.get(first, first.upper())
        words.append(first + rest)
    return ' '.join(words)


def _customer_phone_lookup_values(phone):
    """Kayıtlı müşteriyi bulmak için denenecek telefon formatları."""
    phone = str(phone).strip()
    db_phone = customer_phone_for_db(phone)
    normalized = normalize_phone_for_storage(phone)
    values = [phone, db_phone, normalized]
    if normalized.startswith('90') and len(normalized) == 12:
        values.append(normalized[2:])
    seen = set()
    ordered = []
    for p in values:
        if p and p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def find_customer_by_phone(cursor, phone):
    """Müşteri kaydını farklı telefon formatlarıyla ara."""
    for p in _customer_phone_lookup_values(phone):
        cursor.execute(
            "SELECT id, name, surname, phone FROM customers WHERE phone = %s",
            (p,),
        )
        row = cursor.fetchone()
        if row:
            return row
    return None


def _time_str_to_minutes(time_str):
    parts = str(time_str)[:5].split(':')
    return int(parts[0]) * 60 + int(parts[1])


def appointment_slot_conflicts(cursor, staff_id, formatted_date, time_str, duration_minutes):
    """Yeni randevu mevcut takvimle (süre dahil) çakışıyor mu?"""
    new_start = _time_str_to_minutes(time_str)
    new_end = new_start + int(duration_minutes or 30)
    cursor.execute("""
        SELECT appointment_time, duration_minutes
        FROM appointments
        WHERE staff_id = %s AND appointment_date = %s AND status != 'cancelled'
    """, (staff_id, formatted_date))
    for appt_time, dur in cursor.fetchall():
        ex_start = _time_str_to_minutes(appt_time)
        ex_end = ex_start + int(dur or 30)
        if new_start < ex_end and ex_start < new_end:
            return True
    return False


def _python_weekday_to_db_day(python_weekday):
    """Python weekday (Mon=0..Sun=6) → DB day_of_week (Sun=0..Sat=6)."""
    return 0 if python_weekday == 6 else python_weekday + 1


PRIVATE_ZONE_DAY_NAMES = [
    'Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'
]

DEFAULT_PRIVATE_ZONE_SETTINGS = {
    'enabled': True,
    'days': [
        {'day_of_week': 2, 'start_time': '14:00', 'end_time': '18:00'},
        {'day_of_week': 4, 'start_time': '14:00', 'end_time': '18:00'},
    ],
}


def get_private_zone_settings():
    """Özel bölge randevu pencereleri (site_settings.json)."""
    site = get_site_settings()
    raw = site.get('private_zone') if isinstance(site.get('private_zone'), dict) else {}
    days_in = raw.get('days') if isinstance(raw.get('days'), list) else []
    days = []
    for item in days_in[:2]:
        if not isinstance(item, dict):
            continue
        try:
            dow = int(item.get('day_of_week', -1))
        except (TypeError, ValueError):
            continue
        if dow < 0 or dow > 6:
            continue
        start_time = str(item.get('start_time') or '14:00')[:5]
        end_time = str(item.get('end_time') or '18:00')[:5]
        if _time_str_to_minutes(start_time) >= _time_str_to_minutes(end_time):
            continue
        days.append({'day_of_week': dow, 'start_time': start_time, 'end_time': end_time})
    if len(days) < 2:
        days = [dict(d) for d in DEFAULT_PRIVATE_ZONE_SETTINGS['days']]
    enabled = raw.get('enabled')
    if enabled is None:
        enabled = DEFAULT_PRIVATE_ZONE_SETTINGS['enabled']
    return {'enabled': bool(enabled), 'days': days}


def save_private_zone_settings(private_zone):
    """Özel bölge ayarlarını site_settings.json içine kaydet."""
    site = get_site_settings()
    site['private_zone'] = private_zone
    save_site_settings(site)
    return True


def resolve_body_region_id(body_region=None, body_area=None):
    region = (body_region or '').strip()
    if region and region in BODY_REGIONS:
        return region
    area = (body_area or '').strip()
    if area:
        for key, meta in BODY_REGIONS.items():
            if meta.get('label') == area:
                return key
    return None


def is_private_body_region(body_region=None, body_area=None):
    region_id = resolve_body_region_id(body_region, body_area)
    if not region_id:
        return False
    return bool(BODY_REGIONS.get(region_id, {}).get('private'))


def get_private_zone_window_for_date(formatted_date, private_zone_settings=None):
    """Özel bölge için o günün izinli saat penceresi; gün uygun değilse None."""
    pz = private_zone_settings or get_private_zone_settings()
    if not pz.get('enabled'):
        return {}
    from datetime import datetime as dt
    date_obj = dt.strptime(formatted_date, '%Y-%m-%d')
    db_day = _python_weekday_to_db_day(date_obj.weekday())
    for day_cfg in pz.get('days') or []:
        if int(day_cfg.get('day_of_week', -1)) == db_day:
            return {
                'start_time': str(day_cfg.get('start_time') or '14:00')[:5],
                'end_time': str(day_cfg.get('end_time') or '18:00')[:5],
            }
    return None


def format_private_zone_schedule_summary(private_zone_settings=None):
    """Müşteriye gösterilecek özet metin."""
    pz = private_zone_settings or get_private_zone_settings()
    if not pz.get('enabled'):
        return ''
    parts = []
    for day_cfg in pz.get('days') or []:
        dow = int(day_cfg.get('day_of_week', 0))
        name = PRIVATE_ZONE_DAY_NAMES[dow] if 0 <= dow <= 6 else '?'
        parts.append(
            f"{name} {day_cfg.get('start_time', '')[:5]}-{day_cfg.get('end_time', '')[:5]}"
        )
    return ', '.join(parts)


def get_private_zone_bookable_dates(days_ahead=14, private_zone_settings=None):
    """Özel bölge talepleri için yalnızca izinli günleri döndürür."""
    pz = private_zone_settings or get_private_zone_settings()
    if not pz.get('enabled'):
        return None
    from datetime import date as dt_date, timedelta
    allowed = {int(d['day_of_week']) for d in (pz.get('days') or [])}
    today = dt_date.today()
    dates = []
    for i in range(days_ahead):
        d = today + timedelta(days=i)
        if _python_weekday_to_db_day(d.weekday()) in allowed:
            dates.append(d.strftime('%d.%m.%Y'))
    return dates


# Müşteri randevu seçimi ve uygun saat üretimi bu adımla gider.
SLOT_STEP_MINUTES = 60


def _ranges_overlap(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


def _generate_half_hour_slots(start_minutes, end_minutes, step=None):
    """start_minutes dahil, end_minutes hariç slot listesi (varsayılan 60 dk)."""
    step = int(step or SLOT_STEP_MINUTES)
    slots = []
    current = int(start_minutes)
    end_m = int(end_minutes)
    while current < end_m:
        slots.append(_time_str_from_minutes(current))
        current += step
    return slots


def _staff_has_working_hours(cursor, staff_id):
    cursor.execute(
        'SELECT 1 FROM working_hours WHERE staff_id = %s LIMIT 1',
        (staff_id,),
    )
    return cursor.fetchone() is not None


def _slots_from_working_hour_row(wh_start, wh_end):
    start_total_minutes = wh_start.hour * 60 + wh_start.minute
    if wh_end.hour == 0 and wh_end.minute == 0:
        end_total_minutes = 24 * 60
    else:
        end_total_minutes = wh_end.hour * 60 + wh_end.minute
    return _generate_half_hour_slots(start_total_minutes, end_total_minutes)


def compute_available_start_slots(
    cursor, staff_id, formatted_date, duration_minutes,
    body_region=None, body_area=None, return_details=False,
    skip_past_filter=False,
    past_filter_mode='buffer',
):
    """Belirli gün/personel için uygun başlangıç saatlerini döndürür."""
    from datetime import datetime as dt

    date_obj = dt.strptime(formatted_date, '%Y-%m-%d')
    day_of_week = date_obj.weekday()
    db_day = 0 if day_of_week == 6 else day_of_week + 1

    cursor.execute("""
        SELECT start_time, end_time, is_available FROM working_hours
        WHERE staff_id = %s AND day_of_week = %s
    """, (staff_id, db_day))
    working_hour = cursor.fetchone()
    available_slots = []
    is_day_closed = False

    if working_hour:
        wh_start, wh_end, is_available = working_hour
        available_slots = _slots_from_working_hour_row(wh_start, wh_end)
        if not is_available:
            is_day_closed = True
    elif _staff_has_working_hours(cursor, staff_id):
        # Sanatçı saatlerini kaydetmiş ama bu gün için satır yok → kapalı
        available_slots = []
        is_day_closed = True
    else:
        # Hiç çalışma saati tanımlanmamış → admin panel varsayılanı (10:00–20:00)
        available_slots = _generate_half_hour_slots(10 * 60, 20 * 60)

    busy_intervals = []
    cursor.execute("""
        SELECT appointment_time, duration_minutes
        FROM appointments
        WHERE staff_id = %s AND appointment_date = %s AND status != 'cancelled'
    """, (staff_id, formatted_date))
    for appt_time, dur in cursor.fetchall():
        appt_start = _time_str_to_minutes(str(appt_time)[:5])
        busy_intervals.append((appt_start, appt_start + int(dur or SLOT_STEP_MINUTES)))

    cursor.execute("""
        SELECT start_time, end_time FROM time_off
        WHERE staff_id = %s AND off_date = %s
    """, (staff_id, formatted_date))
    for start_time, end_time in cursor.fetchall():
        if start_time is None:
            busy_intervals.append((0, 24 * 60))
        else:
            start_m = _time_str_to_minutes(str(start_time)[:5])
            end_str = str(end_time)[:5] if end_time else "00:00"
            end_m = 24 * 60 if end_str in ("00:00", "24:00") else _time_str_to_minutes(end_str)
            if end_m <= start_m:
                end_m = 24 * 60
            busy_intervals.append((start_m, end_m))

    if is_day_closed:
        busy_intervals.append((0, 24 * 60))

    booked = []
    for t in available_slots:
        slot_start = _time_str_to_minutes(t)
        slot_end = slot_start + SLOT_STEP_MINUTES
        if any(_ranges_overlap(slot_start, slot_end, b0, b1) for b0, b1 in busy_intervals):
            booked.append(t)

    req = int(duration_minutes or SLOT_STEP_MINUTES)
    if req < SLOT_STEP_MINUTES:
        req = SLOT_STEP_MINUTES
    if req % 30 != 0:
        req = ((req // 30) + 1) * 30
    booked_set = set(booked)
    work_end_m = (
        _time_str_to_minutes(available_slots[-1]) + SLOT_STEP_MINUTES
        if available_slots else 0
    )
    starts = []
    for start in available_slots:
        start_m = _time_str_to_minutes(start)
        end_m = start_m + req
        if end_m > work_end_m:
            continue
        if any(_ranges_overlap(start_m, end_m, b0, b1) for b0, b1 in busy_intervals):
            continue
        starts.append(start)

    # Bugünse geçmiş başlangıç saatlerini çıkar
    from datetime import date as dt_date
    if not skip_past_filter and formatted_date == dt_date.today().isoformat():
        now = datetime.now()
        now_mins = now.hour * 60 + now.minute
        if past_filter_mode == 'strict':
            cutoff = now_mins
        else:
            cutoff = now_mins + SLOT_STEP_MINUTES
        starts = [s for s in starts if _time_str_to_minutes(s) > cutoff]

    # Özel bölge: yalnızca yapılandırılmış gün/saat pencerelerinde randevu
    if is_private_body_region(body_region, body_area):
        pz = get_private_zone_settings()
        if pz.get('enabled'):
            window = get_private_zone_window_for_date(formatted_date, pz)
            if not window:
                starts = []
                available_slots = []
                booked_set = set()
            else:
                win_start_m = _time_str_to_minutes(window['start_time'])
                win_end_m = _time_str_to_minutes(window['end_time'])
                available_slots = [
                    t for t in available_slots
                    if win_start_m <= _time_str_to_minutes(t) < win_end_m
                ]
                booked_set = set()
                for t in available_slots:
                    slot_start = _time_str_to_minutes(t)
                    slot_end = slot_start + SLOT_STEP_MINUTES
                    if any(_ranges_overlap(slot_start, slot_end, b0, b1) for b0, b1 in busy_intervals):
                        booked_set.add(t)
                starts = []
                for start in available_slots:
                    start_m = _time_str_to_minutes(start)
                    end_m = start_m + req
                    if end_m > win_end_m:
                        continue
                    if any(_ranges_overlap(start_m, end_m, b0, b1) for b0, b1 in busy_intervals):
                        continue
                    starts.append(start)

    if return_details:
        work_start = available_slots[0] if available_slots else None
        work_end = available_slots[-1] if available_slots else None
        return {
            'available_start_slots': starts,
            'all_slots': available_slots,
            'booked_slots': sorted(booked_set),
            'is_day_closed': is_day_closed,
            'work_start': work_start,
            'work_end': work_end,
        }

    return starts, is_day_closed


def _minutes_from_time_value(t):
    s = str(t)[:5]
    parts = s.split(':')
    return int(parts[0]) * 60 + int(parts[1])


def _time_str_from_minutes(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _range_from_working_hour_rows(rows):
    """Açık günlerin birleşik min/max dakika aralığı."""
    min_m = None
    max_m = None
    for start_time, end_time, is_available in rows:
        if is_available is False:
            continue
        st = _minutes_from_time_value(start_time or '09:00')
        end_raw = str(end_time)[:5] if end_time else '20:00'
        if end_raw in ('00:00', '24:00'):
            en = 24 * 60
        else:
            en = _minutes_from_time_value(end_time)
        if en <= st:
            en = 24 * 60
        min_m = st if min_m is None else min(min_m, st)
        max_m = en if max_m is None else max(max_m, en)
    return min_m, max_m


def _build_half_hour_time_labels(start_m, end_m):
    labels = []
    m = int(start_m)
    end_m = int(end_m)
    while m < end_m:
        labels.append(_time_str_from_minutes(m))
        m += 30
    return labels


@app.route('/api/admin/schedule-grid-times', methods=['GET'])
@limiter.exempt
@token_required
def admin_schedule_grid_times():
    """Admin takvim tablosu için sabit saat sütunları (tüm çalışma günleri birleşimi)."""
    staff_id = request.args.get('staff_id', type=int)

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        staff_ids = []
        if staff_id:
            if not is_studio_admin() and int(staff_id) != int(request.staff_id):
                cursor.close()
                return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
            staff_ids = [int(staff_id)]
        elif is_studio_admin():
            cursor.execute("SELECT id FROM artists ORDER BY id")
            staff_ids = [r[0] for r in cursor.fetchall()]
        else:
            staff_ids = [int(request.staff_id)]

        # Admin takvim tablosu: sabit 09:00–24:00 (çalışma saati DB kaydı grid'i daraltmaz)
        min_m = 9 * 60
        max_m = 24 * 60

        times = _build_half_hour_time_labels(min_m, max_m)
        cursor.close()

        return jsonify({
            'success': True,
            'times': times,
            'start_time': _time_str_from_minutes(min_m),
            'end_time': _time_str_from_minutes(max_m),
        })
    except Exception as e:
        logger.error(f"admin_schedule_grid_times hatası: {e}")
        return jsonify({'success': False, 'message': 'Saatler alınamadı'}), 500
    finally:
        release_db_connection(conn)


def is_wapio_demo_mode():
    """Şimdilik sabit OTP 123456 — WhatsApp doğrulaması atlanır."""
    return True


def verify_phone_code_from_db(phone, code):
    """DB'deki doğrulama kodunu kontrol et; başarılıysa kodu siler."""
    phone = str(phone).strip()
    normalized_phone = normalize_phone_for_storage(phone)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT code, expires_at FROM verification_codes
            WHERE phone = %s AND expires_at > NOW()
            ORDER BY created_at DESC LIMIT 1
            FOR UPDATE SKIP LOCKED
        """, (phone,))
        row = cursor.fetchone()
        if not row and normalized_phone != phone:
            cursor.execute("""
                SELECT code, expires_at FROM verification_codes
                WHERE phone = %s AND expires_at > NOW()
                ORDER BY created_at DESC LIMIT 1
                FOR UPDATE SKIP LOCKED
            """, (normalized_phone,))
            row = cursor.fetchone()
        if not row:
            return False, 'Doğrulama kodu bulunamadı. Lütfen kod isteyiniz', 404
        stored_code, expires_at = row
        if str(stored_code) != str(code).strip():
            return False, 'Doğrulama kodu yanlış', 401
        if datetime.now() > expires_at:
            cursor.execute(
                "DELETE FROM verification_codes WHERE phone IN (%s, %s) AND expires_at <= NOW()",
                (phone, normalized_phone),
            )
            conn.commit()
            return False, 'Doğrulama kodu süresi dolmuş', 401
        cursor.execute(
            "DELETE FROM verification_codes WHERE phone IN (%s, %s) AND code = %s",
            (phone, normalized_phone, str(code).strip()),
        )
        conn.commit()
        cursor.close()
        return True, 'Doğrulama başarılı', 200
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"verify_phone_code_from_db hatası: {e}")
        return False, 'Doğrulama hatası', 500
    finally:
        release_db_connection(conn)


def format_verification_whatsapp_message(code):
    return build_verification_code_message(code)


def send_whatsapp_code(phone):
    """Evolution API ile doğrulama kodu gönder."""
    code = generate_code()
    message = format_verification_whatsapp_message(code)

    original_phone = str(phone).strip()
    evo_cfg = get_evolution_config()
    configured = bool((evo_cfg.get('api_key') or '').strip() and (evo_cfg.get('instance_name') or '').strip())

    message_sent = False
    if not configured:
        log_warning(logger, E_WA_003, "Evolution yapilandirmasi eksik, kod terminale yazildi", phone=original_phone)
        print(f"\n{'='*50}\nDOGRULAMA KODU (TEST MODU)\nTelefon: {original_phone}\nKod: {code}\n{'='*50}\n")
    else:
        message_sent = send_wapio_message(original_phone, message)

    if message_sent:
        logger.info("Dogrulama kodu WhatsApp ile gonderildi | phone=%s", original_phone)
    elif configured:
        log_error(logger, E_WA_004, "Dogrulama kodu WhatsApp ile gonderilemedi", phone=original_phone)
    
    # Database tabanlı kod kaydetme (mesaj gönderilse de gönderilmese de)
    # Worker'lar arasında paylaşımlı olması için database'e kaydet
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Expire zamanını hesapla
        expires_at = datetime.now() + timedelta(seconds=CODE_EXPIRATION_SECONDS)
        
        # Frontend'den gelen orijinal formatı kaydet
        cursor.execute("""
            INSERT INTO verification_codes (phone, code, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (original_phone, str(code), expires_at))
        
        # Normalize formatı da kaydet (normal numaralar için)
        if '@' not in original_phone:  # WhatsApp ID formatı değilse
            normalized_phone = normalize_phone_for_storage(original_phone)
            if normalized_phone != original_phone:
                cursor.execute("""
                    INSERT INTO verification_codes (phone, code, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (normalized_phone, str(code), expires_at))
                logger.debug(f"Kod hem orijinal ({original_phone}) hem normalize ({normalized_phone}) formatında kaydedildi")
        
        conn.commit()
        cursor.close()
        logger.debug(f"Verification code kaydedildi (database): {original_phone}")
    except Exception as e:
        logger.error(f"Verification code kaydetme hatası: {e}")
        if conn:
            conn.rollback()
            cursor.close()
    finally:
        release_db_connection(conn)
    
    # İstatistik kaydet (monitoring için)
    current_time = time.time()
    with verification_stats_lock:
        verification_stats.append({
            'timestamp': current_time,
            'success': message_sent
        })
        # Eski kayıtları temizle (10 dakikadan eski)
        cutoff_time = current_time - VERIFICATION_STATS_MAX_AGE
        verification_stats[:] = [stat for stat in verification_stats if stat['timestamp'] > cutoff_time]
    
    return (message_sent, code)

# Doğrulama kodu gönder
@app.route('/api/send-code', methods=['POST'])
@limiter.limit("5 per minute")  # Dakikada max 5 kod
def send_code():
    # Input validation
    schema = SendCodeSchema()
    try:
        data = schema.load(request.get_json())
    except ValidationError as err:
        logger.warning(f"Validation error in send_code: {err.messages}")
        return jsonify({
            'success': False, 
            'message': 'Geçersiz telefon numarası',
            'errors': err.messages
        }), 400
    except TypeError:
        return jsonify({'success': False, 'message': 'Geçersiz JSON formatı'}), 400
    except Exception as e:
        logger.error(f"Unexpected error in send_code validation: {e}")
        return jsonify({'success': False, 'message': ERROR_MESSAGES['validation']}), 400

    phone = data['phone']  # Validated: 10 haneli

    try:
        if is_wapio_demo_mode():
            demo_code = "123456"
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                expires_at = datetime.now() + timedelta(seconds=CODE_EXPIRATION_SECONDS)
                original_phone = str(phone).strip()
                normalized_phone = normalize_phone_for_storage(original_phone)
                cursor.execute(
                    "INSERT INTO verification_codes (phone, code, expires_at) VALUES (%s, %s, %s)",
                    (original_phone, demo_code, expires_at),
                )
                if normalized_phone != original_phone:
                    cursor.execute(
                        "INSERT INTO verification_codes (phone, code, expires_at) VALUES (%s, %s, %s)",
                        (normalized_phone, demo_code, expires_at),
                    )
                conn.commit()
                cursor.close()
            except Exception as e:
                logger.warning(f"Demo verification code insert failed: {e}")
                if conn:
                    conn.rollback()
            finally:
                release_db_connection(conn)
            logger.info(f"DEMO doğrulama kodu: {phone} -> {demo_code}")
            return jsonify({'success': True, 'message': 'Demo doğrulama kodu: 123456'})

        message_sent, _code = send_whatsapp_code(phone)
        if not message_sent:
            return jsonify({
                'success': False,
                'message': 'WhatsApp doğrulama kodu gönderilemedi. WhatsApp API bağlantısını kontrol edin.',
            }), 503
        return jsonify({'success': True, 'message': 'Doğrulama kodu WhatsApp ile gönderildi'})
    except Exception as e:
        log_error(logger, E_WA_004, "Dogrulama kodu gonderilirken hata", exc=e)
        return jsonify({
            'success': False,
            'message': 'Kod gönderilirken bir hata oluştu'
        }), 500


@app.route('/api/verify-code', methods=['POST'])
@limiter.limit("10 per minute")  # Dakikada max 10 deneme
def verify_code():
    data = request.get_json()
    phone = data.get('phone')
    code = data.get('code')
    
    if not phone or not code:
        return jsonify({'success': False, 'message': 'Telefon numarası ve doğrulama kodu gereklidir'}), 400

    phone = str(phone).strip()
    normalized_phone = normalize_phone_for_storage(phone)

    if is_wapio_demo_mode():
        if str(code).strip() != "123456":
            return jsonify({'success': False, 'message': 'Demo doğrulama kodu yanlış (123456 olmalı)'}), 401
    else:
        ok, msg, status = verify_phone_code_from_db(phone, code)
        if not ok:
            return jsonify({'success': False, 'message': msg}), status

    # Müşteri var mı kontrol et
    conn = None
    conn_bad = False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        customer = find_customer_by_phone(cursor, phone)
        cursor.close()
        
        if customer:
            # Mevcut müşteri - bilgilerini döndür
            return jsonify({
                'success': True, 
                'message': 'Doğrulama başarılı',
                'is_new_customer': False,
                'customer': {
                    'id': customer[0],
                    'name': customer[1],
                    'surname': customer[2]
                }
            })
        else:
            # Yeni müşteri
            return jsonify({
                'success': True, 
                'message': 'Doğrulama başarılı',
                'is_new_customer': True
            })
    except Exception as e:
        conn_bad = True
        logger.error(f"verify_code hatası: {e}")
        return jsonify({'success': False, 'message': ERROR_MESSAGES['database']}), 503
    finally:
        release_db_connection(conn, close=conn_bad)

@app.route('/api/register-customer', methods=['POST'])
@limiter.limit("3 per minute")  # Dakikada max 3 kayıt
def register_customer():
    data = request.get_json(silent=True) or {}
    phone = data.get('phone')
    name = data.get('name')
    surname = data.get('surname')

    # Tattoo flow: phone verification only, name/surname optional
    if not phone:
        return jsonify({'success': False, 'message': 'Telefon numarası gereklidir'}), 400

    phone = customer_phone_for_db(str(phone).strip())
    if len(phone) != 10:
        return jsonify({'success': False, 'message': 'Geçerli 10 haneli telefon girin'}), 400
    name = format_person_name(name)
    surname = format_person_name(surname)

    conn = None
    conn_bad = False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        existing = find_customer_by_phone(cursor, phone)
        if existing:
            cursor.execute("""
                UPDATE customers SET
                  name = COALESCE(%s, name),
                  surname = COALESCE(%s, surname)
                WHERE id = %s
                RETURNING id, phone, name, surname
            """, (name, surname, existing[0]))
        else:
            cursor.execute("""
                INSERT INTO customers (phone, name, surname)
                VALUES (%s, %s, %s)
                RETURNING id, phone, name, surname
            """, (phone, name, surname))
        row = cursor.fetchone()
        conn.commit()
        cursor.close()
        logger.info(f"Müşteri kaydedildi/güncellendi: {phone}")
        return jsonify({
            'success': True,
            'message': 'Müşteri kaydı başarılı',
            'customer': {
                'id': row[0],
                'phone': row[1],
                'name': row[2],
                'surname': row[3]
            } if row else None
        })
    except Exception as e:
        conn_bad = True
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"register_customer hatası: {e}")
        return jsonify({'success': False, 'message': ERROR_MESSAGES['database']}), 500
    finally:
        release_db_connection(conn, close=conn_bad)

def normalize_instagram_url(raw_value):
    """Kullanıcı adı, @handle veya Instagram URL → https://www.instagram.com/username/"""
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None

    value = value.rstrip('/')
    if value.startswith('@'):
        value = value[1:].strip()

    username = None
    if value.startswith('http://') or value.startswith('https://'):
        parsed = urlparse(value)
        host = (parsed.netloc or '').lower().lstrip('www.')
        if host != 'instagram.com':
            return None
        parts = [p for p in (parsed.path or '').split('/') if p]
        if not parts:
            return None
        username = parts[0]
    elif 'instagram.com' in value:
        parsed = urlparse('https://' + value.lstrip('/'))
        host = (parsed.netloc or '').lower().lstrip('www.')
        if host != 'instagram.com':
            return None
        parts = [p for p in (parsed.path or '').split('/') if p]
        if not parts:
            return None
        username = parts[0]
    else:
        username = value.split('/')[0].split('?')[0].strip()

    if not username or not re.match(r'^[a-zA-Z0-9._]{1,30}$', username):
        return None

    return f'https://www.instagram.com/{username}/'


def ensure_artist_instagram_column():
    """Mevcut kurulumlarda artists.instagram_url kolonunu oluşturur."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'artists'
              AND column_name = 'instagram_url'
            """
        )
        if not cursor.fetchone():
            cursor.execute('ALTER TABLE artists ADD COLUMN instagram_url VARCHAR(255)')
            conn.commit()
            logger.info('artists.instagram_url kolonu eklendi')
        cursor.close()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.warning('ensure_artist_instagram_column: %s', e)
    finally:
        release_db_connection(conn)


@app.route('/api/barbers', methods=['GET'])  # backward compatible
@app.route('/api/artists', methods=['GET'])
def get_artists():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, profile_photo, phone, instagram_url
            FROM artists
            WHERE role IS DISTINCT FROM 'tech_support'
            ORDER BY display_order ASC, id ASC
            """
        )
        barbers = cursor.fetchall()
        cursor.close()
        
        barber_list = []
        for satir in barbers:
            berber = {
                "id": satir[0],
                "name": satir[1],
                "profile_photo": satir[2],
                "phone": satir[3],
                "instagram_url": satir[4] or '',
            }
            barber_list.append(berber)

        return jsonify(barber_list)
    except Exception as e:
        logger.error(f"get_artists hatası: {e}")
        return jsonify({"success": False, "message": "Bir problem oluştu"}), 500
    finally:
        release_db_connection(conn)

@app.route('/api/services', methods=['GET'])
def get_services():
    return jsonify({
        "success": False,
        "message": "Bu sistemde hizmet seçimi kaldırıldı. Dövme talebi akışını kullanın."
    }), 410

@app.route('/api/create-appointment', methods=['POST'])
@limiter.limit("10 per minute")  # Dakikada max 10 randevu
def create_appointment():
    return jsonify({
        "success": False,
        "message": "Randevu oluşturma akışı değişti. Önce dövme talebi oluşturulur, sonra admin süre belirleyip link gönderir; müşteri linkten slot seçince randevu oluşur."
    }), 410


@app.route('/api/booked-times', methods=['GET'])
def get_booked_times():
    staff_id = request.args.get('staff_id')
    date_str = request.args.get('date')  # Format: "16.12.2025"
    duration_minutes = request.args.get('duration_minutes', type=int)  # Dakika cinsinden (opsiyonel)
    
    logger.info(
        "get_booked_times | staff_id=%s date=%s duration=%s",
        staff_id,
        date_str,
        duration_minutes,
    )
    
    if not staff_id or not date_str:
        return jsonify({"success": False, "message": "staff_id ve date gerekli"}), 400
    
    # Tarih formatını dönüştür
    day, month, year = date_str.split('.')
    formatted_date = f"{year}-{month}-{day}"
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        slot_details = compute_available_start_slots(
            cursor, int(staff_id), formatted_date, duration_minutes, return_details=True
        )
        available_slots = slot_details['all_slots']
        booked_times = slot_details['booked_slots']
        available_start_slots = slot_details['available_start_slots']

        logger.info(
            "get_booked_times slots | available=%s booked=%s start_slots=%s",
            len(available_slots or []),
            len(booked_times or []),
            len(available_start_slots or []),
        )

        cursor.close()

        return jsonify({
            "success": True,
            "available_slots": available_slots,
            "booked_times": booked_times,
            "available_start_slots": available_start_slots
        })
    except Exception as e:
        logger.error(f"get_booked_times hatası: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": "Bir problem oluştu"}), 500
    finally:
        release_db_connection(conn)


# =============================================
# TATTOO CONFIG (body region — no auto pricing)
# =============================================

BODY_REGIONS = {
    'head': {'label': 'Baş / ense'},
    'neck': {'label': 'Boyun'},
    'chest': {'label': 'Göğüs', 'private': True},
    'ribs': {'label': 'Kaburga', 'private': True},
    'stomach': {'label': 'Karın', 'private': True},
    'back_upper': {'label': 'Üst sırt'},
    'back_lower': {'label': 'Alt sırt / bel', 'private': True},
    'shoulder': {'label': 'Omuz'},
    'upper_arm': {'label': 'Üst kol'},
    'forearm': {'label': 'Ön kol'},
    'wrist': {'label': 'Bilek'},
    'hand': {'label': 'El / parmak'},
    'thigh': {'label': 'Uyluk', 'private': True},
    'knee': {'label': 'Diz'},
    'calf': {'label': 'Baldır'},
    'ankle': {'label': 'Ayak bileği'},
    'foot': {'label': 'Ayak üstü'},
}


@app.route('/api/tattoo-config', methods=['GET'])
def get_tattoo_config():
    """Vücut bölgesi ve özel bölge randevu penceresi meta verisi."""
    pz = get_private_zone_settings()
    schedule_summary = format_private_zone_schedule_summary(pz)
    return jsonify({
        'success': True,
        'regions': [
            {
                'id': k,
                'label': v['label'],
                'private': bool(v.get('private')),
            }
            for k, v in BODY_REGIONS.items()
        ],
        'private_zone': {
            'enabled': bool(pz.get('enabled')),
            'schedule_summary': schedule_summary,
            'days': pz.get('days') or [],
            'day_names': PRIVATE_ZONE_DAY_NAMES,
        },
    })


# =============================================
# TATTOO REQUEST REFERENCE NUMBER (RN2323)
# =============================================

def generate_tattoo_reference_number(cursor, max_attempts=30):
    """Benzersiz kısa referans: RN + 4 rakam (örn. RN2323)."""
    for _ in range(max_attempts):
        ref = f"RN{random.randint(1000, 9999)}"
        cursor.execute(
            "SELECT 1 FROM tattoo_requests WHERE reference_number = %s LIMIT 1",
            (ref,)
        )
        if not cursor.fetchone():
            return ref
    raise RuntimeError("Referans numarası üretilemedi")


# =============================================
# TATTOO REQUEST FLOW (CUSTOMER)
# =============================================

@app.route('/api/loyalty/validate-code', methods=['POST'])
@limiter.limit("20 per minute")
def validate_loyalty_code():
    """Randevu talebi öncesi indirim kodu doğrulama (telefon + kod)."""
    data = request.get_json() or {}
    phone = (data.get('phone') or '').strip()
    code = (data.get('loyalty_code') or '').strip()
    if not phone or not code:
        return jsonify({'success': False, 'message': 'Telefon ve indirim kodu gerekli'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        phone_stored = customer_phone_for_db(phone)
        existing = find_customer_by_phone(cursor, phone_stored)
        if not existing:
            cursor.close()
            return jsonify({'success': False, 'message': 'Önce telefon doğrulaması yapın'}), 404
        info = validate_loyalty_code_for_customer(cursor, existing[0], code)
        cursor.close()
        return jsonify({'success': True, 'loyalty_discount': info})
    except LoyaltyCodeError as loyalty_err:
        return jsonify({'success': False, 'message': str(loyalty_err)}), 400
    except Exception as e:
        logger.error(f"validate_loyalty_code hatası: {e}")
        return jsonify({'success': False, 'message': 'Kod doğrulanamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/tattoo-requests', methods=['POST'])
@limiter.limit("10 per minute")
def create_tattoo_request():
    data = request.get_json() or {}

    phone = (data.get('phone') or '').strip()
    staff_id = data.get('staff_id')
    size = (data.get('size') or '').strip()
    body_area = (data.get('body_area') or '').strip()
    body_region = (data.get('body_region') or '').strip()
    description = (data.get('description') or '').strip()
    reference_image = (data.get('reference_image') or '').strip()

    config_undecided = data.get('config_undecided') in (True, 'true', 1, '1')
    pre_consultation = data.get('pre_consultation') in (True, 'true', 1, '1')

    if not phone or not staff_id:
        return jsonify({'success': False, 'message': 'phone ve staff_id gerekli'}), 400

    if config_undecided or pre_consultation:
        if pre_consultation:
            style_label = 'Ön görüşme'
            body_area = body_area or 'Ön görüşme'
            description = description or 'Müşteri ön görüşme talep ediyor.'
        else:
            style_label = 'Karar verilmedi'
            body_area = body_area or 'Henüz belirlenmedi'
        size = size or None
    else:
        if body_region and body_region in BODY_REGIONS:
            body_area = BODY_REGIONS[body_region]['label']
        elif not body_area:
            return jsonify({'success': False, 'message': 'Vücut bölgesi seçin'}), 400

        if not size:
            return jsonify({'success': False, 'message': 'Lütfen dövme büyüklüğünü seçin'}), 400

        style_label = None

    estimated_price = None

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT name, phone FROM artists WHERE id = %s', (staff_id,))
        staff_row = cursor.fetchone()
        if not staff_row:
            cursor.close()
            return jsonify({'success': False, 'message': 'Sanatçı bulunamadı'}), 404

        staff_name, staff_phone = staff_row[0], staff_row[1]

        # Ensure customer exists (phone verified earlier in UI)
        phone_stored = customer_phone_for_db(phone)
        existing = find_customer_by_phone(cursor, phone_stored)
        customer_name = None
        if existing:
            customer_id = existing[0]
            customer_name = ' '.join(filter(None, [existing[1], existing[2]])).strip() or None
        else:
            cursor.execute(
                "INSERT INTO customers (phone, name, surname) VALUES (%s, %s, %s) RETURNING id",
                (phone_stored, None, None)
            )
            customer_id = cursor.fetchone()[0]

        reference_number = generate_tattoo_reference_number(cursor)

        stored_body_region = None
        if body_region and body_region in BODY_REGIONS:
            stored_body_region = body_region
        elif body_area:
            stored_body_region = resolve_body_region_id(body_area=body_area)

        cursor.execute("""
            INSERT INTO tattoo_requests (
                customer_id, staff_id, size, body_area, body_region, tattoo_style, estimated_price,
                reference_number, description, reference_image, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new')
            RETURNING id
        """, (
            customer_id, staff_id, size or None, body_area or None, stored_body_region,
            style_label, estimated_price, reference_number, description or None, reference_image or None
        ))

        request_id = cursor.fetchone()[0]

        loyalty_code = (data.get('loyalty_code') or '').strip()
        loyalty_attached = None
        if loyalty_code:
            try:
                _, code, discount_pct = attach_loyalty_code_to_request(
                    cursor, customer_id, request_id, loyalty_code
                )
                loyalty_attached = {
                    'code': code,
                    'discount_percent': discount_pct,
                }
            except LoyaltyCodeError as loyalty_err:
                conn.rollback()
                cursor.close()
                return jsonify({'success': False, 'message': str(loyalty_err)}), 400

        conn.commit()
        cursor.close()

        private_zone = is_private_body_region(stored_body_region, body_area)
        try:
            wa_msg = build_tattoo_request_received_message(
                reference_number,
                staff_name,
                body_area=body_area or None,
                size=size or None,
                style_label=style_label,
                pre_consultation=pre_consultation,
                config_undecided=config_undecided,
                loyalty_attached=loyalty_attached,
            )
            if send_wapio_message(phone_stored, wa_msg):
                logger.info(f"Talep alındı WhatsApp mesajı gönderildi: {phone_stored} — {reference_number}")
            else:
                logger.warning(f"Talep alındı WhatsApp mesajı gönderilemedi: {phone_stored}")
        except Exception as wa_err:
            logger.warning(f"Talep alındı WhatsApp bildirimi atlandı: {wa_err}")

        if staff_phone:
            try:
                staff_msg = build_tattoo_request_staff_message(
                    reference_number,
                    phone_stored,
                    customer_name=customer_name,
                    body_area=body_area or None,
                    size=size or None,
                    style_label=style_label,
                    description=description or None,
                    pre_consultation=pre_consultation,
                    config_undecided=config_undecided,
                    loyalty_attached=loyalty_attached,
                    private_zone=private_zone,
                    has_reference_image=bool(reference_image),
                )
                if send_wapio_message(staff_phone, staff_msg):
                    logger.info(f"Sanatçı talep bildirimi gönderildi: {staff_phone} — {reference_number}")
                else:
                    logger.warning(f"Sanatçı talep bildirimi gönderilemedi: {staff_phone}")
            except Exception as staff_wa_err:
                logger.warning(f"Sanatçı talep WhatsApp bildirimi atlandı: {staff_wa_err}")

        base_message = (
            f'Talebiniz alındı. Referans numaranız: {reference_number}. '
            'Sanatçı inceleyip süre belirledikten sonra size seçim linki gönderilecek.'
        )
        if loyalty_attached:
            base_message += (
                f" Sadakat indirim kodunuz ({loyalty_attached['code']}) talebe eklendi; "
                f"teklif fiyatınıza %{loyalty_attached['discount_percent']} indirim uygulanacak."
            )

        return jsonify({
            'success': True,
            'tattoo_request_id': request_id,
            'reference_number': reference_number,
            'loyalty_discount': loyalty_attached,
            'message': base_message,
        })
    except Exception as e:
        if conn:
            conn.rollback()
        log_error(logger, E_REQ_001, "Dovme talebi olusturulamadi", exc=e)
        return jsonify({'success': False, 'message': ERROR_MESSAGES.get('database', 'Bir problem oluştu')}), 500
    finally:
        release_db_connection(conn)


# =============================================
# TOKENIZED SLOT OFFER FLOW (CUSTOMER)
# =============================================

@app.route('/api/offers/<token>', methods=['GET'])
def get_offer(token):
    """Return offer metadata and, optionally, available start slots for a given date."""
    token = (token or '').strip()
    date_str = request.args.get('date')  # optional: "16.12.2025"

    if not token:
        return jsonify({'success': False, 'message': 'token gerekli'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                so.id,
                so.duration_minutes,
                so.expires_at,
                so.used_at,
                so.price,
                so.original_price,
                so.discount_percent,
                tr.id,
                tr.staff_id,
                tr.size,
                tr.body_area,
                tr.body_region,
                tr.tattoo_style,
                tr.estimated_price,
                tr.description,
                tr.reference_image,
                c.phone,
                s.name,
                lr.redemption_code
            FROM slot_offers so
            JOIN tattoo_requests tr ON so.tattoo_request_id = tr.id
            JOIN customers c ON tr.customer_id = c.id
            JOIN artists s ON tr.staff_id = s.id
            LEFT JOIN loyalty_redemptions lr ON tr.loyalty_redemption_id = lr.id
            WHERE so.token = %s
        """, (token,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return jsonify({'success': False, 'message': 'Link geçersiz'}), 404

        (offer_id, duration_minutes, expires_at, used_at, offer_price,
         original_price, discount_percent, tr_id, staff_id,
         size, body_area, body_region, tattoo_style, estimated_price_req, desc, ref_img,
         customer_phone, staff_name, loyalty_code) = row

        is_private = is_private_body_region(body_region, body_area)
        pz = get_private_zone_settings()

        if used_at is not None:
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu link daha önce kullanılmış'}), 410

        if expires_at and expires_at < datetime.utcnow():
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu linkin süresi dolmuş'}), 410

        offer_payload = {
            'token': token,
            'duration_minutes': int(duration_minutes),
            'price': float(offer_price or 0),
            'expires_at': expires_at.isoformat() if expires_at else None,
        }
        if original_price and discount_percent:
            offer_payload['original_price'] = float(original_price)
            offer_payload['discount_percent'] = int(discount_percent)
            if loyalty_code:
                offer_payload['loyalty_code'] = loyalty_code

        payload = {
            'success': True,
            'offer': offer_payload,
            'tattoo_request': {
                'id': tr_id,
                'staff': {'id': staff_id, 'name': staff_name},
                'size': size,
                'body_area': body_area,
                'body_region': body_region,
                'tattoo_style': tattoo_style,
                'estimated_price': float(estimated_price_req) if estimated_price_req is not None else None,
                'description': desc,
                'reference_image': ref_img,
                'is_private_zone': is_private,
            },
            'private_zone': {
                'active': is_private and bool(pz.get('enabled')),
                'schedule_summary': format_private_zone_schedule_summary(pz) if is_private else '',
            },
        }

        # If a date is provided, return available start slots for that date
        if date_str:
            day, month, year = date_str.split('.')
            formatted_date = f"{year}-{month}-{day}"

            slot_details = compute_available_start_slots(
                cursor, staff_id, formatted_date, duration_minutes,
                body_region=body_region, body_area=body_area, return_details=True
            )
            payload['slots'] = {
                'date': date_str,
                'available_start_slots': slot_details['available_start_slots'],
                'all_slots': slot_details['all_slots'],
                'booked_slots': slot_details['booked_slots'],
            }
        else:
            private_dates = get_private_zone_bookable_dates(days_ahead=14) if is_private else None
            if private_dates is not None:
                payload['dates'] = private_dates
            else:
                from datetime import date as dt_date
                today = dt_date.today()
                payload['dates'] = [
                    (today + timedelta(days=i)).strftime('%d.%m.%Y')
                    for i in range(14)
                ]

        cursor.close()
        return jsonify(payload)
    except Exception as e:
        logger.error(f"get_offer hatası: {e}")
        return jsonify({'success': False, 'message': 'Bir problem oluştu'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/offers/<token>/choose-slot', methods=['POST'])
@limiter.limit("20 per minute")
def choose_offer_slot(token):
    token = (token or '').strip()
    data = request.get_json() or {}
    date_str = data.get('date')  # "16.12.2025"
    time_str = data.get('time')  # "13:00"

    if not token or not date_str or not time_str:
        return jsonify({'success': False, 'message': 'token, date, time gerekli'}), 400

    # Normalize date
    day, month, year = date_str.split('.')
    formatted_date = f"{year}-{month}-{day}"

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Lock offer row to prevent double use
        cursor.execute("""
            SELECT
                so.id,
                so.duration_minutes,
                so.expires_at,
                so.used_at,
                so.price,
                tr.id,
                tr.customer_id,
                tr.staff_id,
                tr.body_area,
                tr.body_region,
                tr.size,
                tr.tattoo_style,
                tr.reference_number,
                tr.description,
                c.phone,
                c.name,
                c.surname,
                s.name,
                s.phone
            FROM slot_offers so
            JOIN tattoo_requests tr ON so.tattoo_request_id = tr.id
            JOIN customers c ON tr.customer_id = c.id
            JOIN artists s ON tr.staff_id = s.id
            WHERE so.token = %s
            FOR UPDATE
        """, (token,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return jsonify({'success': False, 'message': 'Link geçersiz'}), 404

        (offer_id, duration_minutes, expires_at, used_at, offer_price, tr_id,
         customer_id, staff_id, body_area, body_region, tattoo_size, tattoo_style,
         reference_number, request_description, customer_phone, customer_first_name,
         customer_last_name, staff_name, staff_phone) = row

        customer_name = ' '.join(
            filter(None, [customer_first_name, customer_last_name])
        ).strip() or None

        if used_at is not None:
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu link daha önce kullanılmış'}), 410

        if expires_at and expires_at < datetime.utcnow():
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu linkin süresi dolmuş'}), 410

        available_start_slots, _ = compute_available_start_slots(
            cursor, staff_id, formatted_date, duration_minutes,
            body_region=body_region, body_area=body_area
        )

        if time_str not in available_start_slots:
            if is_private_body_region(body_region, body_area) and get_private_zone_settings().get('enabled'):
                msg = (
                    'Seçilen saat özel bölge randevu penceresine uygun değil. '
                    f'Yalnızca {format_private_zone_schedule_summary()} aralıklarında randevu alınabilir.'
                )
            else:
                msg = 'Seçilen saat artık uygun değil. Lütfen saatleri yeniden yükleyip tekrar deneyin.'
            cursor.close()
            return jsonify({'success': False, 'message': msg}), 409

        cursor.execute("""
            INSERT INTO appointments (customer_id, staff_id, tattoo_request_id, appointment_date, appointment_time, status, duration_minutes, price, source)
            VALUES (%s, %s, %s, %s, %s, 'confirmed', %s, %s, 'customer')
            RETURNING id
        """, (customer_id, staff_id, tr_id, formatted_date, time_str, int(duration_minutes), float(offer_price or 0)))
        new_appointment_id = cursor.fetchone()[0]

        cursor.execute("UPDATE slot_offers SET used_at = NOW() WHERE id = %s", (offer_id,))
        cursor.execute("UPDATE tattoo_requests SET status = 'scheduled' WHERE id = %s", (tr_id,))

        conn.commit()

        try:
            on_appointment_created(new_appointment_id)
        except Exception as gcal_err:
            logger.warning(f"Google Calendar senkronu atlandı (apt #{new_appointment_id}): {gcal_err}")

        customer_msg = build_appointment_created_customer_message(
            date_str,
            time_str,
            duration_minutes,
            offer_price,
            staff_name=staff_name,
            customer_name=customer_name,
            reference_number=reference_number,
            style_label=tattoo_style,
            body_area=body_area,
            tattoo_size=tattoo_size,
            private_zone=is_private_body_region(body_region, body_area),
        )
        staff_msg = build_appointment_created_staff_message(
            customer_phone,
            date_str,
            time_str,
            duration_minutes,
            offer_price,
            customer_name=customer_name,
            reference_number=reference_number,
            style_label=tattoo_style,
            body_area=body_area,
            tattoo_size=tattoo_size,
            description=request_description,
            private_zone=is_private_body_region(body_region, body_area),
        )

        send_wapio_message(customer_phone, customer_msg)
        send_wapio_message(staff_phone, staff_msg)

        cursor.close()
        return jsonify({'success': True, 'message': 'Randevu oluşturuldu'})
    except psycopg2.IntegrityError as e:
        if conn:
            conn.rollback()
        logger.warning(f"choose_offer_slot IntegrityError: {e}")
        return jsonify({'success': False, 'message': 'Bu saat dolu. Lütfen başka bir saat seçin.'}), 409
    except Exception as e:
        if conn:
            conn.rollback()
        log_error(logger, E_BOOK_001, "Randevu olusturulamadi (teklif slot)", exc=e)
        return jsonify({'success': False, 'message': 'Bir problem oluştu'}), 500
    finally:
        release_db_connection(conn)


# =============================================
# ADMIN PANEL ENDPOINTS
# =============================================

@app.route('/api/admin/login', methods=['POST'])
@limiter.limit("5 per minute")  # Brute force koruması
def admin_login():
    """Admin/Staff login endpoint"""
    data = request.get_json()
    phone = data.get('phone')
    password = data.get('password')
    
    if not phone or not password:
        return jsonify({'success': False, 'message': 'Telefon ve şifre gerekli'}), 400
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, password, role, profile_photo
            FROM artists WHERE phone = %s
        """, (phone,))
        staff = cursor.fetchone()
        cursor.close()
        
        if not staff:
            return jsonify({'success': False, 'message': 'Kullanıcı bulunamadı'}), 401
        
        stored_password = staff[2]
        # Check password using verify_password (supports bcrypt and legacy)
        if not verify_password(password, stored_password):
            return jsonify({'success': False, 'message': 'Şifre yanlış'}), 401
        
        # Generate JWT token (remember_me: 30 gün, aksi halde 8 saat)
        remember_me = bool(data.get('remember_me'))
        token_hours = 24 * 30 if remember_me else 8
        token = jwt.encode({
            'staff_id': staff[0],
            'name': staff[1],
            'role': staff[3],
            'remember': remember_me,
            'exp': datetime.utcnow() + timedelta(hours=token_hours)
        }, JWT_SECRET, algorithm='HS256')
        
        logger.info(f"Admin girişi başarılı: {phone}")
        
        return jsonify({
            'success': True,
            'message': 'Giriş başarılı',
            'token': token,
            'staff': {
                'id': staff[0],
                'name': staff[1],
                'role': staff[3],
                'profile_photo': staff[4]
            }
        })
    except Exception as e:
        log_error(logger, E_AUTH_001, "Admin girisi sirasinda beklenmeyen hata", exc=e)
        return jsonify({'success': False, 'message': 'Giriş sırasında hata oluştu'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/tattoo-requests', methods=['GET'])
@limiter.exempt
@token_required
def admin_list_tattoo_requests():
    """List tattoo requests for admin panel."""
    if not can_access_tattoo_requests():
        return jsonify({'success': False, 'message': 'Bu sayfaya erişim yetkiniz yok'}), 403

    status_filter = request.args.get('status')  # optional
    staff_id_filter = request.args.get('staff_id')  # super_admin optional
    reference_filter = (request.args.get('reference') or '').strip().upper()

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                tr.id,
                tr.reference_number,
                tr.created_at,
                tr.status,
                tr.size,
                tr.body_area,
                tr.tattoo_style,
                tr.estimated_price,
                tr.description,
                tr.reference_image,
                c.id as customer_id,
                c.phone as customer_phone,
                COALESCE(c.name, '') as customer_name,
                COALESCE(c.surname, '') as customer_surname,
                s.id as staff_id,
                s.name as staff_name,
                tr.loyalty_discount_code,
                tr.loyalty_discount_percent,
                lr.redemption_code,
                lr.discount_percent,
                lr.used_at
            FROM tattoo_requests tr
            JOIN customers c ON tr.customer_id = c.id
            JOIN artists s ON tr.staff_id = s.id
            LEFT JOIN loyalty_redemptions lr ON tr.loyalty_redemption_id = lr.id
            WHERE 1=1
        """
        params = []

        if is_studio_admin():
            scope = (request.args.get('scope') or '').strip().lower()
            if scope == 'mine':
                query += " AND tr.staff_id = %s"
                params.append(request.staff_id)
            elif staff_id_filter:
                query += " AND tr.staff_id = %s"
                params.append(staff_id_filter)
        else:
            query += " AND tr.staff_id = %s"
            params.append(request.staff_id)

        if status_filter:
            query += " AND tr.status = %s"
            params.append(status_filter)

        kind_filter = (request.args.get('kind') or '').strip().lower()
        undecided_clause = """(
            tr.tattoo_style IN ('undecided', 'Karar verilmedi')
            OR tr.body_area IN ('Henüz belirlenmedi')
        )"""
        preconsult_clause = """(
            tr.tattoo_style IN ('pre_consultation', 'Ön görüşme')
            OR tr.body_area IN ('Ön görüşme')
        )"""
        if kind_filter in ('undecided', 'karar'):
            query += f" AND {undecided_clause} AND NOT {preconsult_clause}"
        elif kind_filter in ('pre_consultation', 'pre-consultation', 'consultation'):
            query += f" AND {preconsult_clause}"
        elif kind_filter in ('standard', 'normal', 'tattoo'):
            query += f" AND NOT {undecided_clause} AND NOT {preconsult_clause}"

        if reference_filter:
            query += " AND UPPER(tr.reference_number) LIKE %s"
            params.append(f"%{reference_filter}%")

        query += " ORDER BY tr.created_at DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()

        items = []
        for r in rows:
            item = {
                'id': r[0],
                'reference_number': r[1],
                'created_at': r[2].strftime('%d.%m.%Y %H:%M') if r[2] else None,
                'status': r[3],
                'size': r[4],
                'body_area': r[5],
                'tattoo_style': r[6],
                'estimated_price': float(r[7]) if r[7] is not None else None,
                'description': r[8],
                'reference_image': r[9],
                'customer': {
                    'id': r[10],
                    'phone': r[11],
                    'name': r[12].strip() or None,
                    'surname': r[13].strip() or None,
                    'full_name': (f"{r[12]} {r[13]}").strip() or None
                },
                'staff': {'id': r[14], 'name': r[15]},
            }
            discount_code = r[16] or r[18]
            if discount_code:
                item['loyalty_discount'] = {
                    'code': discount_code,
                    'discount_percent': int(r[17] or r[19] or 10),
                    'used': r[20] is not None,
                }
            items.append(item)

        return jsonify({'success': True, 'tattoo_requests': items})
    except Exception as e:
        logger.error(f"admin_list_tattoo_requests hatası: {e}")
        return jsonify({'success': False, 'message': 'Talepler alınırken hata oluştu'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/tattoo-requests/<int:tattoo_request_id>/offer', methods=['POST'])
@token_required
def admin_offer_slots(tattoo_request_id):
    """Admin sets duration, system sends token link to customer."""
    if not can_access_tattoo_requests():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403

    data = request.get_json() or {}
    duration_minutes = int(data.get('duration_minutes') or 0)
    expires_hours    = int(data.get('expires_hours') or 48)
    price            = float(data.get('price') or 0)

    if duration_minutes < 60 or duration_minutes % 60 != 0:
        return jsonify({'success': False, 'message': 'duration_minutes 60 dakikanın katı olmalı (örn 60, 120, 180)'}), 400
    if expires_hours <= 0 or expires_hours > 168:
        expires_hours = 48
    if price < 0:
        price = 0

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Permission: staff can only offer their own requests (super_admin can offer all)
        loyalty_discount = get_request_loyalty_discount(cursor, tattoo_request_id)

        cursor.execute("""
            SELECT tr.customer_id, tr.staff_id, tr.reference_number, c.phone, s.name
            FROM tattoo_requests tr
            JOIN customers c ON tr.customer_id = c.id
            JOIN artists s ON tr.staff_id = s.id
            WHERE tr.id = %s
        """, (tattoo_request_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return jsonify({'success': False, 'message': 'Talep bulunamadı'}), 404

        customer_id, staff_id, request_ref, customer_phone, staff_name = row
        if not is_studio_admin() and int(staff_id) != int(request.staff_id):
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu talep için yetkiniz yok'}), 403

        from evolution_client import resolve_evolution_send_target

        phone_digits = re.sub(r'\D', '', str(customer_phone or ''))
        if phone_digits.startswith('0') and len(phone_digits) == 11:
            phone_digits = '90' + phone_digits[1:]
        elif len(phone_digits) == 10 and not phone_digits.startswith('90'):
            phone_digits = f'90{phone_digits}'
        if len(phone_digits) != 12 or not phone_digits.startswith('90') or phone_digits[2] != '5':
            cursor.close()
            return jsonify({
                'success': False,
                'message': (
                    f'Geçersiz müşteri telefonu ({customer_phone}). '
                    'Talep 5XXXXXXXXX formatında kayıtlı olmalı.'
                ),
            }), 400
        whatsapp_target = resolve_evolution_send_target(customer_phone)

        original_price = float(price)
        final_price = original_price
        discount_applied = False
        discount_percent = None
        loyalty_code = None

        if (
            loyalty_discount
            and loyalty_discount.get('used_at') is None
            and original_price > 0
        ):
            final_price, _, discount_percent = apply_percent_discount(
                original_price, loyalty_discount['discount_percent']
            )
            if loyalty_discount.get('redemption_id'):
                mark_redemption_used_for_offer(
                    cursor, loyalty_discount['redemption_id'], tattoo_request_id
                )
            discount_applied = True
            loyalty_code = loyalty_discount['code']

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=expires_hours)

        cursor.execute("""
            INSERT INTO slot_offers (
                tattoo_request_id, token, duration_minutes, expires_at,
                price, original_price, discount_percent
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            tattoo_request_id, token, duration_minutes, expires_at,
            final_price,
            original_price if discount_applied else None,
            discount_percent if discount_applied else None,
        ))

        cursor.execute("UPDATE tattoo_requests SET status = 'offered' WHERE id = %s", (tattoo_request_id,))

        conn.commit()
        cursor.close()

        offer_url = build_slot_select_url(token)

        if discount_applied:
            price_line = (
                f"💰 Ücret: *{final_price:.2f} ₺*\n"
                f"   _(Liste fiyatı {original_price:.2f} ₺ — "
                f"%{discount_percent} sadakat indirimi: {loyalty_code})_\n\n"
            )
        elif final_price > 0:
            price_line = f"💰 Ücret: *{final_price:.2f} ₺*\n\n"
        else:
            price_line = ""

        ref_line = f"📋 Referans: *{request_ref}*\n\n" if request_ref else ""
        msg = (
            f"🕒 *Dövme Randevu Saat Seçimi*\n\n"
            f"{ref_line}"
            f"Dövmeniz için süre: *{duration_minutes} dakika*.\n\n"
            f"{price_line}"
            f"Aşağıdaki linkten sadece bu süreye uygun saatleri göreceksiniz (60 dk slotlar).\n\n"
            f"Link: {offer_url}\n\n"
            f"Not: Link {expires_hours} saat boyunca geçerlidir."
        )
        whatsapp_sent = send_wapio_message(customer_phone, msg)
        if whatsapp_sent:
            logger.info(
                f"Teklif linki WhatsApp OK: request_id={tattoo_request_id}, "
                f"hedef={whatsapp_target}, db_phone={customer_phone}"
            )
        else:
            logger.error(
                f"Teklif linki WhatsApp ile gönderilemedi: request_id={tattoo_request_id}, "
                f"hedef={whatsapp_target}, db_phone={customer_phone}"
            )

        if discount_applied and whatsapp_sent:
            status_msg = (
                f'Link gönderildi — %{discount_percent} sadakat indirimi uygulandı '
                f'({original_price:.2f} ₺ → {final_price:.2f} ₺, kod: {loyalty_code})'
            )
        elif discount_applied and not whatsapp_sent:
            status_msg = (
                f'Teklif oluşturuldu (WhatsApp gönderilemedi) — %{discount_percent} indirim kayıtlı. '
                f'Linki manuel paylaşın: {offer_url}'
            )
        elif whatsapp_sent:
            status_msg = 'Link müşteriye WhatsApp ile gönderildi'
        else:
            status_msg = (
                f'Teklif oluşturuldu ancak WhatsApp mesajı gitmedi. '
                f'Bağlantıyı kontrol edin veya linki manuel gönderin: {offer_url}'
            )

        return jsonify({
            'success': True,
            'token': token,
            'offer_url': offer_url,
            'whatsapp_sent': whatsapp_sent,
            'whatsapp_target': whatsapp_target,
            'customer_phone': customer_phone,
            'message': status_msg,
            'discount_applied': discount_applied,
            'original_price': original_price if discount_applied else None,
            'final_price': final_price if discount_applied else (original_price if original_price > 0 else None),
            'discount_percent': discount_percent,
            'loyalty_code': loyalty_code,
        })
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"admin_offer_slots hatası: {e}")
        return jsonify({'success': False, 'message': 'Teklif oluşturulamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/appointments', methods=['GET'])
@limiter.exempt
@token_required
def get_admin_appointments():
    """Get appointments list for admin panel"""
    status_filter = request.args.get('status')  # pending, confirmed, etc.
    date_filter = request.args.get('date')  # Format: "16.12.2025"
    exclude_pending = request.args.get('exclude_pending')  # Bekleyenleri hariç tut
    exclude_completed = request.args.get('exclude_completed')  # Tamamlanmış/iptal/gelmedi hariç tut
    staff_id_filter = request.args.get('staff_id')  # Super admin için personel filtresi
    scope = request.args.get('scope')  # 'all' => Tüm/Geçmiş Randevular (yalnızca super_admin)
    start_date = request.args.get('start_date')  # Format: "2025-12-16"
    end_date = request.args.get('end_date')  # Format: "2025-12-16"
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT
                a.id,
                a.appointment_date,
                a.appointment_time,
                a.status,
                a.created_at,
                a.duration_minutes,
                c.id as customer_id,
                COALESCE(c.name, '') as customer_name,
                COALESCE(c.surname, '') as customer_surname,
                c.phone as customer_phone,
                s.id as staff_id,
                s.name as staff_name,
                tr.id as tattoo_request_id,
                tr.size,
                tr.body_area,
                tr.description,
                tr.reference_image,
                COALESCE(a.price, 0) as price,
                a.source
            FROM appointments a
            JOIN customers c ON a.customer_id = c.id
            JOIN artists s ON a.staff_id = s.id
            LEFT JOIN tattoo_requests tr ON a.tattoo_request_id = tr.id
            WHERE 1=1
        """
        params = []
        
        # Yetki kontrolü:
        # - Diğer personelin randevuları YALNIZCA super_admin VE scope='all' olduğunda görünür.
        #   (Sadece "Tüm Randevular" ve "Geçmiş Randevular" sekmeleri scope=all gönderir.)
        # - Normal "Randevular" sekmesinde (scope yok) super admin dahil herkes
        #   yalnızca KENDİ randevularını görür.
        is_all_scope = (is_studio_admin() and scope == 'all')
        if is_all_scope and staff_id_filter:
            # Super admin belirli bir personeli filtreledi
            query += " AND a.staff_id = %s"
            params.append(staff_id_filter)
        elif is_all_scope:
            # Super admin tüm personelin randevularını görüyor - personel filtresi yok
            pass
        else:
            # Sadece kendi randevuları (normal personel veya super admin kendi sekmesinde)
            query += " AND a.staff_id = %s"
            params.append(request.staff_id)
        
        if status_filter:
            query += " AND a.status = %s"
            params.append(status_filter)
        
        # Bekleyenleri hariç tut (exclude_pending=true ise)
        if exclude_pending == 'true':
            query += " AND a.status != 'pending'"
        
        # Tamamlanmış/iptal/gelmedi olanları hariç tut (exclude_completed=true ise)
        # Sadece pending ve confirmed olanları göster
        if exclude_completed == 'true':
            query += " AND a.status NOT IN ('completed', 'cancelled', 'no_show')"
        
        if date_filter:
            # Convert "16.12.2025" to "2025-12-16"
            day, month, year = date_filter.split('.')
            formatted_date = f"{year}-{month}-{day}"
            query += " AND a.appointment_date = %s"
            params.append(formatted_date)
        
        # Tarih aralığı filtresi (Tüm Randevular sekmesi için)
        if start_date:
            query += " AND a.appointment_date >= %s"
            params.append(start_date)
        
        if end_date:
            query += " AND a.appointment_date <= %s"
            params.append(end_date)
        
        query += " ORDER BY a.appointment_date DESC, a.appointment_time ASC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        
        appointments = []
        for row in rows:
            customer_full = (f"{row[7]} {row[8]}").strip()
            appointments.append({
                'id': row[0],
                'date': row[1].strftime('%d.%m.%Y'),
                'time': str(row[2])[:5],
                'status': row[3],
                'created_at': row[4].strftime('%d.%m.%Y %H:%M') if row[4] else None,
                'duration_minutes': int(row[5] or 30),
                'can_complete': _appointment_has_started(row[1], row[2]),
                'customer': {
                    'id': row[6],
                    'name': row[7] or None,
                    'surname': row[8] or None,
                    'phone': row[9],
                    'full_name': customer_full or None
                },
                'staff': {
                    'id': row[10],
                    'name': row[11]
                },
                'tattoo_request': {
                    'id': row[12],
                    'size': row[13],
                    'body_area': row[14],
                    'description': row[15],
                    'reference_image': row[16]
                },
                'price': float(row[17] or 0),
                'source': row[18] or 'admin'
            })
        
        return jsonify({'success': True, 'appointments': appointments})
    except Exception as e:
        logger.error(f"get_admin_appointments hatası: {e}")
        return jsonify({'success': False, 'message': 'Randevular alınırken hata oluştu'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/manual-appointment/available-slots', methods=['GET'])
@token_required
def admin_manual_appointment_available_slots():
    """Manuel randevu formu — mesai saatlerine göre uygun başlangıç saatleri."""
    staff_id = request.args.get('staff_id', type=int)
    date_str = (request.args.get('date') or '').strip()
    duration_minutes = request.args.get('duration_minutes', type=int)

    if not staff_id or not date_str:
        return jsonify({'success': False, 'message': 'staff_id ve date gerekli'}), 400

    if not is_studio_admin() and int(staff_id) != int(request.staff_id):
        return jsonify({'success': False, 'message': 'Bu personel için yetkiniz yok'}), 403

    try:
        day, month, year = date_str.split('.')
        formatted_date = f"{year}-{month}-{day}"
    except ValueError:
        return jsonify({'success': False, 'message': 'Tarih formatı: GG.AA.YYYY'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        slot_details = compute_available_start_slots(
            cursor,
            int(staff_id),
            formatted_date,
            duration_minutes,
            return_details=True,
            skip_past_filter=False,
            past_filter_mode='strict',
        )
        cursor.close()
        return jsonify({
            'success': True,
            'available_start_slots': slot_details['available_start_slots'],
            'work_start': slot_details.get('work_start'),
            'work_end': slot_details.get('work_end'),
            'is_day_closed': slot_details.get('is_day_closed', False),
        })
    except Exception as e:
        logger.error(f"admin_manual_appointment_available_slots hatası: {e}")
        return jsonify({'success': False, 'message': 'Saatler alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/appointments/manual', methods=['POST'])
@limiter.exempt
@token_required
def admin_create_manual_appointment():
    """Dükkan / telefon vb. için admin panelden manuel randevu oluştur."""
    data = request.get_json() or {}
    phone_raw = (data.get('phone') or '').strip()
    name = format_person_name(data.get('name'))
    surname = format_person_name(data.get('surname'))
    date_str = (data.get('date') or '').strip()  # dd.mm.yyyy
    time_str = (data.get('time') or '').strip()[:5]
    duration_minutes = int(data.get('duration_minutes') or 0)
    price = float(data.get('price') or 0)
    status = (data.get('status') or 'confirmed').strip()
    send_whatsapp = data.get('send_whatsapp', True) not in (False, 'false', 0, '0')
    staff_id_raw = data.get('staff_id')

    if not phone_raw or not name or not surname:
        return jsonify({'success': False, 'message': 'Telefon, ad ve soyad zorunludur'}), 400
    if not date_str or not time_str:
        return jsonify({'success': False, 'message': 'Tarih ve saat zorunludur'}), 400
    if duration_minutes < 60 or duration_minutes % 60 != 0:
        return jsonify({'success': False, 'message': 'Süre 60 dakikanın katı olmalı (örn. 60, 120, 180)'}), 400
    if status not in ('pending', 'confirmed'):
        status = 'confirmed'
    if price < 0:
        price = 0

    phone = customer_phone_for_db(phone_raw)
    if len(phone) != 10:
        return jsonify({'success': False, 'message': 'Geçerli 10 haneli telefon girin'}), 400

    try:
        day, month, year = date_str.split('.')
        formatted_date = f"{year}-{month}-{day}"
    except ValueError:
        return jsonify({'success': False, 'message': 'Tarih formatı: GG.AA.YYYY'}), 400

    if is_studio_admin() and staff_id_raw:
        staff_id = int(staff_id_raw)
    else:
        staff_id = int(request.staff_id)

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, name, phone FROM artists WHERE id = %s", (staff_id,))
        staff_row = cursor.fetchone()
        if not staff_row:
            cursor.close()
            return jsonify({'success': False, 'message': 'Personel bulunamadı'}), 404

        if not is_studio_admin() and staff_id != int(request.staff_id):
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu personel için randevu oluşturamazsınız'}), 403

        available_starts, is_day_closed = compute_available_start_slots(
            cursor, staff_id, formatted_date, duration_minutes
        )
        if is_day_closed:
            cursor.close()
            return jsonify({'success': False, 'message': 'Seçilen gün kapalı (izin / kapalı gün)'}), 400
        if time_str not in available_starts:
            cursor.close()
            return jsonify({
                'success': False,
                'message': 'Seçilen saat takvimde uygun değil veya dolu. Lütfen listeden başka saat seçin.'
            }), 409

        # Kayıt anında tekrar kilitle ve çakışma kontrolü (aynı takvim kuralları)
        cursor.execute("""
            SELECT id FROM appointments
            WHERE staff_id = %s AND appointment_date = %s AND status != 'cancelled'
            FOR UPDATE
        """, (staff_id, formatted_date))

        if appointment_slot_conflicts(cursor, staff_id, formatted_date, time_str, duration_minutes):
            conn.rollback()
            cursor.close()
            return jsonify({
                'success': False,
                'message': 'Bu saat aralığında başka randevu var. Süreyi veya saati değiştirin.'
            }), 409

        available_starts_locked, is_day_closed_locked = compute_available_start_slots(
            cursor, staff_id, formatted_date, duration_minutes
        )
        if is_day_closed_locked or time_str not in available_starts_locked:
            conn.rollback()
            cursor.close()
            return jsonify({
                'success': False,
                'message': 'Saat artık uygun değil (takvim güncellendi). Lütfen saatleri yenileyip tekrar deneyin.'
            }), 409

        existing = find_customer_by_phone(cursor, phone)
        if existing:
            cursor.execute("""
                UPDATE customers SET name = %s, surname = %s
                WHERE id = %s
                RETURNING id, phone, name, surname
            """, (name, surname, existing[0]))
        else:
            cursor.execute("""
                INSERT INTO customers (phone, name, surname)
                VALUES (%s, %s, %s)
                RETURNING id, phone, name, surname
            """, (phone, name, surname))
        cust = cursor.fetchone()
        customer_id = cust[0]

        cursor.execute("""
            INSERT INTO appointments (
                customer_id, staff_id, tattoo_request_id,
                appointment_date, appointment_time, status,
                duration_minutes, price, source
            )
            VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, 'admin')
            RETURNING id
        """, (
            customer_id, staff_id, formatted_date, time_str,
            status, duration_minutes, price
        ))
        appointment_id = cursor.fetchone()[0]
        conn.commit()

        staff_name, staff_phone = staff_row[1], staff_row[2]
        customer_phone_display = phone

        if send_whatsapp:
            try:
                customer_msg = build_appointment_created_customer_message(
                    date_str,
                    time_str,
                    duration_minutes,
                    price,
                    staff_name=staff_name,
                    customer_name=f'{name} {surname}'.strip() or None,
                )
                send_wapio_message(customer_phone_display, customer_msg)
                if staff_phone:
                    staff_msg = build_appointment_created_staff_message(
                        customer_phone_display,
                        date_str,
                        time_str,
                        duration_minutes,
                        price,
                        customer_name=f'{name} {surname}'.strip(),
                        manual=True,
                    )
                    send_wapio_message(staff_phone, staff_msg)
            except Exception as wa_err:
                logger.warning(f"Manuel randevu WhatsApp bildirimi gönderilemedi: {wa_err}")

        cursor.close()
        logger.info(f"Manuel randevu oluşturuldu: apt={appointment_id}, customer={customer_id}, staff={staff_id}")

        try:
            on_appointment_created(appointment_id)
        except Exception as gcal_err:
            logger.warning(f"Google Calendar senkronu atlandı (apt #{appointment_id}): {gcal_err}")

        return jsonify({
            'success': True,
            'message': 'Randevu oluşturuldu ve müşteri kaydedildi',
            'appointment': {
                'id': appointment_id,
                'date': date_str,
                'time': time_str,
                'status': status,
                'duration_minutes': duration_minutes,
                'price': price,
                'source': 'admin',
            },
            'customer': {
                'id': cust[0],
                'phone': cust[1],
                'name': cust[2],
                'surname': cust[3],
            },
        })
    except psycopg2.IntegrityError as e:
        if conn:
            conn.rollback()
        logger.warning(f"admin_create_manual_appointment IntegrityError: {e}")
        return jsonify({
            'success': False,
            'message': 'Bu saat takvimde dolu. Lütfen başka saat seçin.'
        }), 409
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"admin_create_manual_appointment hatası: {e}", exc_info=True)
        err_msg = str(e).lower()
        if 'value too long' in err_msg or 'varchar' in err_msg:
            return jsonify({'success': False, 'message': 'Telefon veya alan uzunluğu geçersiz'}), 400
        return jsonify({'success': False, 'message': 'Randevu oluşturulamadı'}), 500
    finally:
        release_db_connection(conn)


def _try_record_completed_appointment_income(cursor, appointment_id, apt_price, apt_date, apt_staff, desc_txt):
    """Tamamlanan randevu gelir kaydı — tablo/şema uyumsuzluğunda durum güncellemesini bozmaz."""
    if apt_price <= 0:
        return
    try:
        cursor.execute(
            "SELECT 1 FROM income_adjustments WHERE description LIKE %s LIMIT 1",
            (f'Randevu #{appointment_id}%',),
        )
        if cursor.fetchone():
            logger.info(f"Gelir kaydı zaten var: randevu #{appointment_id}")
            return
    except Exception:
        pass  # tablo yoksa insert denemelerine devam

    attempts = [
        (
            """
            INSERT INTO income_adjustments (amount, type, description, adjustment_date, created_by)
            VALUES (%s, 'income', %s, %s, %s)
            """,
            (apt_price, desc_txt, apt_date, apt_staff),
        ),
        (
            """
            INSERT INTO income_adjustments (amount, description, adjustment_date, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (apt_price, desc_txt, apt_date, apt_staff),
        ),
        (
            """
            INSERT INTO income_adjustments (amount, description, adjustment_date)
            VALUES (%s, %s, %s)
            """,
            (apt_price, desc_txt, apt_date),
        ),
    ]
    last_err = None
    for sql, params in attempts:
        try:
            cursor.execute(sql, params)
            logger.info(f"Gelir kaydı eklendi: randevu #{appointment_id}, tutar={apt_price}")
            return
        except Exception as err:
            last_err = err
            err_s = str(err).lower()
            if 'income_adjustments' in err_s and 'does not exist' in err_s:
                logger.warning(
                    f"income_adjustments tablosu yok — gelir atlandı (randevu #{appointment_id}). "
                    "Migration: backend/migrations/ensure_income_adjustments_table.sql"
                )
                return
    logger.warning(
        f"Gelir kaydı eklenemedi (randevu #{appointment_id} yine de tamamlandı): {last_err}"
    )


def _appointment_has_started(apt_date, apt_time):
    """Randevu başlangıcı (İstanbul) geldiyse True."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Europe/Istanbul')
    except Exception:
        tz = None
    if isinstance(apt_date, datetime):
        apt_date = apt_date.date()
    t = apt_time
    if t is None:
        t = dt_time(0, 0)
    elif isinstance(t, datetime):
        t = t.time()
    elif not isinstance(t, dt_time):
        parts = str(t).split(':')
        t = dt_time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    start = datetime.combine(apt_date, t.replace(tzinfo=None) if getattr(t, 'tzinfo', None) else t)
    if tz:
        start = start.replace(tzinfo=tz)
        now = datetime.now(tz)
    else:
        now = datetime.now()
    return now >= start


@app.route('/api/admin/appointments/<int:appointment_id>/status', methods=['PUT'])
@token_required
def update_appointment_status(appointment_id):
    """Update appointment status and send WhatsApp notification"""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    
    valid_statuses = ['pending', 'confirmed', 'completed', 'cancelled', 'no_show']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'message': 'Geçersiz durum'}), 400
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get appointment details for notification (mevcut status'u da al)
        cursor.execute("""
            SELECT 
                a.appointment_date, a.appointment_time,
                a.status,
                a.duration_minutes,
                c.phone, COALESCE(c.name, ''), COALESCE(c.surname, ''),
                s.name as staff_name,
                tr.size, tr.body_area,
                a.google_event_id,
                a.customer_id
            FROM appointments a
            JOIN customers c ON a.customer_id = c.id
            JOIN artists s ON a.staff_id = s.id
            LEFT JOIN tattoo_requests tr ON a.tattoo_request_id = tr.id
            WHERE a.id = %s
        """, (appointment_id,))
        
        appointment = cursor.fetchone()
        if not appointment:
            cursor.close()
            return jsonify({'success': False, 'message': 'Randevu bulunamadı'}), 404
        
        # Mevcut durumu al
        old_status = appointment[2]  # appointment[2] = a.status
        google_event_id = appointment[10]

        if old_status != new_status and new_status == 'completed':
            if not _appointment_has_started(appointment[0], appointment[1]):
                cursor.close()
                return jsonify({
                    'success': False,
                    'message': 'Randevu saati gelmeden tamamlandı olarak işaretlenemez',
                }), 400

        # Update status (sadece durum değişiyorsa güncelle)
        if old_status != new_status:
            if new_status == 'cancelled':
                # İptal edilen randevular hemen siliniyor
                cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
                conn.commit()
                logger.info(f"Randevu {appointment_id} iptal edildi ve silindi: {old_status} -> {new_status}")
                try:
                    on_appointment_cancelled(google_event_id)
                except Exception as gcal_err:
                    logger.warning(f"Google Calendar silme atlandı (apt #{appointment_id}): {gcal_err}")
            else:
                if new_status == 'completed':
                    cursor.execute("""
                        UPDATE appointments
                        SET status = %s, completed_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (new_status, appointment_id))
                else:
                    cursor.execute("""
                        UPDATE appointments SET status = %s WHERE id = %s
                    """, (new_status, appointment_id))

                # Tamamlandı → fiyat varsa gelir kaydı ekle
                if new_status == 'completed':
                    cursor.execute("SELECT price, staff_id FROM appointments WHERE id = %s", (appointment_id,))
                    apt_row = cursor.fetchone()
                    apt_price = float(apt_row[0] or 0) if apt_row else 0
                    apt_staff = apt_row[1] if apt_row else None
                    apt_date = appointment[0]
                    size_str = appointment[8] or ''
                    area_str = appointment[9] or ''
                    desc_txt = f"Randevu #{appointment_id}" + (f" · {area_str}" if area_str else '') + (f" · {size_str}" if size_str else '')
                    _try_record_completed_appointment_income(
                        cursor, appointment_id, apt_price, apt_date, apt_staff, desc_txt
                    )
                    try:
                        award_loyalty_on_completion(
                            cursor, appointment[11], appointment_id
                        )
                    except Exception as loyalty_err:
                        logger.warning(
                            f"Sadakat puanı atlandı (apt #{appointment_id}): {loyalty_err}"
                        )

                conn.commit()
                logger.info(f"Randevu {appointment_id} durumu güncellendi: {old_status} -> {new_status}")
                try:
                    on_appointment_status_changed(appointment_id)
                except Exception as gcal_err:
                    logger.warning(f"Google Calendar güncelleme atlandı (apt #{appointment_id}): {gcal_err}")
        else:
            conn.commit()
            logger.info(f"Randevu {appointment_id} durumu zaten {new_status}, güncelleme yapılmadı")
        
        cursor.close()
        
        # Prepare WhatsApp notification
        duration_minutes = int(appointment[3] or 30)
        customer_phone = appointment[4]  # c.phone
        date_str = appointment[0].strftime('%d.%m.%Y')  # appointment_date
        time_str = str(appointment[1])[:5]  # appointment_time
        customer_name = (f"{appointment[5]} {appointment[6]}").strip() or f"0{customer_phone}"
        staff_name = appointment[7]  # staff_name
        tattoo_size = appointment[8]
        tattoo_area = appointment[9]
        
        business_name = SITE_CONFIG['business_name']
        
        if new_status == 'confirmed':
            message = build_appointment_confirmed_message(
                customer_name, staff_name, date_str, time_str, duration_minutes,
                tattoo_area, tattoo_size,
            )
        
        elif new_status == 'cancelled':
            message = build_appointment_cancelled_message(customer_name, date_str, time_str)
        
        elif new_status == 'completed':
            message = f"""✨ *Teşekkür Ederiz!*

Sayın {customer_name},

Bugünkü randevunuz tamamlandı.
Bizi tercih ettiğiniz için teşekkür ederiz!

⭐ Memnun kaldıysanız, bizi arkadaşlarınıza tavsiye edin!

Tekrar görüşmek üzere,
{business_name}"""
        else:
            message = None
        
        # Send WhatsApp message if applicable (sadece durum değiştiyse)
        # Eğer aynı duruma tekrar güncelleniyorsa mesaj gönderme
        if message and old_status != new_status:
            try:
                send_wapio_message(customer_phone, message)
                logger.info(f"Durum değişikliği mesajı gönderildi: {customer_phone} - {old_status} -> {new_status}")
            except Exception as wapio_err:
                logger.warning(f"WhatsApp mesajı gönderilemedi (durum kaydedildi): {wapio_err}")
        elif old_status == new_status:
            logger.info(
                "Durum degismedi, mesaj gonderilmedi | phone=%s status=%s",
                customer_phone,
                new_status,
            )
        
        return jsonify({
            'success': True, 
            'message': f'Randevu durumu güncellendi: {new_status}'
        })
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_appointment_status hatası: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Durum güncellenirken hata oluştu'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/dashboard', methods=['GET'])
@limiter.exempt
@token_required
def get_admin_dashboard():
    """Get dashboard summary for admin panel"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')

        # Personel kendi istatistiklerini görür; teknik destek stüdyo genelini görür.
        studio_wide = request.staff_role == 'tech_support'
        staff_filter = "" if studio_wide else "AND staff_id = %s"
        params = [today] if studio_wide else [today, request.staff_id]
        
        # Today's active appointments (pending + confirmed; tamamlananlar ayrı kartta)
        cursor.execute(f"""
            SELECT COUNT(*) FROM appointments 
            WHERE appointment_date = %s
              AND status IN ('pending', 'confirmed')
              {staff_filter}
        """, params)
        today_total = cursor.fetchone()[0]
        
        # Pending appointments count
        params_pending = [today] if studio_wide else [today, request.staff_id]
        cursor.execute(f"""
            SELECT COUNT(*) FROM appointments 
            WHERE appointment_date = %s AND status = 'pending' {staff_filter}
        """, params_pending)
        today_pending = cursor.fetchone()[0]
        
        # Confirmed appointments count for today
        params_confirmed = [today] if studio_wide else [today, request.staff_id]
        cursor.execute(f"""
            SELECT COUNT(*) FROM appointments 
            WHERE appointment_date = %s AND status = 'confirmed' {staff_filter}
        """, params_confirmed)
        today_confirmed = cursor.fetchone()[0]
        
        # Completed appointments count for today
        params_completed = [today] if studio_wide else [today, request.staff_id]
        cursor.execute(f"""
            SELECT COUNT(*) FROM appointments 
            WHERE appointment_date = %s AND status = 'completed' {staff_filter}
        """, params_completed)
        today_completed = cursor.fetchone()[0]
        
        # All pending appointments (tüm zamanlar) - pending ve confirmed ama tamamlanmamış olanlar
        staff_filter_simple = "" if studio_wide else "AND staff_id = %s"
        params_all_pending = [] if studio_wide else [request.staff_id]
        cursor.execute(f"""
            SELECT COUNT(*) FROM appointments 
            WHERE status NOT IN ('completed', 'cancelled', 'no_show') {staff_filter_simple}
        """, params_all_pending)
        all_pending = cursor.fetchone()[0]
        
        cursor.close()
        
        return jsonify({
            'success': True,
            'dashboard': {
                'today': {
                    'total': today_total,
                    'pending': today_pending,
                    'confirmed': today_confirmed,
                    'completed': today_completed
                },
                'all_pending': all_pending,
                'date': datetime.now().strftime('%d.%m.%Y')
            }
        })
    except Exception as e:
        logger.error(f"get_admin_dashboard hatası: {e}")
        return jsonify({'success': False, 'message': 'Dashboard verileri alınamadı'}), 500
    finally:
        release_db_connection(conn)


# =============================================
# PERSONEL YÖNETİMİ
# =============================================

@app.route('/api/admin/staff', methods=['GET'])
@token_required
def get_staff_list():
    """Personel listesi - sadece super_admin"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu sayfaya erişim yetkiniz yok'}), 403

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, name, phone, role, profile_photo, COALESCE(display_order, 0) as display_order, instagram_url
            FROM artists
            ORDER BY display_order ASC, name
        """)
        
        rows = cursor.fetchall()
        cursor.close()
        
        staff_list = []
        for row in rows:
            staff_list.append({
                'id': row[0],
                'name': row[1],
                'phone': row[2],
                'role': row[3],
                'profile_photo': row[4],
                'display_order': row[5],
                'instagram_url': row[6] or '',
            })
        
        return jsonify({'success': True, 'staff': staff_list})
    except Exception as e:
        logger.error(f"get_staff_list hatası: {e}")
        return jsonify({'success': False, 'message': 'Personel listesi alınamadı'}), 500
    finally:
        release_db_connection(conn)

@app.route('/api/admin/staff/<int:staff_id>/display-order', methods=['PATCH'])
@token_required
def update_staff_display_order(staff_id):
    """Personelin sıralama değerini güncelle - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    data = request.get_json()
    display_order = data.get('display_order', 0)
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE artists SET display_order = %s WHERE id = %s", (display_order, staff_id))
        conn.commit()
        cursor.close()
        
        logger.info(f"Personel sıralaması güncellendi: id={staff_id}, order={display_order}")
        return jsonify({'success': True, 'message': 'Sıralama güncellendi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_staff_display_order hatası: {e}")
        return jsonify({'success': False, 'message': 'Sıralama güncellenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/staff', methods=['POST'])
@token_required
def add_staff():
    """Yeni personel ekle - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    data = request.get_json()
    name = data.get('name')
    phone = data.get('phone')
    password = data.get('password')
    role = data.get('role', 'staff')
    role_err = _role_assignment_error(desired_role=role)
    if role_err:
        return role_err
    profile_photo = data.get('profile_photo')  # Base64 encoded image
    instagram_raw = data.get('instagram_url', '')
    
    if not name or not phone or not password:
        return jsonify({'success': False, 'message': 'Ad, telefon ve şifre gerekli'}), 400
    
    # Telefon numarası 10 haneli olmalı
    if len(phone) != 10 or not phone.isdigit():
        return jsonify({'success': False, 'message': 'Telefon numarası 10 haneli olmalı (5XXXXXXXXX)'}), 400
    
    # Şifre en az 6 karakter
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Şifre en az 6 karakter olmalı'}), 400
    
    # Profil fotoğrafı boyut kontrolü (max 2MB base64 encoded)
    if profile_photo and len(profile_photo) > 2 * 1024 * 1024:
        return jsonify({'success': False, 'message': 'Profil fotoğrafı çok büyük (max 2MB)'}), 400

    instagram_url = None
    if instagram_raw is not None and str(instagram_raw).strip():
        instagram_url = normalize_instagram_url(instagram_raw)
        if not instagram_url:
            return jsonify({'success': False, 'message': 'Geçerli bir Instagram kullanıcı adı veya linki girin'}), 400
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Telefon numarası zaten var mı kontrol et
        cursor.execute("SELECT id FROM artists WHERE phone = %s", (phone,))
        if cursor.fetchone():
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu telefon numarası zaten kayıtlı'}), 400
        
        # Şifreyi hashle
        hashed_password = hash_password_bcrypt(password)
        
        cursor.execute("""
            INSERT INTO artists (name, phone, password, role, profile_photo, instagram_url)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (name, phone, hashed_password, role, profile_photo, instagram_url))
        
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        
        logger.info(f"Yeni personel eklendi: {name} (id={new_id})")
        
        return jsonify({
            'success': True,
            'message': 'Personel eklendi',
            'staff_id': new_id
        })
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"add_staff hatası: {e}")
        return jsonify({'success': False, 'message': 'Personel eklenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/staff/<int:staff_id>', methods=['PUT'])
@token_required
def update_staff(staff_id):
    """Personel güncelle - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    data = request.get_json()
    name = data.get('name')
    phone = data.get('phone')
    password = data.get('password')
    role = data.get('role')
    profile_photo = data.get('profile_photo')  # Base64 encoded image veya null (silmek için)
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT role FROM artists WHERE id = %s", (staff_id,))
        existing = cursor.fetchone()
        if not existing:
            cursor.close()
            return jsonify({'success': False, 'message': 'Personel bulunamadı'}), 404
        role_err = _role_assignment_error(desired_role=role, existing_role=existing[0])
        if role_err:
            cursor.close()
            return role_err
        
        # Dinamik güncelleme
        updates = []
        params = []
        
        if name:
            updates.append("name = %s")
            params.append(name)
        if phone:
            # Telefon numarası başka birinde var mı kontrol et
            cursor.execute("SELECT id FROM artists WHERE phone = %s AND id != %s", (phone, staff_id))
            if cursor.fetchone():
                cursor.close()
                return jsonify({'success': False, 'message': 'Bu telefon numarası başka personelde kayıtlı'}), 400
            updates.append("phone = %s")
            params.append(phone)
        if password:
            if len(password) < 6:
                cursor.close()
                return jsonify({'success': False, 'message': 'Şifre en az 6 karakter olmalı'}), 400
            updates.append("password = %s")
            params.append(hash_password_bcrypt(password))
        if role:
            updates.append("role = %s")
            params.append(role)
        if 'profile_photo' in data:  # Key var mı kontrol et (null olabilir)
            # Profil fotoğrafı boyut kontrolü
            if profile_photo and len(profile_photo) > 2 * 1024 * 1024:
                cursor.close()
                return jsonify({'success': False, 'message': 'Profil fotoğrafı çok büyük (max 2MB)'}), 400
            updates.append("profile_photo = %s")
            params.append(profile_photo)
        if 'instagram_url' in data:
            raw_ig = data.get('instagram_url')
            if raw_ig is None or not str(raw_ig).strip():
                updates.append("instagram_url = %s")
                params.append(None)
            else:
                normalized_ig = normalize_instagram_url(raw_ig)
                if not normalized_ig:
                    cursor.close()
                    return jsonify({'success': False, 'message': 'Geçerli bir Instagram kullanıcı adı veya linki girin'}), 400
                updates.append("instagram_url = %s")
                params.append(normalized_ig)
        
        if not updates:
            return jsonify({'success': False, 'message': 'Güncellenecek alan yok'}), 400
        
        params.append(staff_id)
        query = f"UPDATE artists SET {', '.join(updates)} WHERE id = %s"
        
        cursor.execute(query, params)
        conn.commit()
        cursor.close()
        
        logger.info(f"Personel güncellendi: id={staff_id}")
        
        return jsonify({'success': True, 'message': 'Personel güncellendi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_staff hatası: {e}")
        return jsonify({'success': False, 'message': 'Personel güncellenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/staff/<int:staff_id>', methods=['DELETE'])
@token_required
def delete_staff(staff_id):
    """Personel sil - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    # Kendini silemez
    if request.staff_id == staff_id:
        return jsonify({'success': False, 'message': 'Kendinizi silemezsiniz'}), 400
    
    # Zorla silme parametresi
    force = request.args.get('force', 'false').lower() == 'true'
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT role FROM artists WHERE id = %s", (staff_id,))
        existing = cursor.fetchone()
        if not existing:
            cursor.close()
            return jsonify({'success': False, 'message': 'Personel bulunamadı'}), 404
        role_err = _role_assignment_error(existing_role=existing[0])
        if role_err:
            cursor.close()
            return role_err
        
        # Personelin aktif randevusu var mı kontrol et
        cursor.execute("""
            SELECT COUNT(*) FROM appointments 
            WHERE staff_id = %s AND status IN ('pending', 'confirmed')
        """, (staff_id,))
        active_appointments = cursor.fetchone()[0]
        
        if active_appointments > 0 and not force:
            cursor.close()
            return jsonify({
                'success': False, 
                'message': f'Bu personelin {active_appointments} aktif randevusu var. Yine de silmek için onay verin.',
                'has_active_appointments': True,
                'active_count': active_appointments
            }), 400
        
        # Tüm randevuları sil (force modunda veya sadece eski randevular)
        cursor.execute("DELETE FROM appointments WHERE staff_id = %s", (staff_id,))
        
        # Tattoo flow: staff_services removed
        
        # Working_hours kayıtlarını sil (foreign key constraint için)
        cursor.execute("DELETE FROM working_hours WHERE staff_id = %s", (staff_id,))
        
        # Time_off (izin) kayıtlarını sil (foreign key constraint için)
        cursor.execute("DELETE FROM time_off WHERE staff_id = %s", (staff_id,))
        
        # Personeli sil
        cursor.execute("DELETE FROM artists WHERE id = %s", (staff_id,))
        conn.commit()
        cursor.close()
        
        logger.info(f"Personel silindi: id={staff_id}, force={force}")
        
        return jsonify({'success': True, 'message': 'Personel silindi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"delete_staff hatası: {e}")
        return jsonify({'success': False, 'message': 'Personel silinemedi'}), 500
    finally:
        release_db_connection(conn)

# =============================================
# ÇALIŞMA SAATLERİ VE İZİN YÖNETİMİ
# =============================================

@app.route('/api/admin/working-hours', methods=['GET'])
@token_required
def get_working_hours():
    """Çalışma saatlerini getir - personel kendisini, super_admin herkesi görebilir"""
    staff_id = request.args.get('staff_id', request.staff_id)
    
    # Yetki kontrolü
    if not is_studio_admin() and int(staff_id) != request.staff_id:
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, day_of_week, start_time, end_time, is_available
            FROM working_hours
            WHERE staff_id = %s
            ORDER BY day_of_week
        """, (staff_id,))
        
        rows = cursor.fetchall()
        cursor.close()
        
        # Günler: 0=Pazar, 1=Pazartesi...
        day_names = ['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi']
        
        working_hours = []
        for row in rows:
            working_hours.append({
                'id': row[0],
                'day_of_week': row[1],
                'day_name': day_names[row[1]],
                'start_time': str(row[2])[:5] if row[2] else None,
                'end_time': str(row[3])[:5] if row[3] else None,
                'is_available': row[4]
            })
        
        return jsonify({'success': True, 'working_hours': working_hours, 'staff_id': int(staff_id)})
    except Exception as e:
        logger.error(f"get_working_hours hatası: {e}")
        return jsonify({'success': False, 'message': 'Çalışma saatleri alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/working-hours', methods=['PUT'])
@token_required
def update_working_hours():
    """Çalışma saatlerini güncelle — yalnızca super_admin"""
    if not is_studio_admin():
        return jsonify({
            'success': False,
            'message': 'Çalışma saatlerini düzenleme yetkiniz yok',
        }), 403

    data = request.get_json() or {}
    staff_id = data.get('staff_id', request.staff_id)
    working_hours = data.get('working_hours', [])
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Mevcut saatleri sil
        cursor.execute("DELETE FROM working_hours WHERE staff_id = %s", (staff_id,))
        
        # Yeni saatleri ekle
        for wh in working_hours:
            cursor.execute("""
                INSERT INTO working_hours (staff_id, day_of_week, start_time, end_time, is_available)
                VALUES (%s, %s, %s, %s, %s)
            """, (staff_id, wh['day_of_week'], wh.get('start_time') or '09:00', wh.get('end_time') or '20:00', wh.get('is_available', True)))
        
        conn.commit()
        cursor.close()
        
        logger.info(f"Çalışma saatleri güncellendi: staff_id={staff_id}")
        
        return jsonify({'success': True, 'message': 'Çalışma saatleri kaydedildi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_working_hours hatası: {e}")
        return jsonify({'success': False, 'message': 'Çalışma saatleri kaydedilemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/time-off', methods=['GET'])
@token_required
def get_time_off():
    """İzin günlerini listele"""
    staff_id = request.args.get('staff_id', request.staff_id)
    start_date = request.args.get('start_date')  # Format: YYYY-MM-DD
    end_date = request.args.get('end_date')      # Format: YYYY-MM-DD
    
    # Yetki kontrolü
    if not is_studio_admin() and int(staff_id) != request.staff_id:
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT id, off_date, start_time, end_time, reason, created_at
            FROM time_off
            WHERE staff_id = %s
        """
        params = [staff_id]
        
        if start_date:
            query += " AND off_date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND off_date <= %s"
            params.append(end_date)
        
        query += " ORDER BY off_date DESC, start_time"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()
        
        time_offs = []
        for row in rows:
            time_offs.append({
                'id': row[0],
                'date': row[1].strftime('%d.%m.%Y'),
                'date_raw': row[1].strftime('%Y-%m-%d'),
                'start_time': str(row[2])[:5] if row[2] else None,
                'end_time': str(row[3])[:5] if row[3] else None,
                'is_full_day': row[2] is None,
                'reason': row[4],
                'created_at': row[5].strftime('%d.%m.%Y %H:%M')
            })
        
        return jsonify({'success': True, 'time_offs': time_offs})
    except Exception as e:
        logger.error(f"get_time_off hatası: {e}")
        return jsonify({'success': False, 'message': 'İzinler alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/time-off', methods=['POST'])
@token_required
def add_time_off():
    """Yeni izin ekle"""
    data = request.get_json()
    staff_id = data.get('staff_id', request.staff_id)
    off_date = data.get('date')  # Format: YYYY-MM-DD
    start_time = data.get('start_time')  # Format: HH:MM veya None (tüm gün)
    end_time = data.get('end_time')
    reason = data.get('reason', '')
    
    # Yetki kontrolü
    if not is_studio_admin() and int(staff_id) != request.staff_id:
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    if not off_date:
        return jsonify({'success': False, 'message': 'Tarih gerekli'}), 400
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO time_off (staff_id, off_date, start_time, end_time, reason)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (staff_id, off_date, start_time, end_time, reason))
        
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        
        logger.info(f"İzin eklendi: staff_id={staff_id}, date={off_date}")
        
        return jsonify({'success': True, 'message': 'İzin eklendi', 'id': new_id})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"add_time_off hatası: {e}")
        return jsonify({'success': False, 'message': 'İzin eklenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/time-off/<int:time_off_id>', methods=['DELETE'])
@token_required
def delete_time_off(time_off_id):
    """İzin iptal et"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # İznin sahibini kontrol et
        cursor.execute("SELECT staff_id FROM time_off WHERE id = %s", (time_off_id,))
        row = cursor.fetchone()
        
        if not row:
            cursor.close()
            return jsonify({'success': False, 'message': 'İzin bulunamadı'}), 404
        
        # Yetki kontrolü
        if not is_studio_admin() and row[0] != request.staff_id:
            cursor.close()
            return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
        
        cursor.execute("DELETE FROM time_off WHERE id = %s", (time_off_id,))
        conn.commit()
        cursor.close()
        
        logger.info(f"İzin silindi: id={time_off_id}")
        
        return jsonify({'success': True, 'message': 'İzin silindi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"delete_time_off hatası: {e}")
        return jsonify({'success': False, 'message': 'İzin silinemedi'}), 500
    finally:
        release_db_connection(conn)


STAFF_COMMISSION_RATE = 0.50


def _staff_share_amount(full_price):
    """Personelin net kazancı — yapılan işin %50'si."""
    return round(float(full_price or 0) * STAFF_COMMISSION_RATE, 2)


@app.route('/api/admin/staff/<int:staff_id>/stats', methods=['GET'])
@token_required
def get_staff_stats(staff_id):
    """Personel istatistikleri - aylık gelir, müşteri sayısı, tamamlanan randevu gelirleri (super_admin)"""

    if not can_access_income():
        return jsonify({'success': False, 'message': 'Bu bilgilere erişim yetkiniz yok'}), 403
    
    month = request.args.get('month')
    year = request.args.get('year')
    
    if not month:
        month = datetime.now().month
    if not year:
        year = datetime.now().year
    
    month = int(month)
    year = int(year)
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Personel bilgilerini al
        cursor.execute("SELECT name, role, profile_photo FROM artists WHERE id = %s", (staff_id,))
        staff_info = cursor.fetchone()
        
        if not staff_info:
            cursor.close()
            return jsonify({'success': False, 'message': 'Personel bulunamadı'}), 404

        apply_commission = (staff_info[1] or '') != 'super_admin'
        
        # 2. Aylık istatistikler (dövme randevuları: appointments.price)
        cursor.execute("""
            SELECT
                COUNT(DISTINCT a.customer_id) as customer_count,
                COUNT(*) as appointment_count,
                COALESCE(SUM(a.price), 0) as total_income,
                COALESCE(SUM(a.duration_minutes), 0) as total_minutes
            FROM appointments a
            WHERE a.staff_id = %s
              AND a.status = 'completed'
              AND EXTRACT(MONTH FROM a.appointment_date) = %s
              AND EXTRACT(YEAR FROM a.appointment_date) = %s
        """, (staff_id, month, year))

        stats = cursor.fetchone()
        customer_count = int(stats[0] or 0)
        appointment_count = int(stats[1] or 0)
        total_income = float(stats[2] or 0)
        total_minutes = int(stats[3] or 0)
        staff_share_total = _staff_share_amount(total_income) if apply_commission else None

        # 3. Tamamlanan randevu gelir kalemleri
        cursor.execute("""
            SELECT
                a.id,
                a.appointment_date,
                a.appointment_time,
                a.price,
                COALESCE(c.name, ''),
                COALESCE(c.surname, '')
            FROM appointments a
            JOIN customers c ON a.customer_id = c.id
            WHERE a.staff_id = %s
              AND a.status = 'completed'
              AND EXTRACT(MONTH FROM a.appointment_date) = %s
              AND EXTRACT(YEAR FROM a.appointment_date) = %s
            ORDER BY a.appointment_date DESC, a.appointment_time DESC
        """, (staff_id, month, year))

        completed_revenue_items = []
        for row in cursor.fetchall():
            cust = f"{row[4]} {row[5]}".strip() or 'Müşteri'
            full_amount = float(row[3] or 0)
            item = {
                'appointment_id': row[0],
                'date': row[1].strftime('%d.%m.%Y'),
                'time': str(row[2])[:5],
                'amount': full_amount,
                'customer_name': cust,
            }
            if apply_commission:
                item['staff_share'] = _staff_share_amount(full_amount)
            completed_revenue_items.append(item)
        
        cursor.close()
        
        logger.info(f"Personel istatistikleri alındı: staff_id={staff_id}, {month}/{year}")
        
        return jsonify({
            'success': True,
            'staff': {
                'id': staff_id,
                'name': staff_info[0],
                'role': staff_info[1],
                'profile_photo': staff_info[2]
            },
            'month': month,
            'year': year,
            'stats': {
                'customer_count': customer_count,
                'appointment_count': appointment_count,
                'total_income': total_income,
                'staff_share_total': staff_share_total,
                'commission_percent': int(STAFF_COMMISSION_RATE * 100) if apply_commission else 0,
                'total_duration_minutes': total_minutes,
                'completed_revenue_items': completed_revenue_items,
            }
        })
    except Exception as e:
        logger.error(f"get_staff_stats hatası: {e}")
        return jsonify({'success': False, 'message': 'İstatistikler alınamadı'}), 500
    finally:
        release_db_connection(conn)


# =============================================
# HİZMET YÖNETİMİ
# =============================================

@app.route('/api/admin/services', methods=['GET'])
@token_required
def get_admin_services():
    """Tüm hizmetleri listele (aktif ve pasif)"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, price, duration_min, is_active 
            FROM services 
            ORDER BY name
        """)
        
        rows = cursor.fetchall()
        cursor.close()
        
        services = []
        for row in rows:
            services.append({
                'id': row[0],
                'name': row[1],
                'price': row[2],
                'duration_min': row[3],
                'is_active': row[4]
            })
        
        return jsonify({'success': True, 'services': services})
    except Exception as e:
        logger.error(f"get_admin_services hatası: {e}")
        return jsonify({'success': False, 'message': 'Hizmetler alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/services/<int:service_id>/staff', methods=['GET'])
@token_required
def get_service_staff(service_id):
    """Bir hizmetin atanmış personellerini getir"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT staff_id FROM staff_services WHERE service_id = %s
        """, (service_id,))
        
        rows = cursor.fetchall()
        cursor.close()
        
        staff_ids = [row[0] for row in rows]
        
        return jsonify({'success': True, 'staff_ids': staff_ids})
    except Exception as e:
        logger.error(f"get_service_staff hatası: {e}")
        return jsonify({'success': False, 'message': 'Personeller alınamadı'}), 500
    finally:
        release_db_connection(conn)

@app.route('/api/admin/services', methods=['POST'])
@token_required
def add_service():
    """Yeni hizmet ekle - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    data = request.get_json()
    name = data.get('name')
    price = data.get('price')
    duration_min = data.get('duration_min')
    staff_ids = data.get('staff_ids', [])  # Seçilen personeller
    
    if not name or not price or not duration_min:
        return jsonify({'success': False, 'message': 'Tüm alanlar gerekli'}), 400
    
    if not staff_ids or len(staff_ids) == 0:
        return jsonify({'success': False, 'message': 'En az bir personel seçmelisiniz'}), 400
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO services (name, price, duration_min, is_active)
            VALUES (%s, %s, %s, TRUE)
            RETURNING id
        """, (name, int(price), int(duration_min)))
        
        new_id = cursor.fetchone()[0]
        
        # Sadece SEÇİLEN personellere hizmeti ata
        for staff_id in staff_ids:
            cursor.execute("""
                INSERT INTO staff_services (staff_id, service_id, price)
                VALUES (%s, %s, %s)
            """, (int(staff_id), new_id, int(price)))
        
        conn.commit()
        cursor.close()
        
        logger.info(f"Yeni hizmet eklendi: {name} (id={new_id}), personeller: {staff_ids}")
        
        return jsonify({
            'success': True, 
            'message': 'Hizmet eklendi',
            'service_id': new_id
        })
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"add_service hatası: {e}")
        return jsonify({'success': False, 'message': 'Hizmet eklenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/services/<int:service_id>', methods=['PUT'])
@token_required
def update_service(service_id):
    """Hizmet güncelle (fiyat, isim, süre, aktiflik, personeller) - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    data = request.get_json()
    name = data.get('name')
    price = data.get('price')
    duration_min = data.get('duration_min')
    is_active = data.get('is_active')
    staff_ids = data.get('staff_ids')  # Yeni: Personel listesi
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Dinamik güncelleme
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = %s")
            params.append(name)
        if price is not None:
            updates.append("price = %s")
            params.append(int(price))
        if duration_min is not None:
            updates.append("duration_min = %s")
            params.append(int(duration_min))
        if is_active is not None:
            updates.append("is_active = %s")
            params.append(is_active)
        
        # Services tablosunu güncelle (eğer güncelleme varsa)
        if updates:
            params.append(service_id)
            query = f"UPDATE services SET {', '.join(updates)} WHERE id = %s"
            cursor.execute(query, params)
        
        # Personel ataması güncelle (staff_ids geldiyse)
        if staff_ids is not None:
            # Önce mevcut atamaları sil
            cursor.execute("DELETE FROM staff_services WHERE service_id = %s", (service_id,))
            
            # Yeni personelleri ekle
            # Fiyat: gönderilmişse onu kullan, yoksa mevcut services.price'ı al
            service_price = int(price) if price else None
            if service_price is None:
                cursor.execute("SELECT price FROM services WHERE id = %s", (service_id,))
                result = cursor.fetchone()
                service_price = result[0] if result else 0
            
            for staff_id in staff_ids:
                cursor.execute("""
                    INSERT INTO staff_services (staff_id, service_id, price)
                    VALUES (%s, %s, %s)
                """, (int(staff_id), service_id, service_price))
        
        conn.commit()
        cursor.close()
        
        logger.info(f"Hizmet güncellendi: id={service_id}, personeller={staff_ids}")
        
        return jsonify({'success': True, 'message': 'Hizmet güncellendi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_service hatası: {e}")
        return jsonify({'success': False, 'message': 'Hizmet güncellenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/services/<int:service_id>', methods=['DELETE'])
@token_required
def delete_service(service_id):
    """Hizmeti kalıcı olarak sil (hard delete) - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Önce bu hizmete bağlı randevuları sil (CASCADE)
        cursor.execute("DELETE FROM appointments WHERE service_id = %s", (service_id,))
        
        # Sonra staff_services ilişkilerini sil
        cursor.execute("DELETE FROM staff_services WHERE service_id = %s", (service_id,))
        
        # En son hizmeti kalıcı olarak sil
        cursor.execute("DELETE FROM services WHERE id = %s", (service_id,))
        conn.commit()
        cursor.close()
        
        logger.info(f"Hizmet kalıcı olarak silindi: id={service_id}")
        
        return jsonify({'success': True, 'message': 'Hizmet kalıcı olarak silindi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"delete_service hatası: {e}")
        return jsonify({'success': False, 'message': 'Hizmet silinemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/services/<int:service_id>/toggle-active', methods=['PATCH'])
@token_required
def toggle_service_active(service_id):
    """Hizmetin aktif/pasif durumunu değiştir - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkiniz yok'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Mevcut durumu al ve tersine çevir
        cursor.execute("UPDATE services SET is_active = NOT is_active WHERE id = %s RETURNING is_active", (service_id,))
        result = cursor.fetchone()
        
        if result is None:
            return jsonify({'success': False, 'message': 'Hizmet bulunamadı'}), 404
        
        new_status = result[0]
        conn.commit()
        cursor.close()
        
        status_text = 'aktif' if new_status else 'pasif'
        logger.info(f"Hizmet durumu değiştirildi: id={service_id}, is_active={new_status}")
        
        return jsonify({
            'success': True, 
            'message': f'Hizmet {status_text} yapıldı',
            'is_active': new_status
        })
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"toggle_service_active hatası: {e}")
        return jsonify({'success': False, 'message': 'Durum değiştirilemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/reports/income', methods=['GET'])
@token_required
def get_income_reports():
    """Aylık gelir raporu endpoint'i"""
    
    month = request.args.get('month')
    year = request.args.get('year')

    if not month:
        month = datetime.now().month 

    if not year: 
        year = datetime.now().year

    month = int(month)
    year = int(year)

    if not can_access_income():
        return jsonify({'success': False, 'message': 'Bu rapora erişim yetkiniz yok'}), 403

    query_params = [month, year]

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Tattoo demo build: no services/pricing model in DB.
        # We keep the income report active via:
        # - completed appointment count
        # - total booked minutes (duration_minutes)
        # - manual income adjustments (super_admin)

        query = """
            SELECT
                COUNT(*) as appointment_count,
                COALESCE(SUM(a.duration_minutes), 0) as total_minutes,
                COALESCE(SUM(a.price), 0) as appointment_income
            FROM appointments a
            WHERE a.status = 'completed'
              AND EXTRACT(MONTH FROM a.appointment_date) = %s
              AND EXTRACT(YEAR FROM a.appointment_date) = %s
        """
        cursor.execute(query, query_params)
        appointment_count, total_minutes, appointment_income = cursor.fetchone()
        appointment_count = int(appointment_count or 0)
        total_minutes = int(total_minutes or 0)
        appointment_income = float(appointment_income or 0)

        service_breakdown = []

        # Günlük trend: tamamlanan randevu sayısı + günlük gelir (₺)
        query = """
            SELECT
                a.appointment_date,
                COUNT(*) as cnt,
                COALESCE(SUM(a.price), 0) as daily_revenue
            FROM appointments a
            WHERE a.status = 'completed'
              AND EXTRACT(MONTH FROM a.appointment_date) = %s
              AND EXTRACT(YEAR FROM a.appointment_date) = %s
            GROUP BY a.appointment_date
            ORDER BY a.appointment_date
        """
        cursor.execute(query, query_params)
        rows = cursor.fetchall()
        daily_trend = [
            {
                'date': r[0].strftime('%d.%m.%Y'),
                'count': int(r[1] or 0),
                'income': float(r[2] or 0),
                'minutes': 0,
            }
            for r in rows
        ]

        # Tamamlanan randevu gelir kalemleri (liste)
        query = """
            SELECT
                a.id,
                a.appointment_date,
                a.appointment_time,
                a.price,
                COALESCE(c.name, ''),
                COALESCE(c.surname, ''),
                s.name as staff_name
            FROM appointments a
            JOIN customers c ON a.customer_id = c.id
            JOIN artists s ON a.staff_id = s.id
            WHERE a.status = 'completed'
              AND EXTRACT(MONTH FROM a.appointment_date) = %s
              AND EXTRACT(YEAR FROM a.appointment_date) = %s
            ORDER BY a.appointment_date DESC, a.appointment_time DESC
        """
        cursor.execute(query, query_params)
        completed_revenue_items = []
        for row in cursor.fetchall():
            cust = f"{row[4]} {row[5]}".strip() or 'Müşteri'
            completed_revenue_items.append({
                'appointment_id': row[0],
                'date': row[1].strftime('%d.%m.%Y'),
                'time': str(row[2])[:5],
                'amount': float(row[3] or 0),
                'customer_name': cust,
                'staff_name': row[6] or '',
            })

        # Manuel ayarlamalar (Randevu # ile otomatik eklenenler hariç — çift sayım olmasın)
        manual_adjustments = []
        manual_adjustments_total = 0

        if is_studio_admin():
            try:
                cursor.execute("""
                    SELECT 
                        ia.id,
                        ia.amount,
                        ia.type,
                        ia.description,
                        ia.adjustment_date,
                        s.name as created_by_name
                    FROM income_adjustments ia
                    LEFT JOIN artists s ON ia.created_by = s.id
                    WHERE EXTRACT(MONTH FROM ia.adjustment_date) = %s
                      AND EXTRACT(YEAR FROM ia.adjustment_date) = %s
                      AND (ia.description IS NULL OR ia.description NOT LIKE 'Randevu #%%')
                    ORDER BY ia.adjustment_date DESC
                """, (month, year))
            except Exception:
                cursor.execute("""
                    SELECT 
                        ia.id,
                        ia.amount,
                        NULL as adj_type,
                        ia.description,
                        ia.adjustment_date,
                        s.name as created_by_name
                    FROM income_adjustments ia
                    LEFT JOIN artists s ON ia.created_by = s.id
                    WHERE EXTRACT(MONTH FROM ia.adjustment_date) = %s
                      AND EXTRACT(YEAR FROM ia.adjustment_date) = %s
                      AND (ia.description IS NULL OR ia.description NOT LIKE 'Randevu #%%')
                    ORDER BY ia.adjustment_date DESC
                """, (month, year))

            for row in cursor.fetchall():
                sign = 1 if (row[2] or 'income') == 'income' else -1
                manual_adjustments.append({
                    'id': row[0],
                    'amount': float(row[1]),
                    'type': row[2] or 'income',
                    'description': row[3],
                    'date': row[4].strftime('%d.%m.%Y'),
                    'created_by_name': row[5] or 'Bilinmiyor',
                })
                manual_adjustments_total += float(row[1]) * sign

        cursor.close()

        total_income = appointment_income + float(manual_adjustments_total)
        
        logger.info(f"Gelir raporu alındı: {month}/{year}")
        
        return jsonify({
            'success': True,
            'month': month,
            'year': year,
            'total_income': total_income,
            'appointment_income': appointment_income,
            'total_duration_minutes': total_minutes,
            'manual_adjustments_total': manual_adjustments_total,
            'appointment_count': appointment_count,
            'total_minutes': total_minutes,
            'service_breakdown': service_breakdown,
            'daily_trend': daily_trend,
            'manual_adjustments': manual_adjustments,
            'completed_revenue_items': completed_revenue_items,
        })
        
    except Exception as e:
        logger.error(f"get_income_reports hatası: {e}")
        return jsonify({'success': False, 'message': 'Rapor alınamadı'}), 500
    finally:
        release_db_connection(conn)


# =============================================
# MANUEL GELİR AYARLAMALARI - INCOME ADJUSTMENTS
# =============================================

@app.route('/api/admin/income-adjustments', methods=['POST'])
@token_required
def add_income_adjustment():
    """Manuel gelir ayarlaması ekle - SADECE SUPER_ADMIN"""
    
    # Sadece super_admin ekleyebilir
    if not can_access_income():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    data = request.get_json()
    amount          = data.get('amount')
    description     = data.get('description')
    adjustment_date = data.get('date') or data.get('adjustment_date')
    adj_type        = data.get('type', 'income')

    # Validasyon
    if not all([amount, description]):
        return jsonify({'success': False, 'message': 'Tutar ve açıklama zorunlu'}), 400
    
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Geçersiz miktar'}), 400
    
    if not description.strip():
        return jsonify({'success': False, 'message': 'Açıklama boş olamaz'}), 400

    if not adjustment_date:
        from datetime import date as _date
        adjustment_date = str(_date.today())
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO income_adjustments (amount, type, description, adjustment_date, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, amount, description, adjustment_date, created_at
        """, (amount, adj_type, description, adjustment_date, request.staff_id))
        
        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        
        adjustment = {
            'id': result[0],
            'amount': float(result[1]),
            'description': result[2],
            'adjustment_date': result[3].strftime('%Y-%m-%d'),
            'created_at': result[4].isoformat()
        }
        
        logger.info(f"Gelir ayarlaması eklendi: {result[0]} by staff {request.staff_id}")
        
        return jsonify({
            'success': True,
            'message': 'Gelir ayarlaması başarıyla eklendi',
            'adjustment': adjustment
        })
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"add_income_adjustment hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlama eklenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/income-adjustments', methods=['GET'])
@token_required
def get_income_adjustments():
    """Belirli bir ay/yıldaki gelir ayarlamalarını listele - SADECE SUPER_ADMIN"""
    
    # Sadece super_admin görebilir
    if not can_access_income():
        return jsonify({'success': False, 'message': 'Bu rapora erişim yetkiniz yok'}), 403
    
    month = request.args.get('month')
    year = request.args.get('year')
    
    if not month:
        month = datetime.now().month
    if not year:
        year = datetime.now().year
    
    month = int(month)
    year = int(year)
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                ia.id,
                ia.amount,
                ia.description,
                ia.adjustment_date,
                s.name as created_by_name,
                ia.created_at
            FROM income_adjustments ia
            LEFT JOIN artists s ON ia.created_by = s.id
            WHERE EXTRACT(MONTH FROM ia.adjustment_date) = %s
              AND EXTRACT(YEAR FROM ia.adjustment_date) = %s
            ORDER BY ia.adjustment_date DESC, ia.created_at DESC
        """, (month, year))
        
        rows = cursor.fetchall()
        adjustments = []
        total_adjustments = 0
        
        for row in rows:
            adjustment = {
                'id': row[0],
                'amount': float(row[1]),
                'description': row[2],
                'adjustment_date': row[3].strftime('%d.%m.%Y'),
                'created_by_name': row[4] or 'Bilinmiyor',
                'created_at': row[5].isoformat()
            }
            adjustments.append(adjustment)
            total_adjustments += float(row[1])
        
        cursor.close()
        
        logger.info(f"Gelir ayarlamaları listelendi: {month}/{year}")
        
        return jsonify({
            'success': True,
            'adjustments': adjustments,
            'total_adjustments': total_adjustments,
            'month': month,
            'year': year
        })
        
    except Exception as e:
        logger.error(f"get_income_adjustments hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlamalar alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/income-adjustments/<int:adjustment_id>', methods=['DELETE'])
@token_required
def delete_income_adjustment(adjustment_id):
    """Gelir ayarlamasını sil - SADECE SUPER_ADMIN"""
    
    # Sadece super_admin silebilir
    if not can_access_income():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Önce kayıt var mı kontrol et
        cursor.execute("SELECT id FROM income_adjustments WHERE id = %s", (adjustment_id,))
        if not cursor.fetchone():
            cursor.close()
            return jsonify({'success': False, 'message': 'Ayarlama bulunamadı'}), 404
        
        cursor.execute("DELETE FROM income_adjustments WHERE id = %s", (adjustment_id,))
        conn.commit()
        cursor.close()
        
        logger.info(f"Gelir ayarlaması silindi: {adjustment_id} by staff {request.staff_id}")
        
        return jsonify({
            'success': True,
            'message': 'Gelir ayarlaması başarıyla silindi'
        })
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"delete_income_adjustment hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlama silinemedi'}), 500
    finally:
        release_db_connection(conn)



@app.route('/api/admin/me', methods=['GET'])
@token_required
def get_admin_me():
    """Giriş yapmış personelin profil bilgileri."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, phone, role, profile_photo, instagram_url
            FROM artists WHERE id = %s
            """,
            (request.staff_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return jsonify({'success': False, 'message': 'Kullanıcı bulunamadı'}), 404
        return jsonify({
            'success': True,
            'staff': {
                'id': row[0],
                'name': row[1],
                'phone': row[2],
                'role': row[3],
                'profile_photo': row[4],
                'instagram_url': row[5] or '',
            },
        })
    except Exception as e:
        logger.error(f"get_admin_me hatası: {e}")
        return jsonify({'success': False, 'message': 'Profil alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/my-profile', methods=['PATCH'])
@token_required
def update_my_profile():
    """Personel kendi profil alanlarını günceller (Instagram linki vb.)."""
    data = request.get_json() or {}
    if 'instagram_url' not in data:
        return jsonify({'success': False, 'message': 'Güncellenecek alan yok'}), 400

    raw_ig = data.get('instagram_url')
    instagram_url = None
    if raw_ig is not None and str(raw_ig).strip():
        instagram_url = normalize_instagram_url(raw_ig)
        if not instagram_url:
            return jsonify({'success': False, 'message': 'Geçerli bir Instagram kullanıcı adı veya linki girin'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE artists SET instagram_url = %s WHERE id = %s",
            (instagram_url, request.staff_id),
        )
        conn.commit()
        cursor.close()
        logger.info(f"Profil güncellendi: staff_id={request.staff_id}, instagram_url={instagram_url}")
        return jsonify({
            'success': True,
            'message': 'Instagram linki kaydedildi',
            'instagram_url': instagram_url or '',
        })
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_my_profile hatası: {e}")
        return jsonify({'success': False, 'message': 'Profil güncellenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/change-password', methods=['POST'])
@token_required
def change_password():
    data = request.get_json() or {}
    eski_sifre = (data.get('old_password') or '').strip()
    yeni_sifre = (data.get('new_password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()

    if not eski_sifre or not yeni_sifre or not confirm_password:
        return jsonify({'success': False, 'message': 'Tüm alanlar gerekli'}), 400

    if yeni_sifre != confirm_password:
        return jsonify({'success': False, 'message': 'Yeni şifreler eşleşmiyor'}), 400

    if len(yeni_sifre) < 6:
        return jsonify({'success': False, 'message': 'Şifre en az 6 karakter olmalı'}), 400

    if passwords_too_similar(eski_sifre, yeni_sifre):
        return jsonify({'success': False, 'message': 'Yeni şifre mevcut şifre ile aynı veya çok benzer olamaz'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM artists WHERE id = %s", (request.staff_id,))
        staff = cursor.fetchone()

        # Kullanıcı bulunamadı kontrolü
        if not staff: 
            cursor.close()
            return jsonify({'success': False, 'message': 'Kullanıcı bulunamadı'}), 400
        
        stored_hash = staff[0]

        # Eski şifre doğru mu?
        if not verify_password(eski_sifre, stored_hash):
            cursor.close()
            return jsonify({'success': False, 'message': 'Mevcut şifre yanlış'}), 400

        # Yeni şifreyi hash'le ve güncelle
        new_hash = hash_password_bcrypt(yeni_sifre)
        cursor.execute("UPDATE artists SET password = %s WHERE id = %s", (new_hash, request.staff_id))
        conn.commit()
        cursor.close()
        
        logger.info(f"Şifre değiştirildi: staff_id={request.staff_id}")
        return jsonify({'success': True, 'message': 'Şifre başarıyla değiştirildi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"change_password hatası: {e}")
        return jsonify({'success': False, 'message': 'Şifre değiştirilemedi'}), 500
    finally:
        release_db_connection(conn)


# =============================================
# WAPIO API AYARLARI (Super Admin Only)
# =============================================

@app.route('/api/admin/wapio-settings', methods=['GET'])
@token_required
def get_wapio_settings():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    if not WAPIO_INTEGRATION_ENABLED:
        return _wapio_disabled_json()


@app.route('/api/admin/wapio-settings', methods=['PUT'])
@token_required
def update_wapio_settings():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    if not WAPIO_INTEGRATION_ENABLED:
        return _wapio_disabled_json()


@app.route('/api/admin/wapio/create-device', methods=['POST'])
@token_required
def admin_wapio_create_device():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    if not WAPIO_INTEGRATION_ENABLED:
        return _wapio_disabled_json()


@app.route('/api/admin/wapio/qr', methods=['POST'])
@token_required
def admin_wapio_qr():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    if not WAPIO_INTEGRATION_ENABLED:
        return _wapio_disabled_json()


@app.route('/api/admin/wapio/session-status', methods=['GET'])
@token_required
def admin_wapio_session_status():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    if not WAPIO_INTEGRATION_ENABLED:
        return _wapio_disabled_json()


@app.route('/api/admin/wapio/update-webhook', methods=['POST'])
@token_required
def admin_wapio_update_webhook():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    if not WAPIO_INTEGRATION_ENABLED:
        return _wapio_disabled_json()


@app.route('/api/admin/wapio-compat-check', methods=['GET'])
@token_required
def admin_wapio_compat_check():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    if not WAPIO_INTEGRATION_ENABLED:
        return _wapio_disabled_json()


@app.route('/api/admin/wapio-contract', methods=['GET'])
@token_required
def admin_wapio_contract():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    if not WAPIO_INTEGRATION_ENABLED:
        return _wapio_disabled_json()


# =============================================
# WHATSAPP SAĞLAYICI + EVOLUTION API (Super Admin)
# =============================================

@app.route('/api/admin/whatsapp/provider', methods=['GET'])
@token_required
def admin_whatsapp_provider():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    provider = get_whatsapp_provider()
    return jsonify({
        'success': True,
        'provider': provider,
        'wapio_active': provider == 'wapio',
        'evolution_active': provider == 'evolution',
    })


@app.route('/api/admin/evolution-settings', methods=['GET'])
@token_required
def get_evolution_settings():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    cfg = get_evolution_config()
    return jsonify({
        'success': True,
        'settings': {
            'api_url': cfg.get('api_url', ''),
            'api_key': cfg.get('api_key', ''),
            'instance_name': cfg.get('instance_name', ''),
            'welcome_message_enabled': bool(cfg.get('welcome_message_enabled', True)),
            'otp_keyboard_hint_enabled': bool(cfg.get('otp_keyboard_hint_enabled', True)),
        },
    })


@app.route('/api/admin/evolution-settings', methods=['PUT'])
@token_required
def update_evolution_settings():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    data = request.get_json() or {}
    cfg = get_evolution_config()
    api_key = (data.get('api_key') or '').strip() or (cfg.get('api_key') or '').strip()
    instance_name = (
        (data.get('instance_name') or data.get('session_id') or '').strip()
        or (cfg.get('instance_name') or '').strip()
    )
    api_url = (data.get('api_url') or '').strip() or cfg.get('api_url') or None
    welcome_message_enabled = data.get('welcome_message_enabled')
    if welcome_message_enabled is not None:
        welcome_message_enabled = bool(welcome_message_enabled)
    otp_keyboard_hint_enabled = data.get('otp_keyboard_hint_enabled')
    if otp_keyboard_hint_enabled is not None:
        otp_keyboard_hint_enabled = bool(otp_keyboard_hint_enabled)
    if not api_key:
        return jsonify({'success': False, 'message': 'Evolution API Key gereklidir (.env veya panel)'}), 400
    if not instance_name:
        return jsonify({'success': False, 'message': 'Instance name gereklidir (.env veya panel)'}), 400
    try:
        save_evolution_config(
            api_key,
            instance_name,
            api_url=api_url,
            welcome_message_enabled=welcome_message_enabled,
            otp_keyboard_hint_enabled=otp_keyboard_hint_enabled,
        )
        saved = get_evolution_config()
        return jsonify({
            'success': True,
            'message': 'Evolution API ayarları kaydedildi',
            'settings': {
                'welcome_message_enabled': bool(saved.get('welcome_message_enabled', True)),
                'otp_keyboard_hint_enabled': bool(saved.get('otp_keyboard_hint_enabled', True)),
            },
        })
    except Exception as e:
        logger.error(f"update_evolution_settings hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlar kaydedilemedi'}), 500


@app.route('/api/admin/evolution/create-instance', methods=['POST'])
@token_required
def admin_evolution_create_instance():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    data = request.get_json() or {}
    cfg = get_evolution_config()
    instance_name = (data.get('instance_name') or data.get('device_name') or cfg.get('instance_name') or '').strip()
    if not instance_name:
        return jsonify({'success': False, 'message': 'Instance name gerekli'}), 400
    status, body, raw = evolution_create_instance(instance_name, cfg)
    saved_name = extract_instance_name_from_response(body if isinstance(body, dict) else None) or instance_name
    if saved_name and cfg.get('api_key'):
        save_evolution_config(
            cfg.get('api_key', ''),
            saved_name,
            api_url=cfg.get('api_url'),
            welcome_message_enabled=cfg.get('welcome_message_enabled', True),
        )
    qr_image = evolution_extract_qr_image(body if isinstance(body, dict) else None, raw)
    return jsonify({
        'success': 200 <= status < 300,
        'http_status': status,
        'instance_name': saved_name,
        'session_id': saved_name,
        'qr_image': qr_image,
        'response': body,
    }), (200 if 200 <= status < 300 else 502)


@app.route('/api/admin/evolution/connect', methods=['POST'])
@token_required
def admin_evolution_connect():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    data = request.get_json() or {}
    cfg = get_evolution_config()
    instance_name = (data.get('instance_name') or data.get('session_id') or cfg.get('instance_name') or '').strip()
    if not instance_name:
        return jsonify({'success': False, 'message': 'Instance name gerekli'}), 400
    status, body, raw = evolution_connect_instance(instance_name, cfg)
    qr_image = evolution_extract_qr_image(body if isinstance(body, dict) else None, raw)
    return jsonify({
        'success': 200 <= status < 300,
        'http_status': status,
        'qr_image': qr_image,
        'response': body,
    }), (200 if 200 <= status < 300 else 502)


@app.route('/api/admin/evolution/session-status', methods=['GET'])
@token_required
def admin_evolution_session_status():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    cfg = get_evolution_config()
    instance_name = (cfg.get('instance_name') or '').strip()
    api_key = (cfg.get('api_key') or '').strip()
    if not api_key or not instance_name:
        info = evolution_interpret_connection_status(0, None, '')
        return jsonify({'success': True, 'http_status': 0, 'connected': False, 'connection': info})
    info = resolve_evolution_connection(cfg, instance_name)
    return jsonify({
        'success': True,
        'http_status': 200,
        'connected': info.get('connected', False),
        'connection': info,
    })


@app.route('/api/admin/evolution/update-webhook', methods=['POST'])
@token_required
def admin_evolution_update_webhook():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    data = request.get_json() or {}
    cfg = get_evolution_config()
    instance_name = (data.get('instance_name') or data.get('session_id') or cfg.get('instance_name') or '').strip()
    webhook = (data.get('webhook') or '').strip() or get_webhook_url()
    if not instance_name or not webhook:
        return jsonify({'success': False, 'message': 'instance_name ve webhook gerekli'}), 400
    status, body, raw = evolution_set_webhook(instance_name, webhook, cfg)
    return jsonify({
        'success': 200 <= status < 300,
        'http_status': status,
        'response': body,
        'webhook': webhook,
    })


@app.route('/api/admin/private-zone-settings', methods=['GET'])
@token_required
def get_admin_private_zone_settings():
    """Özel bölge randevu pencereleri ayarları."""
    try:
        pz = get_private_zone_settings()
        private_regions = [
            {'id': k, 'label': v['label']}
            for k, v in BODY_REGIONS.items()
            if v.get('private')
        ]
        return jsonify({
            'success': True,
            'private_zone': pz,
            'day_names': PRIVATE_ZONE_DAY_NAMES,
            'private_regions': private_regions,
        })
    except Exception as e:
        logger.error(f"get_admin_private_zone_settings hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlar alınamadı'}), 500


@app.route('/api/admin/private-zone-settings', methods=['PUT'])
@token_required
def update_admin_private_zone_settings():
    """Özel bölge randevu pencerelerini güncelle — yalnızca super_admin."""
    if not is_studio_admin():
        return jsonify({
            'success': False,
            'message': 'Özel bölge saatlerini yalnızca Super Admin düzenleyebilir',
        }), 403

    data = request.get_json() or {}
    try:
        enabled = data.get('enabled', True)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ('1', 'true', 'yes', 'on')
        days_in = data.get('days')
        if not isinstance(days_in, list) or len(days_in) != 2:
            return jsonify({
                'success': False,
                'message': 'Tam olarak 2 gün ve saat aralığı tanımlanmalıdır',
            }), 400

        seen_days = set()
        normalized = []
        for item in days_in:
            if not isinstance(item, dict):
                return jsonify({'success': False, 'message': 'Geçersiz gün ayarı'}), 400
            try:
                dow = int(item.get('day_of_week'))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Geçersiz gün seçimi'}), 400
            if dow < 0 or dow > 6:
                return jsonify({'success': False, 'message': 'Gün 0-6 arasında olmalı'}), 400
            if dow in seen_days:
                return jsonify({'success': False, 'message': 'Aynı gün iki kez seçilemez'}), 400
            seen_days.add(dow)
            start_time = str(item.get('start_time') or '')[:5]
            end_time = str(item.get('end_time') or '')[:5]
            if _time_str_to_minutes(start_time) >= _time_str_to_minutes(end_time):
                return jsonify({'success': False, 'message': 'Bitiş saati başlangıçtan sonra olmalı'}), 400
            normalized.append({
                'day_of_week': dow,
                'start_time': start_time,
                'end_time': end_time,
            })

        private_zone = {'enabled': bool(enabled), 'days': normalized}
        save_private_zone_settings(private_zone)
        logger.info(f"Özel bölge ayarları güncellendi by staff_id={request.staff_id}")
        return jsonify({
            'success': True,
            'message': 'Özel bölge randevu saatleri kaydedildi',
            'private_zone': private_zone,
        })
    except Exception as e:
        logger.error(f"update_admin_private_zone_settings hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlar kaydedilemedi'}), 500


@app.route('/api/admin/site-settings', methods=['GET'])
@token_required
def get_site_settings_endpoint():
    """Site ayarlarını (logo, banner vb.) al"""
    try:
        settings = get_site_settings()
        return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        logger.error(f"get_site_settings_endpoint hatası: {e}")
        return jsonify({'success': False, 'message': 'Site ayarları alınamadı'}), 500


@app.route('/api/admin/site-settings', methods=['PUT'])
@token_required
def update_site_settings_endpoint():
    """Site ayarlarını güncelle - SADECE SUPER_ADMIN"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    
    data = request.get_json()
    try:
        settings = get_site_settings()
        
        # Sadece izin verilen alanları güncelle
        if 'banner_image' in data:
            settings['banner_image'] = data['banner_image']
        if 'logo_image' in data:
            settings['logo_image'] = data['logo_image']
            
        save_site_settings(settings)
        logger.info(f"Site ayarları güncellendi by staff_id={request.staff_id}")
        return jsonify({'success': True, 'message': 'Site ayarları kaydedildi'})
    except Exception as e:
        logger.error(f"update_site_settings_endpoint hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlar kaydedilemedi'}), 500


@app.route('/api/site-settings', methods=['GET'])
def get_public_site_settings():
    """Giriş gerektirmeyen herkese açık site ayarlarını al"""
    try:
        settings = get_site_settings()
        return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        logger.error(f"get_public_site_settings hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlar alınamadı'}), 500


@app.route('/api/admin/google-calendar-settings', methods=['GET'])
@token_required
def get_google_calendar_settings():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    cfg = get_google_calendar_config()
    probe = None
    if cfg.get('calendar_id') and credentials_file_ok():
        probe = probe_google_calendar(cfg.get('calendar_id'))
    return jsonify({
        'success': True,
        'settings': {
            'enabled': bool(cfg.get('enabled')),
            'calendar_id': cfg.get('calendar_id') or '',
            'timezone': cfg.get('timezone') or 'Europe/Istanbul',
            'credentials_ok': credentials_file_ok(),
            'service_account_email': get_service_account_email() or '',
            'sync_active': is_google_calendar_enabled(),
            'calendar_summary': (probe or {}).get('summary') or '',
            'connected': bool(probe and probe.get('ok')),
            'probe_message': (probe or {}).get('message') or '',
        },
        'calendars': list_accessible_calendars(),
    })


@app.route('/api/admin/google-calendar-settings', methods=['PUT'])
@token_required
def update_google_calendar_settings():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    data = request.get_json() or {}
    calendar_id = data.get('calendar_id')
    enabled = data.get('enabled')
    timezone = data.get('timezone')
    try:
        save_google_calendar_config(
            calendar_id=calendar_id if calendar_id is not None else None,
            enabled=enabled if enabled is not None else None,
            timezone=timezone if timezone is not None else None,
        )
        cfg = get_google_calendar_config()
        probe = probe_google_calendar(cfg.get('calendar_id')) if cfg.get('calendar_id') and credentials_file_ok() else None
        logger.info(
            'Google Calendar ayarları güncellendi by staff_id=%s calendar_id=%s enabled=%s',
            request.staff_id,
            cfg.get('calendar_id'),
            cfg.get('enabled'),
        )
        return jsonify({
            'success': True,
            'message': 'Google Takvim ayarları kaydedildi',
            'settings': {
                'enabled': bool(cfg.get('enabled')),
                'calendar_id': cfg.get('calendar_id') or '',
                'timezone': cfg.get('timezone') or 'Europe/Istanbul',
                'sync_active': is_google_calendar_enabled(),
                'connected': bool(probe and probe.get('ok')),
                'calendar_summary': (probe or {}).get('summary') or '',
                'probe_message': (probe or {}).get('message') or '',
            },
        })
    except Exception as e:
        logger.error(f"update_google_calendar_settings hatası: {e}")
        return jsonify({'success': False, 'message': 'Ayarlar kaydedilemedi'}), 500


@app.route('/api/admin/google-calendar-settings/test', methods=['POST'])
@token_required
def test_google_calendar_settings():
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Bu işlem için yetkiniz yok'}), 403
    data = request.get_json() or {}
    calendar_id = (data.get('calendar_id') or '').strip() or None
    result = probe_google_calendar(calendar_id)
    return jsonify({
        'success': bool(result.get('ok')),
        'message': result.get('message') or ('Bağlantı başarılı' if result.get('ok') else 'Bağlantı başarısız'),
        'calendar': {
            'id': result.get('calendar_id') or '',
            'summary': result.get('summary') or '',
            'time_zone': result.get('time_zone') or '',
        } if result.get('ok') else None,
    }), (200 if result.get('ok') else 400)


# =============================================
# RANDEVU HATIRLATMA SİSTEMİ
# =============================================

def send_appointment_reminders():
    """1 saat içinde başlayacak randevulara hatırlatma mesajı gönder
    
    Race condition önleme:
    - SELECT FOR UPDATE ile atomic işlem
    - Mesaj göndermeden ÖNCE reminder_sent flag'ini güncelle
    - Her randevu için sadece 1 kez mesaj gönderilmesini garanti eder
    """
    conn = None
    try:
        conn = get_db_connection()
        
        # Transaction başlat (atomic işlem için)
        conn.autocommit = False
        cursor = conn.cursor()
        
        reminder_hours = get_reminder_hours_before()
        now = datetime.now()
        reminder_until = now + timedelta(hours=reminder_hours)
        
        # Bugünün tarihi
        today = now.date()
        current_time = now.strftime('%H:%M')
        reminder_until_time = reminder_until.strftime('%H:%M')
        
        # X saat içinde başlayacak, onaylanmış ve henüz hatırlatma gönderilmemiş randevular
        # SELECT FOR UPDATE: Aynı anda birden fazla worker aynı randevuyu işlemesin
        cursor.execute("""
            SELECT 
                a.id, a.appointment_date, a.appointment_time,
                c.phone, c.name, c.surname,
                COALESCE(tr.body_area, '-') as body_area,
                COALESCE(tr.size, '-') as tattoo_size,
                st.name as staff_name
            FROM appointments a
            JOIN customers c ON a.customer_id = c.id
            LEFT JOIN tattoo_requests tr ON a.tattoo_request_id = tr.id
            JOIN artists st ON a.staff_id = st.id
            WHERE a.status = 'confirmed'
              AND a.appointment_date = %s
              AND a.appointment_time > %s
              AND a.appointment_time <= %s
              AND (a.reminder_sent IS NULL OR a.reminder_sent = FALSE)
            FOR UPDATE OF a SKIP LOCKED
        """, (today, current_time, reminder_until_time))
        
        appointments = cursor.fetchall()
        
        sent_count = 0
        for apt in appointments:
            apt_id, apt_date, apt_time, phone, name, surname, body_area, tattoo_size, staff_name = apt
            
            try:
                # ÖNCE reminder_sent flag'ini güncelle (race condition önleme)
                # Bu sayede başka bir worker aynı randevuyu işlemez
                cursor.execute("UPDATE appointments SET reminder_sent = TRUE WHERE id = %s AND (reminder_sent IS NULL OR reminder_sent = FALSE)", (apt_id,))
                
                # Eğer UPDATE başarılı olduysa (1 row affected), mesaj gönder
                if cursor.rowcount > 0:
                    message = build_appointment_reminder_message(
                        f'{name} {surname}'.strip(),
                        apt_date.strftime('%d.%m.%Y'),
                        str(apt_time)[:5],
                        body_area,
                        tattoo_size,
                        staff_name,
                        hours_before=reminder_hours,
                    )
                    
                    send_wapio_message(phone, message)
                    sent_count += 1
                    logger.info(f"Hatırlatma gönderildi: {phone} - {apt_date} {apt_time}")
                else:
                    # Başka bir worker zaten bu randevuyu işlemiş
                    logger.info(
                        "Hatirlatma atlandi (zaten gonderilmis) | phone=%s date=%s time=%s",
                        phone,
                        apt_date,
                        apt_time,
                    )
                
            except Exception as e:
                log_error(logger, E_WA_004, "Randevu hatirlatmasi gonderilemedi", exc=e, phone=phone)
                # Hata durumunda reminder_sent'i geri al (rollback için)
                cursor.execute("UPDATE appointments SET reminder_sent = FALSE WHERE id = %s", (apt_id,))
        
        # Transaction'ı commit et
        conn.commit()
        cursor.close()
        
        if sent_count > 0:
            logger.info(f"{sent_count} randevu hatırlatması gönderildi")
        elif appointments:
            logger.info("%s randevu bulundu ama hepsi zaten islenmis", len(appointments))
            
    except Exception as e:
        if conn:
            conn.rollback()
        log_error(logger, E_WA_004, "Randevu hatirlatmalari calistirilamadi", exc=e)
    finally:
        if conn:
            conn.autocommit = True
        release_db_connection(conn)


AFTERCARE_REMINDER_HOURS = float(os.getenv('AFTERCARE_REMINDER_HOURS', '2'))


def send_aftercare_cream_reminders():
    """Tamamlanan randevulardan 2 saat sonra krem bakım hatırlatması (WhatsApp)."""
    conn = None
    try:
        conn = get_db_connection()
        conn.autocommit = False
        cursor = conn.cursor()

        delay_hours = max(0.5, AFTERCARE_REMINDER_HOURS)
        cutoff = datetime.now() - timedelta(hours=delay_hours)

        cursor.execute("""
            SELECT
                a.id,
                c.phone,
                COALESCE(c.name, ''),
                COALESCE(c.surname, ''),
                s.name as staff_name,
                a.completed_at
            FROM appointments a
            JOIN customers c ON a.customer_id = c.id
            JOIN artists s ON a.staff_id = s.id
            WHERE a.status = 'completed'
              AND a.completed_at IS NOT NULL
              AND a.completed_at <= %s
              AND (a.aftercare_reminder_sent IS NULL OR a.aftercare_reminder_sent = FALSE)
            FOR UPDATE OF a SKIP LOCKED
        """, (cutoff,))

        rows = cursor.fetchall()

        sent_count = 0
        for apt_id, phone, name, surname, staff_name, completed_at in rows:
            try:
                cursor.execute(
                    """
                    UPDATE appointments
                    SET aftercare_reminder_sent = TRUE
                    WHERE id = %s
                      AND (aftercare_reminder_sent IS NULL OR aftercare_reminder_sent = FALSE)
                    """,
                    (apt_id,),
                )
                if cursor.rowcount <= 0:
                    continue

                customer_name = f"{name} {surname}".strip() or 'Müşterimiz'
                message = build_aftercare_reminder_message(customer_name, staff_name)

                send_wapio_message(phone, message)
                sent_count += 1
                logger.info(
                    "Krem bakim hatirlatmasi gonderildi | phone=%s appointment_id=%s completed_at=%s",
                    phone,
                    apt_id,
                    completed_at,
                )
            except Exception as send_err:
                log_error(
                    logger,
                    E_WA_004,
                    "Krem bakim hatirlatmasi gonderilemedi",
                    exc=send_err,
                    appointment_id=apt_id,
                )
                cursor.execute(
                    "UPDATE appointments SET aftercare_reminder_sent = FALSE WHERE id = %s",
                    (apt_id,),
                )

        conn.commit()
        cursor.close()
        if sent_count > 0:
            logger.info(f"{sent_count} krem bakım hatırlatması gönderildi")
    except Exception as e:
        if conn:
            conn.rollback()
        log_error(logger, E_WA_004, "Krem bakim hatirlatmalari calistirilamadi", exc=e)
    finally:
        if conn:
            conn.autocommit = True
        release_db_connection(conn)


def create_database_backup():
    """PostgreSQL veritabanını yedekler (scheduler için)"""
    import subprocess
    import glob
    
    # Backup klasörü
    BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
    KEEP_DAYS = 7  # Kaç günlük yedek tutulsun
    
    # Backup klasörünü oluştur
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        logger.info(f"Backup klasörü oluşturuldu: {BACKUP_DIR}")
    
    # Dosya adı: backup_2024-12-28_02-00-00.sql
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    backup_filename = f"backup_{timestamp}.sql"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    
    # Veritabanı bilgileri
    db_config = DATABASE_CONFIG
    db_host = db_config['host']
    db_port = db_config['port']
    db_name = db_config['database']
    db_user = db_config['user']
    db_password = db_config['password']
    
    # pg_dump yolunu bul (PATH'te olmayabilir, common path'lerde ara)
    import shutil
    pg_dump_path = shutil.which('pg_dump')
    
    if not pg_dump_path:
        # Common PostgreSQL bin path'lerini dene
        common_paths = [
            '/usr/bin/pg_dump',
            '/usr/local/bin/pg_dump',
            '/usr/lib/postgresql/14/bin/pg_dump',
            '/usr/lib/postgresql/13/bin/pg_dump',
            '/usr/lib/postgresql/12/bin/pg_dump',
            '/usr/lib/postgresql/15/bin/pg_dump',
            '/opt/PostgreSQL/14/bin/pg_dump',
            '/opt/PostgreSQL/15/bin/pg_dump',
        ]
        
        for path in common_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                pg_dump_path = path
                logger.info(f"pg_dump bulundu: {pg_dump_path}")
                break
    
    if not pg_dump_path:
        log_error(logger, E_BKP_001, "pg_dump bulunamadi; PostgreSQL client tools yuklu olmali")
        return False
    
    # pg_dump komutu
    pg_dump_cmd = [
        pg_dump_path,
        '-h', db_host,
        '-p', str(db_port),
        '-U', db_user,
        '-d', db_name,
        '-f', backup_path,
        '--no-password'
    ]
    
    # PGPASSWORD ortam değişkeni ile şifre geç
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password
    
    try:
        logger.info(f"Veritabanı yedekleme başlıyor: {db_name}")
        logger.info(f"   pg_dump: {pg_dump_path}")
        result = subprocess.run(
            pg_dump_cmd,
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            file_size = os.path.getsize(backup_path) / (1024 * 1024)  # MB
            logger.info(f"Veritabanı yedekleme tamamlandı!")
            logger.info(f"Dosya: {backup_filename}")
            logger.info(f"Boyut: {file_size:.2f} MB")
            
            # Google Drive'a yükle (rclone ile)
            upload_to_google_drive(backup_path, backup_filename)
            
            # Eski yedekleri temizle
            cleanup_old_database_backups(BACKUP_DIR, KEEP_DAYS)
            
            return True
        else:
            log_error(logger, E_BKP_001, "Veritabani yedekleme basarisiz", stderr=result.stderr)
            if result.stdout:
                logger.error("pg_dump ciktisi | stdout=%s", result.stdout[:500])
            return False
            
    except FileNotFoundError:
        log_error(logger, E_BKP_001, "pg_dump bulunamadi", path=pg_dump_path)
        return False
    except Exception as e:
        log_error(logger, E_BKP_001, "Veritabani yedekleme hatasi", exc=e)
        return False


def upload_to_google_drive(backup_path, backup_filename):
    """Backup dosyasını Google Drive'a yükle (rclone ile)"""
    import subprocess
    
    # Rclone remote adı ve Google Drive klasörü
    # .env'den al, yoksa 'sefadrive' varsayılan (kullanıcının remote adı)
    RCLONE_REMOTE = os.getenv('RCLONE_REMOTE', 'sefadrive')
    GDRIVE_FOLDER = 'Randevu_Yedekleri'  # Google Drive'daki klasör adı
    
    try:
        # Önce rclone'un kurulu olup olmadığını kontrol et (PATH'te olmayabilir)
        import shutil
        rclone_path = shutil.which('rclone')
        
        if not rclone_path:
            # Common rclone path'lerini dene
            common_paths = [
                '/usr/bin/rclone',
                '/usr/local/bin/rclone',
                '/usr/sbin/rclone',
                '/opt/rclone/rclone',
            ]
            
            for path in common_paths:
                if os.path.exists(path) and os.access(path, os.X_OK):
                    rclone_path = path
                    logger.info(f"Rclone bulundu (common path): {rclone_path}")
                    break
        
        if not rclone_path:
            logger.warning(f"Rclone bulunamadı, Google Drive'a yükleme atlandı")
            logger.warning(f"   Rclone kurulumu: https://rclone.org/install/")
            logger.warning(f"   Veya: which rclone ile konumunu bulup PATH'e ekleyin")
            return False
        
        logger.info(f"Rclone bulundu: {rclone_path}")
        
        # Backup dosyasının var olduğunu kontrol et
        if not os.path.exists(backup_path):
            log_error(logger, E_BKP_001, "Yedek dosyasi bulunamadi", path=backup_path)
            return False
        
        file_size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        logger.info(f"Backup dosyası boyutu: {file_size_mb:.2f} MB")
        
        # Rclone remote'u kontrol et (tam path ile)
        remote_check = subprocess.run(
            [rclone_path, 'lsd', f'{RCLONE_REMOTE}:'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if remote_check.returncode != 0:
            log_error(
                logger,
                E_BKP_001,
                "Rclone remote erisilemiyor",
                remote=RCLONE_REMOTE,
                stderr=remote_check.stderr,
            )
            return False
        
        logger.info(f"Rclone remote '{RCLONE_REMOTE}' erişilebilir")
        
        # Klasörün var olup olmadığını kontrol et, yoksa oluştur
        folder_check = subprocess.run(
            [rclone_path, 'lsd', f'{RCLONE_REMOTE}:{GDRIVE_FOLDER}'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if folder_check.returncode != 0:
            logger.info(f"Klasör '{GDRIVE_FOLDER}' bulunamadı, oluşturuluyor...")
            mkdir_result = subprocess.run(
                [rclone_path, 'mkdir', f'{RCLONE_REMOTE}:{GDRIVE_FOLDER}'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if mkdir_result.returncode != 0:
                logger.warning(f"Klasör oluşturulamadı (zaten var olabilir): {mkdir_result.stderr}")
        else:
            logger.info(f"Klasör '{GDRIVE_FOLDER}' mevcut")
        
        # Rclone ile Google Drive'a yükle (tam path ile)
        remote_path = f"{RCLONE_REMOTE}:{GDRIVE_FOLDER}/{backup_filename}"
        rclone_cmd = [
            rclone_path,
            'copyto',
            backup_path,
            remote_path,
            '--progress',
            '--stats=10s'
        ]
        
        logger.info(f"Google Drive'a yükleniyor...")
        logger.info(f"   Kaynak: {backup_path}")
        logger.info(f"   Hedef: {remote_path}")
        
        result = subprocess.run(
            rclone_cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 dakika timeout (büyük dosyalar için)
        )
        
        if result.returncode == 0:
            logger.info(f"Backup Google Drive'a başarıyla yüklendi!")
            logger.info(f"Konum: {remote_path}")
            if result.stdout:
                logger.info(f"Rclone çıktısı: {result.stdout[-500:]}") # Son 500 karakter
            return True
        else:
            log_error(
                logger,
                E_BKP_001,
                "Google Drive yedek yukleme basarisiz",
                exit_code=result.returncode,
                stderr=result.stderr,
            )
            return False
            
    except subprocess.TimeoutExpired:
        log_error(logger, E_BKP_001, "Google Drive yedek yukleme timeout (10 dakika)")
        return False
    except FileNotFoundError:
        logger.warning(f"Rclone bulunamadı, Google Drive'a yükleme atlandı")
        logger.warning(f"   Rclone kurulumu: https://rclone.org/install/")
        return False
    except Exception as e:
        log_error(logger, E_BKP_001, "Google Drive yedek yukleme hatasi", exc=e)
        return False


def cleanup_old_database_backups(backup_dir, keep_days):
    """Eski yedekleri temizler"""
    import glob
    
    cutoff_date = datetime.now() - timedelta(days=keep_days)
    backup_pattern = os.path.join(backup_dir, 'backup_*.sql')
    
    deleted_count = 0
    
    for backup_file in glob.glob(backup_pattern):
        file_time = datetime.fromtimestamp(os.path.getmtime(backup_file))
        
        if file_time < cutoff_date:
            try:
                os.remove(backup_file)
                logger.info(f"Eski yedek silindi: {os.path.basename(backup_file)}")
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Dosya silinemedi: {backup_file} - {e}")
    
    if deleted_count > 0:
        logger.info(f"Toplam {deleted_count} eski yedek temizlendi")


# Scheduler'ı başlat (sadece master process'te)
# --preload ile Gunicorn master process'te başlatılır
# File lock ile birden fazla instance'ın scheduler'ı başlatmasını önle
scheduler = BackgroundScheduler()

# Scheduler lock file path
SCHEDULER_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.scheduler.lock')

def start_scheduler_if_master():
    """Scheduler'ı sadece bir process'te başlat (PostgreSQL advisory lock ile)
    
    PostgreSQL advisory lock kullanarak worker'lar arasında scheduler'ın 
    sadece bir kez başlatılmasını garanti eder. File lock yerine database 
    lock kullanılması daha güvenilirdir çünkü:
    - Worker'lar farklı process'lerde çalışır
    - Database lock tüm worker'lar için merkezi kontrol sağlar
    """
    import fcntl
    
    # Önce file lock dene (hızlı kontrol için)
    file_lock_acquired = False
    lock_file = None
    try:
        lock_file = open(SCHEDULER_LOCK_FILE, 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        file_lock_acquired = True
    except (IOError, OSError):
        # File lock alınamadı - başka bir process scheduler'ı başlatmış olabilir
        # Ama yine de database lock kontrolü yapacağız (daha güvenilir)
        logger.info("File lock alinamadi, database lock kontrolu yapiliyor")
        if lock_file:
            try:
                lock_file.close()
            except:
                pass
    
    # Database advisory lock ile kesin kontrol
    conn = None
    advisory_lock_id = 123456  # Scheduler için unique lock ID
    db_lock_acquired = False
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # PostgreSQL advisory lock al (non-blocking)
        # pg_try_advisory_lock: lock alınamazsa False döner, beklemez
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (advisory_lock_id,))
        db_lock_acquired = cursor.fetchone()[0]
        cursor.close()
        
        if not db_lock_acquired:
            logger.info("Scheduler baska bir process tarafindan baslatilmis (database lock), atlaniyor")
            if lock_file and file_lock_acquired:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                    lock_file.close()
                except:
                    pass
            return False
        
        # Lock alındı, scheduler'ı başlat
        if not scheduler.running:
            scheduler.add_job(func=send_appointment_reminders, trigger="interval", minutes=5, id='send_reminders', replace_existing=True, max_instances=1)
            scheduler.add_job(func=send_aftercare_cream_reminders, trigger="interval", minutes=5, id='send_aftercare_reminders', replace_existing=True, max_instances=1)
            scheduler.add_job(func=cleanup_expired_verification_codes, trigger="interval", minutes=5, id='cleanup_verification_codes', replace_existing=True, max_instances=1)
            scheduler.add_job(func=cleanup_expired_webhook_messages, trigger="interval", hours=1, id='cleanup_webhook_messages', replace_existing=True, max_instances=1)
            scheduler.add_job(func=cleanup_old_cancelled_appointments, trigger="interval", days=7, id='cleanup_cancelled_appointments', replace_existing=True, max_instances=1)
            scheduler.add_job(func=cleanup_expired_admin_tokens, trigger="interval", hours=24, id='cleanup_admin_tokens', replace_existing=True, max_instances=1)
            # Günlük veritabanı yedekleme: Her gün saat 00:30'da
            backup_hour = 0
            backup_minute = 30
            scheduler.add_job(func=create_database_backup, trigger=CronTrigger(hour=backup_hour, minute=backup_minute), id='daily_database_backup', replace_existing=True, max_instances=1)
            
            scheduler.start()
            import os
            logger.info(f"Scheduler başlatıldı (PID: {os.getpid()}, Advisory Lock ID: {advisory_lock_id})")
            logger.info("   - Randevu hatırlatma: her 5 dakikada bir (max_instances=1)")
            logger.info(f"   - Krem bakım hatırlatması: her 5 dk (tamamlandıktan {AFTERCARE_REMINDER_HOURS} saat sonra)")
            logger.info("   - Verification codes cleanup: her 5 dakikada bir")
            logger.info("   - Webhook messages cleanup: her 1 saatte bir")
            logger.info("   - Cancelled appointments cleanup: her 7 günde bir")
            logger.info("   - Admin tokens cleanup: her 24 saatte bir")
            logger.info(f"   - Database backup: Her gün saat {backup_hour:02d}:{backup_minute:02d}'da (max_instances=1)")
            if is_google_calendar_enabled():
                logger.info("   - Google Calendar: aktif (Faz 1 — randevu oluşunca/güncellenince push)")
            else:
                logger.info("   - Google Calendar: kapalı (GOOGLE_CALENDAR_ENABLED veya credentials)")
            
            # Lock dosyasını açık tut (process sonlanınca otomatik kapanır)
            if lock_file and file_lock_acquired:
                # Lock dosyasını açık bırak (process sonlanınca otomatik kapanır)
                pass
            
            return True
        else:
            logger.info("Scheduler zaten calisiyor")
            # Lock'u bırak (scheduler zaten çalışıyorsa başka bir process başlatmıştır)
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT pg_advisory_unlock(%s)", (advisory_lock_id,))
                cursor.close()
            if lock_file and file_lock_acquired:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                    lock_file.close()
                except:
                    pass
            return False
            
    except Exception as e:
        log_error(logger, E_SCH_001, "Scheduler baslatilamadi", exc=e)
        # Lock'u bırak
        if conn:
            try:
                if db_lock_acquired:
                    cursor = conn.cursor()
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (advisory_lock_id,))
                    cursor.close()
            except:
                pass
        if lock_file and file_lock_acquired:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
                lock_file.close()
            except:
                pass
        return False
    finally:
        release_db_connection(conn)

# Scheduler'ı başlat (sadece bir process başlatacak)
start_scheduler_if_master()
ensure_artist_instagram_column()

# Uygulama kapandığında scheduler'ı durdur
atexit.register(lambda: scheduler.shutdown() if scheduler.running else None)


# =============================================
# STAFF-SPECIFIC SCHEDULE ENDPOINTS (Super Admin)
# =============================================

@app.route('/api/admin/staff/<int:staff_id>/working-hours', methods=['GET'])
@token_required
def get_staff_working_hours(staff_id):
    """Super admin gets working hours for a specific staff member"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkisiz erişim'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, day_of_week, start_time, end_time, is_available
            FROM working_hours
            WHERE staff_id = %s
            ORDER BY day_of_week
        """, (staff_id,))
        
        rows = cursor.fetchall()
        cursor.close()
        
        working_hours = []
        for row in rows:
            working_hours.append({
                'id': row[0],
                'day_of_week': row[1],
                'start_time': str(row[2])[:5] if row[2] else None,
                'end_time': str(row[3])[:5] if row[3] else None,
                'is_available': row[4]
            })
        
        return jsonify({'success': True, 'working_hours': working_hours})
    except Exception as e:
        logger.error(f"get_staff_working_hours hatası: {e}")
        return jsonify({'success': False, 'message': 'Çalışma saatleri alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/staff/<int:staff_id>/working-hours', methods=['PUT'])
@token_required
def update_staff_working_hours(staff_id):
    """Super admin updates working hours for a specific staff member"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkisiz erişim'}), 403
    
    data = request.get_json()
    working_hours = data.get('working_hours', [])
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete existing working hours
        cursor.execute("DELETE FROM working_hours WHERE staff_id = %s", (staff_id,))
        
        # Insert new working hours
        for wh in working_hours:
            # Veritabanı NULL kabul etmiyor, kapalı günler için varsayılan değerler kullan
            start_time = wh['start_time'] if wh['start_time'] else '09:00'
            end_time = wh['end_time'] if wh['end_time'] else '18:00'
            
            cursor.execute("""
                INSERT INTO working_hours (staff_id, day_of_week, start_time, end_time, is_available)
                VALUES (%s, %s, %s, %s, %s)
            """, (staff_id, wh['day_of_week'], start_time, end_time, wh['is_available']))
        
        conn.commit()
        cursor.close()
        
        logger.info(f"Personel çalışma saatleri güncellendi: staff_id={staff_id}")
        
        return jsonify({'success': True, 'message': 'Çalışma saatleri güncellendi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_staff_working_hours hatası: {e}")
        return jsonify({'success': False, 'message': 'Çalışma saatleri güncellenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/staff/<int:staff_id>/time-off', methods=['GET'])
@token_required
def get_staff_time_off(staff_id):
    """Super admin gets time-off for a specific staff member"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkisiz erişim'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, off_date, start_time, end_time, reason
            FROM time_off
            WHERE staff_id = %s
            ORDER BY off_date DESC
        """, (staff_id,))
        
        rows = cursor.fetchall()
        cursor.close()
        
        time_offs = []
        for row in rows:
            time_offs.append({
                'id': row[0],
                'date': row[1].strftime('%d.%m.%Y'),
                'start_time': str(row[2])[:5] if row[2] else None,
                'end_time': str(row[3])[:5] if row[3] else None,
                'is_full_day': row[2] is None,
                'reason': row[4] or ''
            })
        
        return jsonify({'success': True, 'time_offs': time_offs})
    except Exception as e:
        logger.error(f"get_staff_time_off hatası: {e}")
        return jsonify({'success': False, 'message': 'İzinler alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/staff/<int:staff_id>/time-off', methods=['POST'])
@token_required
def add_staff_time_off(staff_id):
    """Super admin adds time-off for a specific staff member"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkisiz erişim'}), 403
    
    data = request.get_json()
    off_date = data.get('date')  # Format: YYYY-MM-DD
    start_time = data.get('start_time')  # Format: HH:MM veya None (tüm gün)
    end_time = data.get('end_time')
    reason = data.get('reason', '')
    
    if not off_date:
        return jsonify({'success': False, 'message': 'Tarih gerekli'}), 400
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO time_off (staff_id, off_date, start_time, end_time, reason)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (staff_id, off_date, start_time, end_time, reason))
        
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        
        logger.info(f"Personel izni eklendi: staff_id={staff_id}, date={off_date}")
        
        return jsonify({'success': True, 'message': 'İzin eklendi', 'id': new_id})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"add_staff_time_off hatası: {e}")
        return jsonify({'success': False, 'message': 'İzin eklenemedi'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/admin/staff/<int:staff_id>/time-off/<int:time_off_id>', methods=['DELETE'])
@token_required
def delete_staff_time_off(staff_id, time_off_id):
    """Super admin deletes time-off for a specific staff member"""
    if not is_studio_admin():
        return jsonify({'success': False, 'message': 'Yetkisiz erişim'}), 403
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify time-off belongs to this staff
        cursor.execute("SELECT staff_id FROM time_off WHERE id = %s", (time_off_id,))
        row = cursor.fetchone()
        
        if not row:
            cursor.close()
            return jsonify({'success': False, 'message': 'İzin bulunamadı'}), 404
        
        if row[0] != staff_id:
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu izin bu personele ait değil'}), 400
        
        cursor.execute("DELETE FROM time_off WHERE id = %s", (time_off_id,))
        conn.commit()
        cursor.close()
        
        logger.info(f"Personel izni silindi: staff_id={staff_id}, time_off_id={time_off_id}")
        
        return jsonify({'success': True, 'message': 'İzin silindi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"delete_staff_time_off hatası: {e}")
        return jsonify({'success': False, 'message': 'İzin silinemedi'}), 500
    finally:
        release_db_connection(conn)


# =============================================
# CUSTOMER PANEL ENDPOINTS
# =============================================

@app.route('/api/customer/login', methods=['POST'])
def customer_login():
    """Customer login with phone verification - returns JWT token"""
    data = request.get_json()
    phone = data.get('phone')
    code = data.get('code')
    
    if not phone or not code:
        return jsonify({'success': False, 'message': 'Telefon numarası ve doğrulama kodu gerekli'}), 400
    
    # Verify code - Database tabanlı (worker'lar arası paylaşımlı)
    phone = str(phone).strip()
    normalized_phone = normalize_phone_for_storage(phone)
    
    # Demo mode: sabit kod "123456" her zaman kabul edilir (WhatsApp doğrulaması atlanır)
    if str(code).strip() != "123456":
        conn_verify = None
        try:
            conn_verify = get_db_connection()
            cursor_verify = conn_verify.cursor()
            
            # Önce orijinal formatı kontrol et
            cursor_verify.execute("""
                SELECT code, expires_at 
                FROM verification_codes 
                WHERE phone = %s 
                AND expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """, (phone,))
            
            row = cursor_verify.fetchone()
            
            # Bulunamazsa normalize formatı kontrol et
            if not row and normalized_phone != phone:
                cursor_verify.execute("""
                    SELECT code, expires_at 
                    FROM verification_codes 
                    WHERE phone = %s 
                    AND expires_at > NOW()
                    ORDER BY created_at DESC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """, (normalized_phone,))
                row = cursor_verify.fetchone()
            
            # Hala bulunamadıysa hata
            if not row:
                logger.warning(f"Customer login - Doğrulama kodu bulunamadı: phone={phone}, normalized={normalized_phone}")
                cursor_verify.close()
                return jsonify({'success': False, 'message': 'Doğrulama kodu bulunamadı. Lütfen kod isteyiniz'}), 404
            
            stored_code, expires_at = row
            
            # Kod kontrolü
            if str(stored_code) != str(code):
                cursor_verify.close()
                return jsonify({'success': False, 'message': 'Doğrulama kodu yanlış'}), 401
            
            # Süre kontrolü (ekstra güvenlik)
            if datetime.now() > expires_at:
                # Expire olan kodu temizle
                cursor_verify.execute("DELETE FROM verification_codes WHERE phone IN (%s, %s) AND expires_at <= NOW()", (phone, normalized_phone))
                conn_verify.commit()
                cursor_verify.close()
                return jsonify({'success': False, 'message': 'Doğrulama kodu süresi dolmuş'}), 401
            
            # Başarılı doğrulama - kodu sil (kullanıldığı için)
            cursor_verify.execute("DELETE FROM verification_codes WHERE phone IN (%s, %s) AND code = %s", (phone, normalized_phone, str(code)))
            conn_verify.commit()
            cursor_verify.close()
            
        except Exception as e:
            logger.error(f"Customer login - Verification code kontrolü hatası: {e}")
            if conn_verify:
                conn_verify.rollback()
                cursor_verify.close()
            return jsonify({'success': False, 'message': 'Doğrulama hatası'}), 500
        finally:
            release_db_connection(conn_verify)
    
    # Get customer info
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        customer = find_customer_by_phone(cursor, phone)
        cursor.close()
        
        if not customer:
            return jsonify({'success': False, 'message': 'Müşteri bulunamadı. Lütfen önce randevu oluşturun'}), 404
        
        stored_phone = customer[3]
        # Generate customer JWT token
        token = jwt.encode({
            'customer_id': customer[0],
            'phone': stored_phone,
            'type': 'customer',
            'exp': datetime.utcnow() + timedelta(days=30)  # 30 gün geçerli
        }, JWT_SECRET, algorithm='HS256')
        
        logger.info(f"Müşteri girişi başarılı: {phone}")
        
        return jsonify({
            'success': True,
            'message': 'Giriş başarılı',
            'token': token,
            'customer': {
                'id': customer[0],
                'name': customer[1],
                'surname': customer[2],
                'phone': stored_phone
            }
        })
    except Exception as e:
        logger.error(f"customer_login hatası: {e}")
        return jsonify({'success': False, 'message': 'Giriş sırasında hata oluştu'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/customer/loyalty', methods=['GET'])
@customer_token_required
def get_customer_loyalty():
    """Müşteri sadakat puanı özeti ve işlem geçmişi."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        summary = build_loyalty_summary(cursor, request.customer_id)
        conn.commit()
        cursor.close()
        return jsonify({'success': True, 'loyalty': summary})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"get_customer_loyalty hatası: {e}")
        return jsonify({'success': False, 'message': 'Sadakat bilgisi alınamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/customer/loyalty/redeem', methods=['POST'])
@customer_token_required
def post_customer_loyalty_redeem():
    """5. dövme milestone + yeterli puan ile indirim kodu oluştur."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        redemption, err = redeem_loyalty_discount(cursor, request.customer_id)
        if err:
            conn.rollback()
            cursor.close()
            return jsonify({'success': False, 'message': err}), 400
        summary = build_loyalty_summary(cursor, request.customer_id)
        conn.commit()
        cursor.close()
        return jsonify({
            'success': True,
            'message': f"%{redemption['discount_percent']} indirim kodunuz oluşturuldu",
            'redemption': redemption,
            'loyalty': summary,
        })
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"post_customer_loyalty_redeem hatası: {e}")
        return jsonify({'success': False, 'message': 'İndirim kodu oluşturulamadı'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/customer/tattoo-requests', methods=['GET'])
@customer_token_required
def get_customer_tattoo_requests():
    """Sanatçı onayı bekleyen dövme randevu talepleri."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                tr.id,
                tr.reference_number,
                tr.status,
                tr.size,
                tr.body_area,
                tr.tattoo_style,
                tr.estimated_price,
                tr.description,
                tr.created_at,
                s.id,
                s.name
            FROM tattoo_requests tr
            JOIN artists s ON tr.staff_id = s.id
            WHERE tr.customer_id = %s AND tr.status = 'new'
            ORDER BY tr.created_at DESC
        """, (request.customer_id,))
        rows = cursor.fetchall()
        requests_list = []
        for row in rows:
            (tr_id, ref_num, status, size, body_area, tattoo_style, estimated_price,
             description, created_at, staff_id, staff_name) = row
            requests_list.append({
                'id': tr_id,
                'reference_number': ref_num,
                'status': status,
                'status_label': 'Onay bekleniyor',
                'created_at': created_at.strftime('%d.%m.%Y %H:%M') if created_at else None,
                'staff': {'id': staff_id, 'name': staff_name},
                'size': size,
                'body_area': body_area,
                'tattoo_style': tattoo_style,
                'estimated_price': float(estimated_price) if estimated_price is not None else None,
                'description': description,
            })
        cursor.close()
        return jsonify({'success': True, 'requests': requests_list})
    except Exception as e:
        logger.error(f"get_customer_tattoo_requests hatası: {e}")
        return jsonify({'success': False, 'message': 'Talepler alınırken hata oluştu'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/customer/appointments', methods=['GET'])
@customer_token_required
def get_customer_appointments():
    """Get customer's appointments with optional filter"""
    filter_type = request.args.get('filter', 'all')  # all, upcoming, past, completed
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT 
                a.id,
                a.appointment_date,
                a.appointment_time,
                a.status,
                a.payment_method,
                a.created_at,
                a.duration_minutes,
                a.price,
                ar.id   AS staff_id,
                ar.name AS staff_name,
                tr.id   AS tattoo_request_id,
                tr.size,
                tr.body_area,
                tr.description,
                a.source
            FROM appointments a
            JOIN artists ar ON a.staff_id = ar.id
            LEFT JOIN tattoo_requests tr ON a.tattoo_request_id = tr.id
            WHERE a.customer_id = %s
        """
        params = [request.customer_id]

        today = datetime.now().date()
        if filter_type == 'upcoming':
            query += " AND (a.appointment_date > %s OR (a.appointment_date = %s AND a.appointment_time >= %s)) AND a.status IN ('pending', 'confirmed')"
            params.extend([today, today, datetime.now().time()])
        elif filter_type == 'past':
            query += " AND (a.appointment_date < %s OR (a.appointment_date = %s AND a.appointment_time < %s) OR a.status IN ('completed', 'cancelled', 'no_show'))"
            params.extend([today, today, datetime.now().time()])
        elif filter_type == 'completed':
            query += " AND a.status = 'completed'"

        query += " ORDER BY a.appointment_date DESC, a.appointment_time DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        appointments = []
        can_use_offer_price_fallback = True
        for row in rows:
            final_price = float(row[7] or 0)
            tattoo_request_id = row[10]

            # Backward-compat: some old appointments may have price=0 even if offered with a price.
            # Try to recover from the latest used slot_offers price.
            if final_price <= 0 and tattoo_request_id and can_use_offer_price_fallback:
                try:
                    cursor.execute("""
                        SELECT price
                        FROM slot_offers
                        WHERE tattoo_request_id = %s AND used_at IS NOT NULL
                        ORDER BY used_at DESC NULLS LAST, id DESC
                        LIMIT 1
                    """, (tattoo_request_id,))
                    offer_row = cursor.fetchone()
                    if offer_row and offer_row[0] is not None and float(offer_row[0]) > 0:
                        final_price = float(offer_row[0])
                except Exception:
                    # If slot_offers.price is unavailable in older DBs, skip fallback silently.
                    can_use_offer_price_fallback = False

            appointments.append({
                'type': 'appointment',
                'id': row[0],
                'date': row[1].strftime('%d.%m.%Y'),
                'time': str(row[2])[:5],
                'status': row[3],
                'payment_method': row[4],
                'created_at': row[5].strftime('%d.%m.%Y %H:%M'),
                'duration_minutes': row[6],
                'price': final_price,
                'staff': {
                    'id': row[8],
                    'name': row[9]
                },
                'tattoo': {
                    'request_id': row[10],
                    'size': row[11],
                    'body_area': row[12],
                    'description': row[13]
                } if row[10] else None,
                'source': row[14] or 'admin',
            })

        if filter_type in ('upcoming', 'all'):
            pending_slots = _fetch_customer_pending_slot_selections(cursor, request.customer_id)
            appointments = pending_slots + appointments

        cursor.close()
        
        return jsonify({'success': True, 'appointments': appointments})
    except Exception as e:
        logger.error(f"get_customer_appointments hatası: {e}")
        return jsonify({'success': False, 'message': 'Randevular alınırken hata oluştu'}), 500
    finally:
        release_db_connection(conn)


@app.route('/api/customer/appointments/<int:appointment_id>/cancel', methods=['PUT'])
@customer_token_required
def cancel_customer_appointment(appointment_id):
    """Cancel an appointment - with validations"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get appointment details (tattoo flow compatible)
        cursor.execute("""
            SELECT a.customer_id, a.status, a.appointment_date, a.appointment_time,
                   c.name, c.surname, c.phone,
                   s.name, s.phone,
                   a.duration_minutes, a.price,
                   tr.size, tr.body_area,
                   a.google_event_id
            FROM appointments a
            JOIN customers c ON a.customer_id = c.id
            JOIN artists s ON a.staff_id = s.id
            LEFT JOIN tattoo_requests tr ON a.tattoo_request_id = tr.id
            WHERE a.id = %s
        """, (appointment_id,))
        
        appointment = cursor.fetchone()
        
        if not appointment:
            cursor.close()
            return jsonify({'success': False, 'message': 'Randevu bulunamadı'}), 404
        
        # Validation 1: Check ownership
        if appointment[0] != request.customer_id:
            cursor.close()
            return jsonify({'success': False, 'message': 'Bu randevuyu iptal etme yetkiniz yok'}), 403
        
        # Validation 2: Check status
        if appointment[1] not in ['pending', 'confirmed']:
            cursor.close()
            return jsonify({'success': False, 'message': f'Bu randevu iptal edilemez. Durum: {appointment[1]}'}), 400
        
        # Validation 3: Check time (at least 2 hours before)
        appt_datetime = datetime.combine(appointment[2], appointment[3])
        now = datetime.now()
        time_diff = (appt_datetime - now).total_seconds() / 3600  # hours
        
        if time_diff < 2:
            cursor.close()
            return jsonify({
                'success': False,
                'message': 'Randevuya 2 saatten az kaldı. İptal edilemez. Lütfen bizimle iletişime geçin.'
            }), 400
        
        # Cancel appointment - DELETE (hemen sil)
        customer_name = f"{appointment[4]} {appointment[5]}"
        google_event_id = appointment[13]
        cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
        conn.commit()
        try:
            on_appointment_cancelled(google_event_id)
        except Exception as gcal_err:
            logger.warning(f"Google Calendar silme atlandı (apt #{appointment_id}): {gcal_err}")
        staff_name = appointment[7]
        staff_phone = appointment[8]
        duration_minutes = int(appointment[9] or 30)
        price_value = float(appointment[10] or 0)
        tattoo_size = appointment[11]
        tattoo_body_area = appointment[12]
        date_str = appointment[2].strftime('%d.%m.%Y')
        time_str = str(appointment[3])[:5]
        tattoo_info = []
        if tattoo_body_area:
            tattoo_info.append(f"Bölge: {tattoo_body_area}")
        if tattoo_size:
            tattoo_info.append(f"Boyut: {tattoo_size}")
        tattoo_line = f"\n🖋️ Detay: {' | '.join(tattoo_info)}" if tattoo_info else ""
        price_line = f"\n💰 Ücret: {price_value:.2f} ₺" if price_value > 0 else ""
        
        staff_message = build_staff_cancel_notification_message(
            customer_name,
            appointment[6],
            date_str,
            time_str,
            duration_minutes,
            tattoo_line,
            price_line,
        )
        
        send_wapio_message(staff_phone, staff_message)
        
        # Send WhatsApp notification to customer
        customer_phone = appointment[6]
        customer_message = build_customer_cancel_confirmation_message(
            customer_name,
            staff_name,
            date_str,
            time_str,
            duration_minutes,
            tattoo_line,
            price_line,
        )
        
        send_wapio_message(customer_phone, customer_message)
        
        cursor.close()
        logger.info(f"Randevu iptal edildi: {appointment_id} by customer {request.customer_id}")
        
        return jsonify({'success': True, 'message': 'Randevunuz başarıyla iptal edildi'})
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"cancel_customer_appointment hatası: {e}")
        return jsonify({'success': False, 'message': 'İptal işlemi sırasında hata oluştu'}), 500
    finally:
        release_db_connection(conn)


# =============================================
# APP RUN
# =============================================

if __name__ == '__main__':
    # Flask'in kendi request loglarını kapat (sadece WARNING ve üstü)
    import logging as log
    log.getLogger('werkzeug').setLevel(log.WARNING)
    
    # Local / standalone ayarları (production'da gunicorn önerilir)
    app_host = os.getenv('APP_HOST', '0.0.0.0')
    app_port = int(os.getenv('APP_PORT', '3000'))
    app_debug = os.getenv('APP_DEBUG', 'false').strip().lower() == 'true'
    app.run(
        host=app_host,
        port=app_port,
        debug=app_debug,
        threaded=True       # Multi-threading aktif (50-100 kullanıcı)
    )
