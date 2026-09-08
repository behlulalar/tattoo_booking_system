"""UptimeRobot sağlık uçları ve arka plan heartbeat ping."""

from __future__ import annotations

import logging
import os
from datetime import datetime

import requests

from config import SITE_CONFIG
from google_calendar_sync import (
    credentials_file_ok,
    get_google_calendar_config,
    google_api_reachable,
    is_google_calendar_enabled,
)
from whatsapp_provider import check_whatsapp_health

logger = logging.getLogger(__name__)

PROBE_UP = 'up'
PROBE_DOWN = 'down'
PROBE_SKIP = 'skip'


def public_base_url() -> str:
    return (SITE_CONFIG.get('randevu_url') or '').strip().rstrip('/')


def _now_iso() -> str:
    return datetime.now().isoformat()


def monitor_payload(probe: str, extra=None) -> dict:
    status = 'healthy' if probe == PROBE_UP else ('skipped' if probe == PROBE_SKIP else 'unhealthy')
    body = {
        'probe': probe,
        'status': status,
        'timestamp': _now_iso(),
    }
    if extra:
        body.update(extra)
    return body


def http_status_for_probe(probe: str) -> int:
    return 200 if probe in (PROBE_UP, PROBE_SKIP) else 503


def check_google_calendar_uptime() -> tuple[str, dict]:
    """Google API'ye çıkış ve takvim ayarı. Kapalıysa skip (monitor yeşil kalır)."""
    if not is_google_calendar_enabled():
        return PROBE_SKIP, {
            'component': 'google-calendar',
            'reason': 'Google Takvim senkronu kapalı',
        }
    cfg = get_google_calendar_config()
    if not credentials_file_ok():
        return PROBE_DOWN, {
            'component': 'google-calendar',
            'reason': 'Google kimlik dosyası yok',
        }
    if not (cfg.get('calendar_id') or '').strip():
        return PROBE_DOWN, {
            'component': 'google-calendar',
            'reason': 'Takvim kimliği yok',
        }
    if not google_api_reachable(timeout=3):
        return PROBE_DOWN, {
            'component': 'google-calendar',
            'reason': 'Google sunucularına ulaşılamıyor',
        }
    return PROBE_UP, {'component': 'google-calendar'}


def check_whatsapp_uptime() -> tuple[str, dict]:
    result = check_whatsapp_health()
    extra = {
        'component': 'whatsapp',
        'provider': result.get('provider'),
    }
    if result.get('healthy'):
        return PROBE_UP, extra
    extra['reason'] = result.get('reason') or 'WhatsApp bağlantısı yok'
    return PROBE_DOWN, extra


def uptime_catalog() -> dict:
    base = public_base_url() or 'https://tattoo.roof.behlulalar.online'
    return {
        'probe': PROBE_UP,
        'status': 'healthy',
        'timestamp': _now_iso(),
        'base_url': base,
        'monitors': [
            {
                'id': 'site',
                'name': 'Site',
                'url': f'{base}/',
                'notes': 'Nginx + müşteri sayfası',
            },
            {
                'id': 'api-db',
                'name': 'API + veritabanı',
                'url': f'{base}/api/health',
                'notes': 'Flask ve PostgreSQL. 503 = kopuk.',
            },
            {
                'id': 'whatsapp',
                'name': 'WhatsApp (Evolution)',
                'url': f'{base}/api/health/whatsapp',
                'notes': 'QR/oturum düşünce 503.',
            },
            {
                'id': 'google-calendar',
                'name': 'Google Takvim',
                'url': f'{base}/api/health/google-calendar',
                'notes': 'Senkron kapalıysa 200 skip; Google ağı düşünce 503.',
            },
            {
                'id': 'scheduler',
                'name': 'Arka plan işleri',
                'url': None,
                'notes': (
                    'UptimeRobot Heartbeat monitörü. Dashboard’da oluşturup '
                    'UPTIMEROBOT_HEARTBEAT_URL değerine yapıştırın.'
                ),
            },
        ],
        'keyword': '"probe": "up"',
    }


def heartbeat_url() -> str:
    return (os.getenv('UPTIMEROBOT_HEARTBEAT_URL') or '').strip()


def ping_uptimerobot_heartbeat():
    """Scheduler canlıysa UptimeRobot heartbeat URL’sine dokunur."""
    url = heartbeat_url()
    if not url:
        return
    try:
        response = requests.get(url, timeout=8)
        if response.status_code >= 400:
            logger.warning(
                'UptimeRobot heartbeat HTTP %s',
                response.status_code,
            )
    except Exception as exc:
        logger.warning('UptimeRobot heartbeat gonderilemedi: %s', str(exc)[:160])
