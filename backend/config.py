import os 
import json
from dotenv import load_dotenv

load_dotenv()


def build_database_config():
    """PostgreSQL bağlantı ayarları (SSL / keepalive destekli)."""
    cfg = {
        'host': os.getenv('DATABASE_HOST'),
        'port': os.getenv('DATABASE_PORT'),
        'user': os.getenv('DATABASE_USER'),
        'password': os.getenv('DATABASE_PASSWORD'),
        'database': os.getenv('DATABASE_NAME'),
        'keepalives': int(os.getenv('DATABASE_KEEPALIVES', '1')),
        'keepalives_idle': int(os.getenv('DATABASE_KEEPALIVES_IDLE', '30')),
        'keepalives_interval': int(os.getenv('DATABASE_KEEPALIVES_INTERVAL', '10')),
        'keepalives_count': int(os.getenv('DATABASE_KEEPALIVES_COUNT', '5')),
    }
    sslmode = (os.getenv('DATABASE_SSLMODE') or '').strip()
    if sslmode:
        cfg['sslmode'] = sslmode
    return cfg


DATABASE_CONFIG = build_database_config()

# Wapio OpenAPI v1.0.0 — api_key: https://my.wapio.com.tr/hesabim
_session_id_env = (os.getenv('WAPIO_SESSION_ID') or os.getenv('WAPIO_INSTANCE_ID') or '').strip()
WAPIO_CONFIG = {
    'api_url': os.getenv('WAPIO_API_URL', 'https://my.wapio.com.tr'),
    'api_key': (os.getenv('WAPIO_API_KEY') or '').strip(),
    'session_id': _session_id_env,
    'domain_key': (os.getenv('WAPIO_DOMAIN_KEY') or '').strip(),
    'device_name': (os.getenv('WAPIO_DEVICE_NAME') or 'Roof Tattoo').strip(),
    # Geriye dönük alan adları
    'instance_id': _session_id_env,
    'api_token': (os.getenv('WAPIO_API_TOKEN') or '').strip(),
}

WAPIO_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'wapio_settings.json')


def _parse_bool(value, default=True):
    """Env/JSON boolean — true, 1, yes, on."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _merge_wapio_settings(stored: dict) -> dict:
    """JSON + env birleşimi."""
    api_key = (stored.get('api_key') or stored.get('api_token') or WAPIO_CONFIG['api_key'] or WAPIO_CONFIG['api_token'] or '').strip()
    session_id = (stored.get('session_id') or stored.get('instance_id') or WAPIO_CONFIG['session_id'] or '').strip()
    domain_key = (stored.get('domain_key') or WAPIO_CONFIG['domain_key'] or '').strip()
    device_name = (stored.get('device_name') or WAPIO_CONFIG['device_name'] or 'Roof Tattoo').strip()
    welcome_env = os.getenv('WAPIO_WELCOME_MESSAGE_ENABLED')
    welcome_message_enabled = _parse_bool(
        stored.get('welcome_message_enabled') if 'welcome_message_enabled' in stored else welcome_env,
        default=True,
    )
    return {
        'api_url': WAPIO_CONFIG['api_url'],
        'api_key': api_key,
        'session_id': session_id,
        'domain_key': domain_key,
        'device_name': device_name,
        'welcome_message_enabled': welcome_message_enabled,
        'instance_id': session_id,
        'api_token': api_key,
    }


def get_wapio_config():
    """Dinamik Wapio config — önce wapio_settings.json, yoksa .env."""
    try:
        if os.path.exists(WAPIO_SETTINGS_FILE):
            with open(WAPIO_SETTINGS_FILE, 'r') as f:
                stored = json.load(f)
                if isinstance(stored, dict):
                    return _merge_wapio_settings(stored)
    except Exception:
        pass
    return _merge_wapio_settings({})


def save_wapio_config(api_key, session_id, domain_key='', device_name='', welcome_message_enabled=None):
    """Wapio ayarlarını JSON dosyasına kaydet."""
    existing = {}
    try:
        if os.path.exists(WAPIO_SETTINGS_FILE):
            with open(WAPIO_SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    existing = loaded
    except Exception:
        pass

    if welcome_message_enabled is None:
        welcome_message_enabled = _parse_bool(existing.get('welcome_message_enabled'), default=True)
    else:
        welcome_message_enabled = _parse_bool(welcome_message_enabled, default=True)

    settings = {
        'api_key': (api_key or '').strip(),
        'session_id': (session_id or '').strip(),
        'domain_key': (domain_key or '').strip(),
        'device_name': (device_name or 'Roof Tattoo').strip(),
        'welcome_message_enabled': welcome_message_enabled,
        # Eski anahtarlar (okuma uyumluluğu)
        'instance_id': (session_id or '').strip(),
        'api_token': (api_key or '').strip(),
    }
    with open(WAPIO_SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)
    return True

# Site ayarları JSON dosya yolu
SITE_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'site_settings.json')

def get_site_settings():
    """Site ayarlarını JSON dosyasından oku"""
    try:
        if os.path.exists(SITE_SETTINGS_FILE):
            with open(SITE_SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {
        'banner_image': '',
        'logo_image': '',
        'private_zone': {
            'enabled': True,
            'days': [
                {'day_of_week': 2, 'start_time': '14:00', 'end_time': '18:00'},
                {'day_of_week': 4, 'start_time': '14:00', 'end_time': '18:00'},
            ],
        },
    }

def save_site_settings(settings):
    """Site ayarlarını JSON dosyasına kaydet"""
    with open(SITE_SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)
    return True

CODE_EXPIRATION_SECONDS = 120

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_GCAL_CREDENTIALS = os.path.join(_BACKEND_DIR, 'credentials', 'google-calendar.json')

GOOGLE_CALENDAR_CONFIG = {
    'enabled': os.getenv('GOOGLE_CALENDAR_ENABLED', 'false').strip().lower() in ('1', 'true', 'yes'),
    'credentials_path': (os.getenv('GOOGLE_CALENDAR_CREDENTIALS_PATH') or _DEFAULT_GCAL_CREDENTIALS).strip(),
    'calendar_id': (os.getenv('GOOGLE_CALENDAR_ID') or '').strip(),
    'timezone': os.getenv('GOOGLE_CALENDAR_TIMEZONE', 'Europe/Istanbul').strip(),
}

GOOGLE_CALENDAR_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'google_calendar_settings.json')


def _merge_google_calendar_settings(stored: dict) -> dict:
    stored = stored if isinstance(stored, dict) else {}
    enabled = stored['enabled'] if 'enabled' in stored else GOOGLE_CALENDAR_CONFIG['enabled']
    return {
        'enabled': _parse_bool(enabled, default=False),
        'credentials_path': GOOGLE_CALENDAR_CONFIG['credentials_path'],
        'calendar_id': ((stored.get('calendar_id') if 'calendar_id' in stored else GOOGLE_CALENDAR_CONFIG['calendar_id']) or '').strip(),
        'timezone': (
            stored.get('timezone')
            if stored.get('timezone')
            else GOOGLE_CALENDAR_CONFIG['timezone']
            or 'Europe/Istanbul'
        ).strip(),
    }


def get_google_calendar_config():
    """Google Calendar ayarları — önce google_calendar_settings.json, sonra .env."""
    try:
        if os.path.exists(GOOGLE_CALENDAR_SETTINGS_FILE):
            with open(GOOGLE_CALENDAR_SETTINGS_FILE, 'r') as f:
                stored = json.load(f)
                if isinstance(stored, dict):
                    return _merge_google_calendar_settings(stored)
    except Exception:
        pass
    return _merge_google_calendar_settings({})


def save_google_calendar_config(calendar_id=None, enabled=None, timezone=None):
    existing = {}
    try:
        if os.path.exists(GOOGLE_CALENDAR_SETTINGS_FILE):
            with open(GOOGLE_CALENDAR_SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    existing = loaded
    except Exception:
        pass

    current = _merge_google_calendar_settings(existing)
    if calendar_id is not None:
        current['calendar_id'] = (calendar_id or '').strip()
    if enabled is not None:
        current['enabled'] = _parse_bool(enabled, default=False)
    if timezone is not None:
        current['timezone'] = (timezone or '').strip() or current['timezone']

    payload = {
        'enabled': current['enabled'],
        'calendar_id': current['calendar_id'],
        'timezone': current['timezone'],
    }
    with open(GOOGLE_CALENDAR_SETTINGS_FILE, 'w') as f:
        json.dump(payload, f, indent=4)
    return True

LOYALTY_CONFIG = {
    'enabled': os.getenv('LOYALTY_ENABLED', 'true').strip().lower() in ('1', 'true', 'yes'),
    'points_per_completion': int(os.getenv('LOYALTY_POINTS_PER_COMPLETION', '100')),
    'milestone_completions': int(os.getenv('LOYALTY_MILESTONE_COMPLETIONS', '5')),
    'redeem_points_cost': int(os.getenv('LOYALTY_REDEEM_POINTS', '500')),
    'discount_percent': int(os.getenv('LOYALTY_DISCOUNT_PERCENT', '10')),
    'redemption_valid_days': int(os.getenv('LOYALTY_REDEMPTION_DAYS', '90')),
}

SITE_CONFIG = {
    'randevu_url': os.getenv('RANDEVU_URL', 'http://127.0.0.1:8000'),
    'business_name': os.getenv('BUSINESS_NAME', 'Roof Tattoo Gallery'),
    'business_phone': os.getenv('BUSINESS_PHONE', ''),
    'business_address': os.getenv('BUSINESS_ADDRESS', ''),
    'working_hours': os.getenv('WORKING_HOURS', 'Pazartesi - Cumartesi: 09:00 - 20:00\nPazar: Kapalı'),
}

# Evolution API — https://github.com/evolution-foundation/evolution-api
EVOLUTION_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'evolution_settings.json')

EVOLUTION_CONFIG = {
    'api_url': os.getenv('EVOLUTION_API_URL', 'http://127.0.0.1:8080'),
    'api_key': (os.getenv('EVOLUTION_API_KEY') or os.getenv('AUTHENTICATION_API_KEY') or '').strip(),
    'instance_name': (os.getenv('EVOLUTION_INSTANCE_NAME') or 'roof-tattoo').strip(),
}


def _merge_evolution_settings(stored: dict) -> dict:
    welcome_env = os.getenv('EVOLUTION_WELCOME_MESSAGE_ENABLED')
    welcome_message_enabled = _parse_bool(
        stored.get('welcome_message_enabled') if 'welcome_message_enabled' in stored else welcome_env,
        default=True,
    )
    otp_env = os.getenv('OTP_KEYBOARD_HINT_ENABLED')
    otp_keyboard_hint_enabled = _parse_bool(
        stored.get('otp_keyboard_hint_enabled') if 'otp_keyboard_hint_enabled' in stored else otp_env,
        default=True,
    )
    return {
        'api_url': (stored.get('api_url') or EVOLUTION_CONFIG['api_url'] or '').strip(),
        'api_key': (stored.get('api_key') or EVOLUTION_CONFIG['api_key'] or '').strip(),
        'instance_name': (stored.get('instance_name') or EVOLUTION_CONFIG['instance_name'] or '').strip(),
        'welcome_message_enabled': welcome_message_enabled,
        'otp_keyboard_hint_enabled': otp_keyboard_hint_enabled,
    }


def get_evolution_config():
    """Evolution ayarları — önce evolution_settings.json, sonra .env."""
    try:
        if os.path.exists(EVOLUTION_SETTINGS_FILE):
            with open(EVOLUTION_SETTINGS_FILE, 'r') as f:
                stored = json.load(f)
                if isinstance(stored, dict):
                    return _merge_evolution_settings(stored)
    except Exception:
        pass
    return _merge_evolution_settings({})


def save_evolution_config(
    api_key,
    instance_name,
    api_url=None,
    welcome_message_enabled=None,
    otp_keyboard_hint_enabled=None,
):
    """Evolution ayarlarını JSON dosyasına kaydet."""
    existing = {}
    try:
        if os.path.exists(EVOLUTION_SETTINGS_FILE):
            with open(EVOLUTION_SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    existing = loaded
    except Exception:
        pass

    if welcome_message_enabled is None:
        welcome_message_enabled = _parse_bool(existing.get('welcome_message_enabled'), default=True)
    else:
        welcome_message_enabled = _parse_bool(welcome_message_enabled, default=True)

    if otp_keyboard_hint_enabled is None:
        otp_keyboard_hint_enabled = _parse_bool(existing.get('otp_keyboard_hint_enabled'), default=True)
    else:
        otp_keyboard_hint_enabled = _parse_bool(otp_keyboard_hint_enabled, default=True)

    merged_api_key = (api_key or '').strip() or (existing.get('api_key') or EVOLUTION_CONFIG['api_key'] or '').strip()
    merged_instance = (instance_name or '').strip() or (
        existing.get('instance_name') or EVOLUTION_CONFIG['instance_name'] or ''
    ).strip()

    settings = {
        'api_url': (api_url or existing.get('api_url') or EVOLUTION_CONFIG['api_url'] or '').strip(),
        'api_key': merged_api_key,
        'instance_name': merged_instance,
        'welcome_message_enabled': welcome_message_enabled,
        'otp_keyboard_hint_enabled': otp_keyboard_hint_enabled,
    }
    with open(EVOLUTION_SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)
    return True
