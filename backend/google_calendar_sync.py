"""
PostgreSQL randevulari paylaşılan Google Calendar ile senkronlar.

Sistem randevusu -> Google (kuyruk). Off Day (time_off) -> Google (kuyruk).
Elle Google etkinliği: telefon varsa source=google randevu; sanatçı + telefonsuz
veya Off Day anahtar kelimesi -> time_off. origin=roof taşı/sil inbound.
origin=roof_off Off Day taşı/sil. Tüm-gün randevu olmaz; tüm-gün Off Day olur.
Yinelenen master randevu olmaz; meşgul zaman olarak kalabilir.
Google kaynaklı hatırlatma/bakım WhatsApp'ı app.py job'larında (telefon varsa).
Google'dan silinen randevu iptal edilir ve müşteriye iptal WhatsApp'ı gider
(set_cancel_notifier ile, commit sonrası, gerçek numara varsa).
"""
import hashlib
import logging
import json
import os
import random
import re
import socket
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone, time as dt_time

import psycopg2

from config import DATABASE_CONFIG, SITE_CONFIG, get_google_calendar_config
from error_codes import E_GCAL_001, E_GCAL_002, E_GCAL_003, E_GCAL_004
from logging_setup import log_error
from whatsapp_messages import format_try

logger = logging.getLogger(__name__)

_SCOPES = ['https://www.googleapis.com/auth/calendar']

# googleapiclient Resource nesnesi (altindaki httplib2.Http) thread-safe degil;
# her thread kendi ornegini kurar. _fingerprint degisince yeniden kurulur.
_thread_local = threading.local()

# Google API cagrilarinda timeout yoksa askida kalan baglanti gunicorn
# thread'ini timeout suresi kadar tutar.
GCAL_HTTP_TIMEOUT = int(os.getenv('GOOGLE_CALENDAR_HTTP_TIMEOUT', '45'))

# Kuyruk isi kac denemeden sonra birakilir + denemeler arasi bekleme
GCAL_MAX_ATTEMPTS = int(os.getenv('GOOGLE_CALENDAR_MAX_ATTEMPTS', '6'))
_BACKOFF_SECONDS = (60, 300, 900, 3600, 10800, 21600)
# Advisory kilit alinamadiginda is deneme hakki yakmadan ertelenir; bu da
# ~1 saatlik bir tavanla sinirlidir (aksi halde sonsuza kadar donerdi).
GCAL_MAX_BUSY_DEFERRALS = int(os.getenv('GOOGLE_CALENDAR_MAX_BUSY_DEFERRALS', '60'))
# Bir is islenirken baska worker'in ayni isi almasini engelleyen kiralama suresi
_CLAIM_LEASE_SECONDS = 300
# Ayni randevunun iki paralel senkronunda mukerrer etkinlik olusmasini onler
_GCAL_ADVISORY_NAMESPACE = 0x6743

GCAL_EVENT_ORIGIN = 'roof'
GCAL_EVENT_ORIGIN_OFF = 'roof_off'
_GCAL_ADVISORY_NAMESPACE_OFF = 0x6744
_BUSY_LOOKBACK_DAYS = 90
_BUSY_LOOKAHEAD_DAYS = 90
# Tam ±90 gun listeleme her 2 dakikada yapilmasin; incremental inbound
# eslesmeyen etkinlikleri busy tablosuna yazar. Tam yenileme emniyet agi.
_BUSY_REFRESH_MIN_SECONDS = int(os.getenv('GOOGLE_CALENDAR_BUSY_REFRESH_SECONDS', '900'))
# Studio slot izgarasi saatlik (app.py SLOT_STEP_MINUTES ile ayni). Randevu
# olusturan iki uc nokta da duration_minutes % 60 == 0 sartini dayatiyor.
SLOT_GRID_MINUTES = 60
# Google client-supplied event id: ^[a-v0-9]{5,1024}$
# Timeout sonrasi tekrar insert mukerrer etkinlik uretmesin diye sabit id.
_STABLE_EVENT_ID_RE = re.compile(r'^[a-v0-9]{5,1024}$')
# Elle yazilan takvim basliklarinda telefon genelde bosluk/tire/nokta ile
# gruplanir (0532 123 45 67, 0532-123-45-67, +90 532...) — eski hali sadece
# 10 hanenin bitisik yazildigi hali yakaliyordu, digerlerinde eslesme
# bulunamayip _resolve_or_create_gcal_customer telefon-eslestirmesi hic
# calismiyordu. _normalize_customer_phone zaten ayirici/on-ek temizligini
# yapiyor, burada sadece adayi (span'i) genisletmek yeterli.
_GCAL_PHONE_RE = re.compile(r'(?<!\d)((?:\+?90[\s.\-]?)?0?5\d{2}[\s.\-]?\d{3}[\s.\-]?\d{2}[\s.\-]?\d{2})(?!\d)')
_OFF_DAY_KEYWORD_RE = re.compile(r'\b(off[\s\-]?day|offday|izin)\b')
_MIN_ARTIST_KEY_LEN = 3
_unmatched_artist_logged = set()
_UNMATCHED_LOG_CAP = 400

# Google Calendar etkinlik renkleri (colorId 1–11)
# https://developers.google.com/workspace/calendar/api/v3/reference/colors
GCAL_COLOR_TOMATO = '11'      # Domates
GCAL_COLOR_SAGE = '2'         # Adaçayı
GCAL_COLOR_TANGERINE = '6'    # Mandalina
GCAL_COLOR_BANANA = '5'       # Muz
GCAL_COLOR_GRAPHITE = '8'      # Granit / Grafit

GCAL_COLOR_NAMES = {
    '1': 'Lavender',
    '2': 'Sage',
    '3': 'Grape',
    '4': 'Flamingo',
    '5': 'Banana',
    '6': 'Tangerine',
    '7': 'Peacock',
    '8': 'Graphite',
    '9': 'Blueberry',
    '10': 'Basil',
    '11': 'Tomato',
}

# İsim (katlanmış ilk kelime) — stüdyo paleti
GCAL_STAFF_COLOR_BY_NAME = {
    'tuncer': GCAL_COLOR_TOMATO,
    'mert': GCAL_COLOR_SAGE,
    'berke': GCAL_COLOR_TANGERINE,
    'ibrahim': GCAL_COLOR_BANANA,
}

# staff_id yedek eşleme (Roof production)
GCAL_STAFF_COLOR_BY_ID = {
    1: GCAL_COLOR_TANGERINE,  # Berke — Mandalina
    2: GCAL_COLOR_TOMATO,     # Tuncer — Domates
    3: GCAL_COLOR_BANANA,     # İbrahim — Muz
    4: GCAL_COLOR_SAGE,       # Mert — Adaçayı
}

# Bilinmeyen sanatçı için dönüşümlü palet
GCAL_STAFF_COLOR_IDS = (
    GCAL_COLOR_TANGERINE,
    GCAL_COLOR_TOMATO,
    GCAL_COLOR_BANANA,
    GCAL_COLOR_SAGE,
    '7',
    '10',
    '9',
    '4',
    '3',
    '1',
)


def _color_id_for_staff(staff_id, staff_name=None):
    """Sanatçıya sabit Google Calendar colorId (1-11)."""
    if staff_name:
        first = _fold_tr(str(staff_name).split()[0] if str(staff_name).split() else '')
        if first in GCAL_STAFF_COLOR_BY_NAME:
            return GCAL_STAFF_COLOR_BY_NAME[first]
    try:
        sid = int(staff_id) if staff_id else None
    except (TypeError, ValueError):
        sid = None
    if sid in GCAL_STAFF_COLOR_BY_ID:
        return GCAL_STAFF_COLOR_BY_ID[sid]
    if not sid:
        return GCAL_COLOR_GRAPHITE
    return GCAL_STAFF_COLOR_IDS[(max(sid, 1) - 1) % len(GCAL_STAFF_COLOR_IDS)]


def _staff_color_label(staff_id, staff_name=None):
    color_id = _color_id_for_staff(staff_id, staff_name)
    return GCAL_COLOR_NAMES.get(color_id, color_id)


_STATUS_LABELS = {
    'pending': 'Bekliyor',
    'confirmed': 'Onaylandı',
    'completed': 'Tamamlandı',
    'cancelled': 'İptal',
    'no_show': 'Gelmedi',
}

_STYLE_LABELS = {
    'old_school': 'Old School / Traditional',
    'neo_traditional': 'Neo-Traditional',
    'realism': 'Realism',
    'fine_line': 'Fine Line / Minimalist',
    'geometric': 'Geometric',
    'watercolor': 'Watercolor',
    'irezumi': 'Irezumi',
    'blackwork': 'Blackwork',
    'tribal': 'Tribal',
    'trash_polka': 'Trash Polka',
    'black_grey_realism': 'Black and Grey Realism (Siyah-Gri Gerçekçilik)',
    'cyber_sigilism_modern_tribal': 'Cyber Sigilism / Modern Tribal',
    'trash_polka_sketch': 'Trash Polka & Sketch Style (Eskiz / Grafik)',
    'japanese_irezumi_blackwork': 'Japanese / Irezumi Blackwork',
    'fine_line_ornamental': 'Fine Line & Ornamental (Zarif Çizgi ve Süsleme)',
    'pet_portraits_micro_realism': 'Pet Portraits / Micro-Realism',
    'illustrative_blackwork': 'Illustrative Blackwork',
    'fine_line_botanical': 'Fine Line & Botanical (İnce Çizgi ve Botanik)',
    'ornamental_dotwork': 'Ornamental & Dotwork (Süsleme ve Noktalama)',
    'lettering_typography': 'Lettering & Typography (Yazı ve Kaligrafi)',
    'red_ink_minimal_color': 'Red Ink & Minimal Color (Kırmızı Mürekkep ve Renkli Minimalist)',
    'illustrative_pop_culture': 'Illustrative & Pop Culture (İllüstratif ve Popüler Kültür)',
    'surrealism_sketch': 'Surrealism & Sketch (Gerçeküstü ve Eskiz)',
    'micro_realism_black_grey': 'Micro-Realism / Black and Grey (Mikro Gerçekçilik / Siyah Gri)',
    'cyber_sigilism': 'Cyber Sigilism',
    'micro_realism_micro_black_grey': 'Micro-Realism / Micro Black & Grey',
    'dark_surrealism_dark_art': 'Dark Surrealism / Dark Art',
    'custom_lettering_calligraphy': 'Custom Lettering / Calligraphy',
    'pop_culture_cartoon_art': 'Pop Culture / Cartoon Art',
    'geometric_line_art': 'Geometric & Line Art',
    'black_grey_micro_realism': 'Black and Grey Realism & Micro-Realism (Siyah Gri Gerçekçilik)',
    'geometric_line_art_geo': 'Geometric & Line Art (Geometrik ve Çizgi Sanatı)',
    'trash_polka_sketch_graphic': 'Trash Polka & Sketch (Grafik ve Eskiz Tarzı)',
    'red_ink_color_highlights': 'Red Ink & Color Highlights (Kırmızı Mürekkep ve Renk Vurgusu)',
    'fine_line_minimalist': 'Fine Line & Minimalist (İnce Çizgi ve Minimal)',
    'japanese_oriental': 'Japanese / Oriental (Japon ve Uzak Doğu Estetiği)',
    'neo_traditional_pop_culture': 'Neo-Traditional & Pop Culture (Yeni Geleneksel ve Pop Kültür)',
    'surrealism_abstract': 'Surrealism & Abstract (Gerçeküstü ve Soyut)',
    'custom_lettering_typography': 'Custom Lettering & Typography (Özel Yazı ve Kaligrafi)',
    'tribal_polynesian_nordic': 'Tribal / Polynesian & Nordic (Kabile ve İskandinav)',
}

_REGION_LABELS = {
    'head': 'Baş / ense',
    'neck': 'Boyun',
    'chest': 'Göğüs',
    'ribs': 'Kaburga',
    'stomach': 'Karın',
    'back_upper': 'Üst sırt',
    'back_lower': 'Alt sırt / bel',
    'shoulder': 'Omuz',
    'upper_arm': 'Üst kol',
    'forearm': 'Ön kol',
    'wrist': 'Bilek',
    'hand': 'El / parmak',
    'thigh': 'Uyluk',
    'knee': 'Diz',
    'calf': 'Baldır',
    'ankle': 'Ayak bileği',
    'foot': 'Ayak üstü',
}


def is_google_calendar_enabled():
    cfg = get_google_calendar_config()
    if not cfg.get('enabled'):
        return False
    if not cfg.get('calendar_id'):
        logger.warning('Google Calendar: takvim kimliği tanımlı değil')
        return False
    cred_path = cfg.get('credentials_path')
    if not cred_path or not os.path.isfile(cred_path):
        logger.warning('Google Calendar: credentials dosyası bulunamadı: %s', cred_path)
        return False
    return True


def get_service_account_email():
    cfg = get_google_calendar_config()
    cred_path = cfg.get('credentials_path')
    if not cred_path or not os.path.isfile(cred_path):
        return None
    try:
        with open(cred_path, 'r') as f:
            data = json.load(f)
        return (data.get('client_email') or '').strip() or None
    except Exception:
        return None


def credentials_file_ok():
    cfg = get_google_calendar_config()
    cred_path = cfg.get('credentials_path')
    return bool(cred_path and os.path.isfile(cred_path))


def google_api_reachable(timeout=2.5):
    """Sunucunun Google OAuth uç noktasına TCP ile çıkıp çıkamadığı.

    Tam Calendar API çağrısı yapmaz; admin ayar sayfasını 45 sn askiya almaz.
    """
    try:
        socket.create_connection(('oauth2.googleapis.com', 443), timeout=timeout)
        return True
    except OSError:
        return False


def _service_fingerprint(cfg):
    """Kimlik dosyasi degisince cache'lenmis servisi tazelemek icin."""
    path = cfg.get('credentials_path') or ''
    try:
        return f'{path}:{os.path.getmtime(path)}'
    except OSError:
        return path


def _build_calendar_service(cfg):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        cfg['credentials_path'],
        scopes=_SCOPES,
    )
    try:
        import httplib2
        import google_auth_httplib2

        authorized_http = google_auth_httplib2.AuthorizedHttp(
            creds, http=httplib2.Http(timeout=GCAL_HTTP_TIMEOUT)
        )
        return build('calendar', 'v3', http=authorized_http, cache_discovery=False)
    except ImportError:
        logger.warning(
            'google_auth_httplib2/httplib2 yok; Google cagrilari timeout olmadan yapilacak'
        )
        return build('calendar', 'v3', credentials=creds, cache_discovery=False)


def _get_calendar_service():
    """Thread basina bir servis ornegi (googleapiclient thread-safe degil)."""
    cfg = get_google_calendar_config()
    fingerprint = _service_fingerprint(cfg)
    service = getattr(_thread_local, 'service', None)
    if service is not None and getattr(_thread_local, 'fingerprint', None) == fingerprint:
        return service
    service = _build_calendar_service(cfg)
    _thread_local.service = service
    _thread_local.fingerprint = fingerprint
    return service


def reset_calendar_service():
    """Ayarlar degistiginde cache'lenmis servisi dusur (bu thread icin)."""
    _thread_local.service = None
    _thread_local.fingerprint = None


def _google_execute(make_request):
    """Timeout veya gecici 5xx olursa servisi yenileyip tekrar dener.

    make_request her denemede taze Resource dondurmeli (_get_calendar_service
    iceride cagrilsin); aksi halde reset sonrasi olu Http nesnesi kalir.
    429 burada yenilenmez — cagiran kuyruk kotasini Retry-After ile yonetir.
    """
    last = None
    for attempt in range(3):
        try:
            return make_request().execute()
        except (TimeoutError, OSError) as exc:
            last = exc
            logger.warning(
                'Google API zaman asimi deneme %s/3: %s',
                attempt + 1,
                str(exc).strip()[:160],
            )
            reset_calendar_service()
            time.sleep(1.5 * (attempt + 1))
        except Exception as exc:
            status = _http_status(exc)
            if status in (500, 502, 503) and attempt < 2:
                last = exc
                logger.warning(
                    'Google API %s deneme %s/3: %s',
                    status,
                    attempt + 1,
                    str(exc).strip()[:160],
                )
                reset_calendar_service()
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last


def _http_status(exc):
    """googleapiclient HttpError icinden HTTP durum kodunu cikar."""
    resp = getattr(exc, 'resp', None)
    status = getattr(resp, 'status', None)
    if status is not None:
        try:
            return int(status)
        except (TypeError, ValueError):
            return None
    return getattr(exc, 'status_code', None)


def _is_missing_event_error(exc):
    """Etkinlik Google tarafinda yok (elle silinmis veya sure dolmus)."""
    status = _http_status(exc)
    if status in (404, 410):
        return True
    if status is not None:
        return False
    text = str(exc).lower()
    return '404' in text or '410' in text or 'not found' in text or 'deleted' in text


def _is_rate_limit_error(exc):
    status = _http_status(exc)
    if status == 429:
        return True
    if status != 403:
        return False
    text = str(exc).lower()
    return any(token in text for token in ('rate', 'quota', 'limit', 'userRateLimitExceeded'))


def _is_conflict_error(exc):
    """Ayni id ile etkinlik zaten var (bizim sabit id insert'i)."""
    status = _http_status(exc)
    if status == 409:
        return True
    if status is not None:
        return False
    text = str(exc).lower()
    return '409' in text or 'already exists' in text


def _stable_appointment_event_id(appointment_id):
    """Google'in izin verdigi karakterlerle randevuya sabit etkinlik kimligi."""
    return f'rtsa{int(appointment_id):010d}'


def _stable_time_off_event_id(time_off_id):
    return f'rtso{int(time_off_id):010d}'


def _upsert_calendar_event(calendar_id, body, existing_id, stable_id):
    """Etkinligi guncelle veya olustur. Timeout sonrasi mukerrer insert olmaz.

    Donus: (event_id, etag). stable_id Google kurallarina uymuyorsa gonderilmez.
    """
    if existing_id:
        try:
            event = _google_execute(
                lambda: _get_calendar_service().events().update(
                    calendarId=calendar_id, eventId=existing_id, body=body
                )
            )
            return event.get('id') or existing_id, event.get('etag')
        except Exception as exc:
            if not _is_missing_event_error(exc):
                raise
            logger.warning(
                'Google Calendar etkinligi yok, yeniden olusturuluyor | event=%s',
                existing_id,
            )

    insert_body = dict(body)
    if stable_id and _STABLE_EVENT_ID_RE.match(stable_id):
        insert_body['id'] = stable_id
    try:
        event = _google_execute(
            lambda: _get_calendar_service().events().insert(
                calendarId=calendar_id, body=insert_body
            )
        )
        return event.get('id') or stable_id, event.get('etag')
    except Exception as exc:
        if stable_id and _is_conflict_error(exc):
            event = _google_execute(
                lambda: _get_calendar_service().events().update(
                    calendarId=calendar_id, eventId=stable_id, body=body
                )
            )
            return event.get('id') or stable_id, event.get('etag')
        raise


def _delete_calendar_event(calendar_id, event_id):
    """Takvimden sil. Yoksa sessizce basarili sayar."""
    if not event_id:
        return
    try:
        _google_execute(
            lambda: _get_calendar_service().events().delete(
                calendarId=calendar_id, eventId=event_id
            )
        )
    except Exception as exc:
        if _is_missing_event_error(exc):
            return
        raise


def _retry_after_seconds(exc):
    resp = getattr(exc, 'resp', None)
    raw = None
    if resp is not None:
        getter = getattr(resp, 'get', None)
        if callable(getter):
            raw = getter('retry-after') or getter('Retry-After')
        elif hasattr(resp, 'headers'):
            headers = resp.headers
            raw = headers.get('retry-after') or headers.get('Retry-After')
    if raw is None:
        return None
    try:
        return max(1, int(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _studio_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(get_google_calendar_config().get('timezone') or 'Europe/Istanbul')
    except Exception:
        return None


def _content_hash(appointment_date, appointment_time, duration_minutes, status, staff_id):
    raw = '|'.join([
        str(_as_date(appointment_date)),
        _time_to_str(appointment_time),
        str(int(duration_minutes or 30)),
        str(status or ''),
        str(staff_id or ''),
    ])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def _extended_properties(appointment_id, content_hash):
    return {
        'private': {
            'origin': GCAL_EVENT_ORIGIN,
            'appointment_id': str(int(appointment_id)),
            'content_hash': str(content_hash or ''),
        }
    }


def _off_day_extended_properties(time_off_id):
    return {
        'private': {
            'origin': GCAL_EVENT_ORIGIN_OFF,
            'time_off_id': str(int(time_off_id)),
        }
    }


def _event_private(event):
    props = (event or {}).get('extendedProperties') or {}
    private = props.get('private') or {}
    return private if isinstance(private, dict) else {}


def _is_our_event(event):
    private = _event_private(event)
    origin = (private.get('origin') or '').strip()
    if origin in (GCAL_EVENT_ORIGIN, GCAL_EVENT_ORIGIN_OFF):
        return True
    description = (event or {}).get('description') or ''
    return 'Randevu ID:' in description or 'Off Day ID:' in description


def _is_off_day_origin(event):
    private = _event_private(event)
    origin = (private.get('origin') or '').strip()
    if origin == GCAL_EVENT_ORIGIN_OFF:
        return True
    description = (event or {}).get('description') or ''
    return 'Off Day ID:' in description


def _our_appointment_id_from_event(event):
    private = _event_private(event)
    raw = (private.get('appointment_id') or '').strip()
    if raw.isdigit():
        return int(raw)
    match = re.search(r'Randevu ID:\s*(\d+)', (event or {}).get('description') or '')
    return int(match.group(1)) if match else None


def _our_time_off_id_from_event(event):
    private = _event_private(event)
    raw = (private.get('time_off_id') or '').strip()
    if raw.isdigit():
        return int(raw)
    match = re.search(r'Off Day ID:\s*(\d+)', (event or {}).get('description') or '')
    return int(match.group(1)) if match else None


def _title_has_off_day_keyword(summary):
    folded = _fold_tr(_normalize_title_text(summary))
    return bool(_OFF_DAY_KEYWORD_RE.search(folded))


def _strip_off_day_keywords(title):
    remaining = _normalize_title_text(title)
    remaining = re.sub(r'(?i)off[\s\-]?day|offday|izin', ' ', remaining)
    return _normalize_title_text(remaining)


def _parse_off_day_from_title(summary, artist_rows):
    """Başlıktan Off Day sinyali: sanatçı, anahtar kelime, telefon, açıklama."""
    title = (summary or '').strip()
    phone = None
    match = _GCAL_PHONE_RE.search(title)
    if match:
        phone = _normalize_customer_phone(match.group(1))
        title_wo_phone = (title[:match.start()] + ' ' + title[match.end():]).strip()
    else:
        title_wo_phone = title

    has_keyword = _title_has_off_day_keyword(title)
    staff_id, staff_name, matched_key = _resolve_staff_from_title(title_wo_phone, artist_rows)
    remaining = title_wo_phone
    if staff_id:
        remaining = _strip_matched_artist(remaining, staff_name, matched_key)
    remaining = _strip_off_day_keywords(remaining)
    reason = remaining[:100] if remaining else ''
    return staff_id, staff_name, has_keyword, phone, reason


def _fold_tr(value):
    text = unicodedata.normalize('NFKD', value or '')
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    text = text.strip().lower()
    return (
        text.replace('ı', 'i').replace('İ', 'i')
        .replace('ş', 's').replace('Ş', 's')
        .replace('ğ', 'g').replace('Ğ', 'g')
        .replace('ü', 'u').replace('Ü', 'u')
        .replace('ö', 'o').replace('Ö', 'o')
        .replace('ç', 'c').replace('Ç', 'c')
    )


def parse_calendar_aliases(raw):
    """Takvim takma adlarını tekilleştirilmiş listeye çevirir."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = re.split(r'[,;\n]+', str(raw))
    out = []
    seen = set()
    for item in items:
        name = ' '.join(str(item).split())
        if not name:
            continue
        key = _fold_tr(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(name[:80])
    return out


def merge_calendar_aliases(existing, extra):
    return parse_calendar_aliases(list(existing or []) + list(extra or []))


def _normalize_customer_phone(raw):
    digits = ''.join(ch for ch in str(raw or '') if ch.isdigit())
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith('90'):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith('5'):
        return digits
    return None


def _synthetic_gcal_phone(event_id):
    digest = hashlib.sha256((event_id or '').encode('utf-8')).hexdigest()
    return ('1' + ''.join(ch for ch in digest if ch.isdigit()))[:10].ljust(10, '0')


def _split_person_name(full_name):
    parts = [p for p in re.split(r'\s+', (full_name or '').strip()) if p]
    if not parts:
        return 'Google', 'Takvim'
    if len(parts) == 1:
        return parts[0][:80], ''
    return parts[0][:80], ' '.join(parts[1:])[:80]


_GCAL_PLACEHOLDER_FOLDED = frozenset({'google', 'takvim', 'google takvim'})


def _customer_full_folded(name, surname):
    return _fold_tr(' '.join(
        p for p in ((name or '').strip(), (surname or '').strip()) if p
    ))


def is_real_customer_phone(phone):
    """Gercek bir TR cep numarasi mi (sentetik gcal numarasi degil)."""
    return _is_real_customer_phone(phone)


def _is_real_customer_phone(phone):
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if digits.startswith('90') and len(digits) > 10:
        digits = digits[2:]
    if digits.startswith('0'):
        digits = digits.lstrip('0')
    return len(digits) == 10 and digits.startswith('5')


def _pick_unique_customer_row(rows):
    if not rows:
        return None
    real = [row for row in rows if _is_real_customer_phone(row[1])]
    pool = real if real else list(rows)
    if len(pool) != 1:
        return None
    return pool[0]


def _match_customer_from_rows(name, surname, rows):
    """Kayıtlı müşteride tek ve net ad eşleşmesi; belirsizse None."""
    needle = _customer_full_folded(name, surname)
    compact = needle.replace(' ', '')
    if not compact or compact in _GCAL_PLACEHOLDER_FOLDED or needle in _GCAL_PLACEHOLDER_FOLDED:
        return None
    if len(compact) < 3:
        return None

    usable = []
    for row in rows or []:
        if not row or len(row) < 4:
            continue
        full = _customer_full_folded(row[2], row[3])
        if not full or full in _GCAL_PLACEHOLDER_FOLDED:
            continue
        usable.append(row)

    exact = [row for row in usable if _customer_full_folded(row[2], row[3]) == needle]
    picked = _pick_unique_customer_row(exact)
    if picked:
        return picked[0]

    if (surname or '').strip():
        return None

    first = _fold_tr((name or '').strip())
    if not first:
        return None
    first_hits = [row for row in usable if _fold_tr((row[2] or '').strip()) == first]
    picked = _pick_unique_customer_row(first_hits)
    return picked[0] if picked else None


def _normalize_title_text(value):
    text = (value or '').replace('[', ' ').replace(']', ' ')
    text = re.sub(r'[·|:_/,]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _artist_name_keys(name):
    """Tam ad ve ardışık kelime grupları. Kısa/belirsiz parçalar elenir."""
    folded = _fold_tr(_normalize_title_text(name))
    folded = re.sub(r'[^a-z0-9\s]+', ' ', folded)
    folded = re.sub(r'\s+', ' ', folded).strip()
    if not folded:
        return set()
    keys = {folded}
    tokens = folded.split()
    for start in range(len(tokens)):
        for end in range(start + 1, len(tokens) + 1):
            chunk = ' '.join(tokens[start:end])
            compact = chunk.replace(' ', '')
            if len(compact) >= _MIN_ARTIST_KEY_LEN:
                keys.add(chunk)
    return keys


def _key_in_title(folded_title, key):
    if not folded_title or not key:
        return False
    return re.search(
        r'(?<![a-z0-9])' + re.escape(key) + r'(?![a-z0-9])',
        folded_title,
    ) is not None


def _resolve_staff_from_title(title, artist_rows):
    """Başlıkta tek sanatçı eşleşsin. Tahmin yok; belirsizse None."""
    folded_title = _fold_tr(_normalize_title_text(title))
    if not folded_title:
        return None, None, None

    best_len = -1
    best = {}
    for row in artist_rows or []:
        artist_id, name = row[0], row[1]
        aliases = row[2] if len(row) > 2 else None
        keys = set(_artist_name_keys(name))
        for alias in parse_calendar_aliases(aliases):
            keys.update(_artist_name_keys(alias))
        for key in keys:
            if not _key_in_title(folded_title, key):
                continue
            key_len = len(key)
            if key_len > best_len:
                best_len = key_len
                best = {artist_id: (name, key)}
            elif key_len == best_len:
                best[artist_id] = (name, key)

    if len(best) != 1:
        return None, None, None
    artist_id, (name, key) = next(iter(best.items()))
    return artist_id, name, key


def _strip_matched_artist(title, staff_name, matched_key):
    remaining = _normalize_title_text(title)
    for piece in (staff_name, matched_key):
        if not piece:
            continue
        remaining = re.sub(
            r'(?i)(?<!\w)' + re.escape(piece) + r'(?!\w)',
            ' ',
            remaining,
            count=1,
        )
    remaining = re.sub(r'\s+', ' ', remaining).strip(' -·|:')
    return remaining


def _log_unmatched_artist(event_id, summary):
    if event_id in _unmatched_artist_logged:
        return
    if len(_unmatched_artist_logged) >= _UNMATCHED_LOG_CAP:
        _unmatched_artist_logged.clear()
    _unmatched_artist_logged.add(event_id)
    logger.warning(
        'Google etkinliginde sanatci eslesmedi, randevu yazilmadi | event=%s title=%s',
        event_id,
        (summary or '')[:120],
    )


def _parse_manual_event_title(summary, artist_rows):
    """Başliktan sanatçı, müşteri adı ve telefon çıkar. Sanatçı yoksa staff_id None."""
    title = (summary or '').strip()
    phone = None
    match = _GCAL_PHONE_RE.search(title)
    if match:
        phone = _normalize_customer_phone(match.group(1))
        title = (title[:match.start()] + ' ' + title[match.end():]).strip()

    staff_id, staff_name, matched_key = _resolve_staff_from_title(title, artist_rows)
    if staff_id:
        title = _strip_matched_artist(title, staff_name, matched_key)
    else:
        title = _normalize_title_text(title)

    title = re.sub(r'^\s*[·\-|:]+\s*', '', title).strip()
    folded_left = _fold_tr(title)
    if not title or folded_left in (_fold_tr(staff_name or ''), _fold_tr(matched_key or '')):
        return staff_id, staff_name, 'Google', 'Takvim', phone
    customer_name, customer_surname = _split_person_name(title)
    return staff_id, staff_name, customer_name, customer_surname, phone


def _is_placeholder_person(name, surname):
    folded = _customer_full_folded(name, surname)
    compact = folded.replace(' ', '')
    return (not compact) or compact in _GCAL_PLACEHOLDER_FOLDED or folded in _GCAL_PLACEHOLDER_FOLDED


def _subscribe_calendar(service, calendar_id):
    """Servis hesabının calendarList'ine ekle (paylaşıldıktan sonra gerekli)."""
    try:
        service.calendarList().insert(body={'id': calendar_id}).execute()
    except Exception:
        pass


def probe_google_calendar(calendar_id=None):
    cfg = get_google_calendar_config()
    calendar_id = (calendar_id or cfg.get('calendar_id') or '').strip()
    email = get_service_account_email()
    if not credentials_file_ok():
        return {'ok': False, 'message': 'Google kimlik dosyası sunucuda yok.'}
    if not calendar_id:
        return {'ok': False, 'message': 'Takvim kimliği boş.'}
    try:
        service = _get_calendar_service()
        _subscribe_calendar(service, calendar_id)
        cal = service.calendars().get(calendarId=calendar_id).execute()
        return {
            'ok': True,
            'calendar_id': cal.get('id') or calendar_id,
            'summary': cal.get('summary') or calendar_id,
            'time_zone': cal.get('timeZone') or cfg.get('timezone'),
        }
    except (TimeoutError, OSError, socket.timeout) as e:
        return {
            'ok': False,
            'network': True,
            'message': (
                'Sunucu Google sunucularına ulaşamıyor (ağ / güvenlik duvarı). '
                'Kimlik dosyası duruyor; barındırıcıda 443 çıkışını kontrol edin.'
            ),
            'error': str(e)[:240],
        }
    except Exception as e:
        hint = email or 'servis hesabı e-postası'
        return {
            'ok': False,
            'message': (
                f'Takvime erişilemedi. Google Takvim ayarlarından bu takvimi '
                f'{hint} adresiyle paylaşın ve “Etkinlikleri değiştir” izni verin.'
            ),
            'error': str(e)[:240],
        }


def list_accessible_calendars():
    if not credentials_file_ok():
        return []
    try:
        service = _get_calendar_service()
        items = []
        page_token = None
        while True:
            resp = service.calendarList().list(pageToken=page_token, maxResults=50).execute()
            for item in resp.get('items') or []:
                cal_id = (item.get('id') or '').strip()
                if not cal_id:
                    continue
                items.append({
                    'id': cal_id,
                    'summary': item.get('summary') or cal_id,
                    'primary': bool(item.get('primary')),
                    'access_role': item.get('accessRole') or '',
                })
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        return items
    except Exception as e:
        logger.warning('Google Calendar listesi alınamadı: %s', e)
        return []


_conn_acquire = None
_conn_release = None


def set_connection_provider(acquire, release):
    """app.py'nin baglanti havuzunu kullan (her senkronda yeni baglanti acmamak icin).

    Kayit yapilmazsa (ornegin scripts/ altindan calisirken) dogrudan baglanti
    acilir.
    """
    global _conn_acquire, _conn_release
    _conn_acquire = acquire
    _conn_release = release


def _connect():
    if _conn_acquire is not None:
        return _conn_acquire()
    return psycopg2.connect(
        host=DATABASE_CONFIG['host'],
        port=DATABASE_CONFIG['port'],
        user=DATABASE_CONFIG['user'],
        password=DATABASE_CONFIG['password'],
        database=DATABASE_CONFIG['database'],
        **({'sslmode': DATABASE_CONFIG['sslmode']} if DATABASE_CONFIG.get('sslmode') else {}),
    )


def _disconnect(conn):
    if conn is None:
        return
    if _conn_release is not None:
        _conn_release(conn)
        return
    try:
        conn.close()
    except Exception:
        pass


def _time_to_str(value):
    if value is None:
        return '00:00'
    if isinstance(value, dt_time):
        return value.strftime('%H:%M')
    return str(value)[:5]


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def _appointment_window(appointment_date, appointment_time, duration_minutes):
    """Admin paneldeki saat ile birebir (duvar saati + IANA timezone)."""
    tz_name = get_google_calendar_config().get('timezone', 'Europe/Istanbul')
    day = _as_date(appointment_date)
    time_str = _time_to_str(appointment_time)
    hour, minute = map(int, time_str.split(':'))
    # Google API: dateTime offset'siz + ayrı timeZone alanı (ikisi birden 400 verebilir)
    start_local = datetime.combine(day, dt_time(hour, minute))
    end_local = start_local + timedelta(minutes=int(duration_minutes or 30))
    start_iso = start_local.strftime('%Y-%m-%dT%H:%M:%S')
    end_iso = end_local.strftime('%Y-%m-%dT%H:%M:%S')
    return start_iso, end_iso, tz_name


def _time_off_minutes(start_time, end_time):
    if start_time is None:
        return None, None
    start_m = _time_str_to_minutes_local(str(start_time)[:5])
    end_str = str(end_time)[:5] if end_time else '00:00'
    end_m = 24 * 60 if end_str in ('00:00', '24:00') else _time_str_to_minutes_local(end_str)
    if end_m <= start_m:
        end_m = 24 * 60
    return start_m, end_m


def _time_str_to_minutes_local(value):
    parts = str(value or '00:00').split(':')
    return int(parts[0]) * 60 + int(parts[1])


def _time_off_window(off_date, start_time, end_time):
    """Off Day Google start/end. all_day ise date; değilse dateTime."""
    tz_name = get_google_calendar_config().get('timezone', 'Europe/Istanbul')
    day = _as_date(off_date)
    if start_time is None:
        nxt = day + timedelta(days=1)
        return {
            'all_day': True,
            'start': {'date': day.isoformat()},
            'end': {'date': nxt.isoformat()},
            'tz': tz_name,
        }
    start_m, end_m = _time_off_minutes(start_time, end_time)
    start_local = datetime.combine(day, dt_time(start_m // 60, start_m % 60))
    end_local = datetime.combine(day, dt_time(0, 0)) + timedelta(minutes=end_m)
    return {
        'all_day': False,
        'start': {
            'dateTime': start_local.strftime('%Y-%m-%dT%H:%M:%S'),
            'timeZone': tz_name,
        },
        'end': {
            'dateTime': end_local.strftime('%Y-%m-%dT%H:%M:%S'),
            'timeZone': tz_name,
        },
        'tz': tz_name,
    }


def _phone_display(phone):
    if not phone:
        return '-'
    p = ''.join(ch for ch in str(phone).strip() if ch.isdigit())
    if len(p) == 10:
        return f'0{p}'
    if len(p) == 11 and p.startswith('0'):
        return p
    return str(phone).strip()


def _label_from_map(value, mapping):
    if not value:
        return '-'
    key = str(value).strip()
    return mapping.get(key, key.replace('_', ' ').title())


def _customer_display(name, surname, phone):
    full = f"{name or ''} {surname or ''}".strip()
    if full:
        return full
    display_phone = _phone_display(phone)
    if display_phone != '-':
        return display_phone
    return 'Müşteri'


def _build_event_body(row):
    (
        appointment_id,
        appointment_date,
        appointment_time,
        status,
        duration_minutes,
        price,
        customer_name,
        customer_surname,
        customer_phone,
        staff_id,
        staff_name,
        body_area,
        tattoo_size,
        tattoo_style,
        request_description,
        reference_number,
        google_event_id,
    ) = row

    customer = _customer_display(customer_name, customer_surname, customer_phone)
    phone = _phone_display(customer_phone)
    status_label = _STATUS_LABELS.get(str(status), str(status))
    style_label = _label_from_map(tattoo_style, _STYLE_LABELS)
    area_label = _label_from_map(body_area, _REGION_LABELS)
    size = tattoo_size or '-'
    time_label = _time_to_str(appointment_time)
    duration = int(duration_minutes or 30)
    artist = (staff_name or 'Sanatçı').strip()
    color_id = _color_id_for_staff(staff_id, artist)

    summary_parts = [f'[{artist}]', customer]
    if phone != '-':
        summary_parts.append(phone)
    if style_label != '-':
        summary_parts.append(style_label)
    if area_label != '-':
        summary_parts.append(area_label)
    summary = ' · '.join(summary_parts)
    if status == 'completed':
        summary = f"✓ {summary}"
    elif status == 'pending':
        summary = f"⏳ {summary}"

    lines = [
        f"📅 Tarih: {_as_date(appointment_date).strftime('%d.%m.%Y')}  ⏰ Saat: {time_label}",
        f"Durum: {status_label}",
        f"Sanatçı: {artist}",
        '',
        '— Müşteri —',
        f"Ad Soyad: {customer}",
        f"Telefon: {phone}",
        '',
        '— Dövme —',
        f"Bölge: {area_label}",
        f"Boyut: {size}",
        f"Süre: {duration} dk",
    ]
    if reference_number:
        lines.append(f"Referans No: {reference_number}")
    if request_description and str(request_description).strip():
        lines.append(f"Not: {str(request_description).strip()}")
    if price is not None and float(price or 0) > 0:
        lines.append(f"Ücret: {format_try(float(price))} ₺")
    # Isletme adi/telefon/adres/randevu ID/tarz/takvim rengi etiketi etkinlik
    # aciklamasinda gereksiz gorunuyordu — kaldirildi.

    start_iso, end_iso, tz = _appointment_window(
        appointment_date, appointment_time, duration_minutes
    )

    body = {
        'summary': summary[:200],
        'description': '\n'.join(lines)[:5000],
        'start': {'dateTime': start_iso, 'timeZone': tz},
        'end': {'dateTime': end_iso, 'timeZone': tz},
        'colorId': color_id,
        'extendedProperties': _extended_properties(
            appointment_id,
            _content_hash(appointment_date, appointment_time, duration_minutes, status, staff_id),
        ),
        'existing_event_id': google_event_id,
    }
    return body


def _build_time_off_event_body(row):
    (
        time_off_id,
        staff_id,
        staff_name,
        off_date,
        start_time,
        end_time,
        reason,
        google_event_id,
    ) = row
    artist = (staff_name or 'Sanatçı').strip()
    color_id = GCAL_COLOR_GRAPHITE
    color_label = GCAL_COLOR_NAMES.get(color_id, 'Graphite')
    reason_text = (reason or '').strip()
    summary_parts = [f'[{artist}]', 'Off Day']
    if reason_text:
        summary_parts.append(reason_text)
    summary = ' · '.join(summary_parts)
    day = _as_date(off_date)
    if start_time is None:
        when_line = f"📅 Tarih: {day.strftime('%d.%m.%Y')}  (tüm gün)"
    else:
        when_line = (
            f"📅 Tarih: {day.strftime('%d.%m.%Y')}  "
            f"⏰ {_time_to_str(start_time)}–{_time_to_str(end_time)}"
        )
    lines = [
        when_line,
        f"Sanatçı: {artist}",
        f"Takvim rengi: Granit ({color_label})",
        f"Açıklama: {reason_text or '-'}",
        '',
        f"Off Day ID: {time_off_id}",
    ]
    window = _time_off_window(off_date, start_time, end_time)
    body = {
        'summary': summary[:200],
        'description': '\n'.join(lines)[:5000],
        'start': window['start'],
        'end': window['end'],
        'colorId': color_id,
        'transparency': 'opaque',
        'extendedProperties': _off_day_extended_properties(time_off_id),
        'existing_event_id': google_event_id,
    }
    return body


def _fetch_time_off_row(cursor, time_off_id):
    cursor.execute(
        """
        SELECT
            t.id,
            t.staff_id,
            s.name,
            t.off_date,
            t.start_time,
            t.end_time,
            t.reason,
            t.google_event_id
        FROM time_off t
        JOIN artists s ON s.id = t.staff_id
        WHERE t.id = %s
        """,
        (time_off_id,),
    )
    return cursor.fetchone()


def _fetch_appointment_row(cursor, appointment_id):
    cursor.execute(
        """
        SELECT
            a.id,
            a.appointment_date,
            a.appointment_time,
            a.status,
            a.duration_minutes,
            a.price,
            COALESCE(c.name, ''),
            COALESCE(c.surname, ''),
            c.phone,
            a.staff_id,
            s.name,
            COALESCE(tr.body_area, ''),
            COALESCE(tr.size, ''),
            COALESCE(tr.tattoo_style, ''),
            tr.description,
            tr.reference_number,
            a.google_event_id
        FROM appointments a
        JOIN customers c ON a.customer_id = c.id
        JOIN artists s ON a.staff_id = s.id
        LEFT JOIN tattoo_requests tr ON a.tattoo_request_id = tr.id
        WHERE a.id = %s
        """,
        (appointment_id,),
    )
    return cursor.fetchone()


def _perform_appointment_sync(appointment_id):
    """Randevuyu takvime yaz/guncelle.

    Donus: (durum, event_id) — durum 'ok' | 'gone' | 'busy' | 'disabled'.
    Gercek API/DB hatalarinda exception firlatir; cagiran tekrar denemeye karar
    verir.
    """
    if not is_google_calendar_enabled():
        return 'disabled', None

    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()

        # Ayni randevunun iki paralel senkronu iki ayri etkinlik olusturabilir.
        # Kilit alinamazsa is birakilmaz, kisa sure sonra tekrar denenir.
        cursor.execute(
            'SELECT pg_try_advisory_xact_lock(%s, %s)',
            (_GCAL_ADVISORY_NAMESPACE, int(appointment_id)),
        )
        if not cursor.fetchone()[0]:
            conn.rollback()
            return 'busy', None

        row = _fetch_appointment_row(cursor, appointment_id)
        if not row:
            # Randevu kuyruga girdikten sonra silinmis; yapilacak is yok.
            conn.rollback()
            logger.info('Google Calendar: randevu #%s yok, senkron atlandi', appointment_id)
            return 'gone', None

        status = str(row[3] or '')
        if status == 'cancelled':
            conn.rollback()
            logger.info('Google Calendar: randevu #%s iptal, yazma atlandi', appointment_id)
            return 'gone', None

        payload = _build_event_body(row)
        existing_id = payload.pop('existing_event_id', None)
        calendar_id = get_google_calendar_config()['calendar_id']
        body = {
            key: payload[key]
            for key in (
                'summary', 'description', 'start', 'end', 'location',
                'colorId', 'extendedProperties',
            )
            if key in payload
        }

        event_id, etag = _upsert_calendar_event(
            calendar_id,
            body,
            existing_id,
            _stable_appointment_event_id(appointment_id),
        )
        if existing_id and event_id == existing_id:
            logger.info(
                'Google Calendar guncellendi: apt #%s event %s', appointment_id, event_id
            )
        else:
            logger.info(
                'Google Calendar olusturuldu: apt #%s event %s', appointment_id, event_id
            )

        if event_id:
            cursor.execute(
                """
                UPDATE appointments
                   SET google_event_id = %s,
                       google_etag = %s,
                       google_calendar_id = %s,
                       google_updated_at = NOW()
                 WHERE id = %s
                RETURNING id
                """,
                (event_id, etag, calendar_id, appointment_id),
            )
            if not cursor.fetchone():
                conn.rollback()
                try:
                    _delete_calendar_event(calendar_id, event_id)
                except Exception:
                    pass
                logger.info(
                    'Google Calendar: randevu #%s yazilirken silindi, etkinlik geri alindi',
                    appointment_id,
                )
                return 'gone', None

        conn.commit()
        cursor.close()
        return 'ok', event_id
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        _disconnect(conn)


def _perform_time_off_sync(time_off_id):
    """Off Day satırını takvime yaz/güncelle. Donus: (durum, event_id)."""
    if not is_google_calendar_enabled():
        return 'disabled', None

    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT pg_try_advisory_xact_lock(%s, %s)',
            (_GCAL_ADVISORY_NAMESPACE_OFF, int(time_off_id)),
        )
        if not cursor.fetchone()[0]:
            conn.rollback()
            return 'busy', None

        row = _fetch_time_off_row(cursor, time_off_id)
        if not row:
            conn.rollback()
            logger.info('Google Calendar: Off Day #%s yok, senkron atlandi', time_off_id)
            return 'gone', None

        payload = _build_time_off_event_body(row)
        existing_id = payload.pop('existing_event_id', None)
        calendar_id = get_google_calendar_config()['calendar_id']
        body = {
            key: payload[key]
            for key in (
                'summary', 'description', 'start', 'end', 'location',
                'colorId', 'extendedProperties', 'transparency',
            )
            if key in payload
        }

        event_id, etag = _upsert_calendar_event(
            calendar_id,
            body,
            existing_id,
            _stable_time_off_event_id(time_off_id),
        )
        if existing_id and event_id == existing_id:
            logger.info(
                'Google Calendar Off Day guncellendi: #%s event %s',
                time_off_id, event_id,
            )
        else:
            logger.info(
                'Google Calendar Off Day olusturuldu: #%s event %s',
                time_off_id, event_id,
            )

        if event_id:
            cursor.execute(
                """
                UPDATE time_off
                   SET google_event_id = %s,
                       google_etag = %s,
                       google_calendar_id = %s,
                       google_updated_at = NOW()
                 WHERE id = %s
                RETURNING id
                """,
                (event_id, etag, calendar_id, time_off_id),
            )
            if not cursor.fetchone():
                conn.rollback()
                try:
                    _delete_calendar_event(calendar_id, event_id)
                except Exception:
                    pass
                logger.info(
                    'Google Calendar: Off Day #%s yazilirken silindi, etkinlik geri alindi',
                    time_off_id,
                )
                return 'gone', None

        conn.commit()
        cursor.close()
        return 'ok', event_id
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        _disconnect(conn)


def _perform_event_delete(google_event_id):
    """Takvimden etkinligi sil. Zaten yoksa basarili sayar."""
    if not is_google_calendar_enabled():
        return 'disabled'
    if not google_event_id:
        return 'ok'

    calendar_id = get_google_calendar_config()['calendar_id']
    try:
        _delete_calendar_event(calendar_id, google_event_id)
        logger.info('Google Calendar etkinlik silindi: %s', google_event_id)
        return 'ok'
    except Exception as exc:
        if _is_missing_event_error(exc):
            logger.info('Google Calendar etkinlik zaten yok: %s', google_event_id)
            return 'ok'
        raise


def sync_appointment_to_google(appointment_id):
    """Tek randevuyu simdi senkronla (scripts/ ve elle kullanim icin).

    Istek yolundan cagirmayin: bloke eder. Endpoint'ler enqueue_appointment_sync
    kullanir.
    """
    try:
        status, event_id = _perform_appointment_sync(appointment_id)
        return event_id if status == 'ok' else None
    except Exception as e:
        log_error(
            logger,
            E_GCAL_001,
            'Google Takvim senkronu basarisiz',
            exc=e,
            appointment_id=appointment_id,
        )
        return None


def delete_google_calendar_event(google_event_id):
    """Etkinligi simdi sil (scripts/ ve elle kullanim icin)."""
    try:
        return _perform_event_delete(google_event_id) == 'ok'
    except Exception as e:
        log_error(
            logger,
            E_GCAL_001,
            'Google Takvim etkinligi silinemedi',
            exc=e,
            google_event_id=google_event_id,
        )
        return False


# =============================================
# SENKRON KUYRUGU (OUTBOX)
# =============================================

_QUEUE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS google_calendar_queue (
        id BIGSERIAL PRIMARY KEY,
        operation VARCHAR(16) NOT NULL,
        appointment_id INTEGER,
        google_event_id VARCHAR(255),
        time_off_id INTEGER,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        dead_at TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_gcq_pending
        ON google_calendar_queue (next_attempt_at, id)
        WHERE dead_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_gcq_appointment
        ON google_calendar_queue (appointment_id)
        WHERE dead_at IS NULL AND operation = 'upsert'
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_gcq_time_off
        ON google_calendar_queue (time_off_id)
        WHERE dead_at IS NULL AND operation = 'upsert'
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_gcq_dead
        ON google_calendar_queue (dead_at)
        WHERE dead_at IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_google_event_id
        ON appointments (google_event_id)
        WHERE google_event_id IS NOT NULL
    """,
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS google_etag VARCHAR(255)",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS google_updated_at TIMESTAMPTZ",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR(255)",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP",
    "ALTER TABLE google_calendar_queue ADD COLUMN IF NOT EXISTS time_off_id INTEGER",
    """
    ALTER TABLE google_calendar_queue
        ADD COLUMN IF NOT EXISTS busy_deferrals INTEGER NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE time_off
        ADD COLUMN IF NOT EXISTS google_event_id VARCHAR(255)
    """,
    "ALTER TABLE time_off ADD COLUMN IF NOT EXISTS google_etag VARCHAR(255)",
    "ALTER TABLE time_off ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR(255)",
    "ALTER TABLE time_off ADD COLUMN IF NOT EXISTS google_updated_at TIMESTAMPTZ",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_time_off_google_event_id
        ON time_off (google_event_id)
        WHERE google_event_id IS NOT NULL
    """,
    "ALTER TABLE google_calendar_queue DROP CONSTRAINT IF EXISTS gcq_payload_check",
    """
    ALTER TABLE google_calendar_queue DROP CONSTRAINT IF EXISTS google_calendar_queue_gcq_payload_check
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'gcq_payload_check'
        ) THEN
            ALTER TABLE google_calendar_queue
                ADD CONSTRAINT gcq_payload_check CHECK (
                    (
                        operation = 'upsert'
                        AND appointment_id IS NOT NULL
                        AND time_off_id IS NULL
                    )
                    OR (
                        operation = 'upsert'
                        AND time_off_id IS NOT NULL
                        AND appointment_id IS NULL
                    )
                    OR (
                        operation = 'delete'
                        AND google_event_id IS NOT NULL
                    )
                );
        END IF;
    END $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS google_external_busy (
        id BIGSERIAL PRIMARY KEY,
        calendar_id VARCHAR(255) NOT NULL,
        start_at TIMESTAMPTZ NOT NULL,
        end_at TIMESTAMPTZ NOT NULL,
        google_event_id VARCHAR(255),
        synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_gcal_external_busy_span
        ON google_external_busy (calendar_id, start_at, end_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS google_calendar_sync_state (
        calendar_id VARCHAR(255) PRIMARY KEY,
        events_sync_token TEXT,
        last_busy_at TIMESTAMPTZ,
        last_events_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
)


def ensure_queue_table():
    """Kuyruk tablosu ve indeksleri (idempotent, acilista cagrilir).

    Her ifade kendi transaction'inda calisir; biri basarisiz olsa (ornegin
    mukerrer event_id yuzunden unique index) digerleri kurulur.
    """
    conn = None
    ok = True
    try:
        conn = _connect()
        for statement in _QUEUE_DDL:
            cursor = conn.cursor()
            try:
                cursor.execute(statement)
                conn.commit()
            except Exception as e:
                conn.rollback()
                ok = False
                logger.warning(
                    'Takvim kuyrugu DDL atlandi | hata=%s', str(e).strip()[:200]
                )
            finally:
                cursor.close()
        _ensure_partial_slot_unique_index(conn)
        _ensure_artist_calendar_aliases(conn)
        return ok
    except Exception as e:
        log_error(logger, E_GCAL_002, 'Takvim senkron kuyrugu hazirlanamadi', exc=e)
        return False
    finally:
        _disconnect(conn)


def ensure_time_off_multi_day_support():
    """Coklu gunluk Off Day destegi: time_off eskiden Google etkinligi basina
    tek satir tutuyordu (UNIQUE(google_event_id)), bu yuzden birden fazla gun
    suren bir etkinlik sadece ilk gunu kapatiyordu. Artik etkinlik basina
    (gun sayisi kadar) birden fazla satir yazilabiliyor — eski tekil kisiti
    (google_event_id, off_date) ikilisi uzerinden UNIQUE'e gevsetir.
    """
    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("DROP INDEX IF EXISTS uq_time_off_google_event_id")
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_time_off_google_event_id_date
            ON time_off (google_event_id, off_date)
            WHERE google_event_id IS NOT NULL
            """
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.warning('ensure_time_off_multi_day_support: %s', str(e).strip()[:200])
    finally:
        _disconnect(conn)


def _ensure_partial_slot_unique_index(conn):
    """Iptal satirlar ayni slotu yeni randevuya biraksin."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT pg_get_indexdef(c.oid)
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relname = 'appointments_staff_date_time_uidx'
               AND n.nspname = 'public'
            """
        )
        row = cursor.fetchone()
        definition = (row[0] or '') if row else ''
        if 'cancelled' in definition.lower():
            conn.commit()
            return
        cursor.execute('DROP INDEX IF EXISTS appointments_staff_date_time_uidx')
        cursor.execute(
            """
            CREATE UNIQUE INDEX appointments_staff_date_time_uidx
                ON appointments (staff_id, appointment_date, appointment_time)
                WHERE status IS DISTINCT FROM 'cancelled'
            """
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning('Randevu slot unique index guncellenemedi: %s', str(e).strip()[:200])
    finally:
        cursor.close()


def _ensure_artist_calendar_aliases(conn):
    """Takvim takma ad kolonu (ad değişince eski yazım elle eklenebilir)."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            ALTER TABLE artists
                ADD COLUMN IF NOT EXISTS calendar_aliases TEXT[] NOT NULL DEFAULT '{}'
            """
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning('Takvim takma ad kolonu hazirlanamadi: %s', str(e).strip()[:200])
    finally:
        cursor.close()


def _enqueue(cursor, operation, appointment_id=None, google_event_id=None, time_off_id=None):
    """Cagiranin transaction'i icinde kuyruga is ekler.

    SAVEPOINT kullanilir: kuyruk yazimi basarisiz olsa bile cagiranin
    transaction'i bozulmaz, yani randevu kaydi takvim yuzunden kaybolmaz.
    """
    try:
        cursor.execute('SAVEPOINT gcal_enqueue')
    except Exception as e:
        logger.warning('Takvim kuyrugu icin savepoint alinamadi: %s', e)
        return False
    try:
        cursor.execute(
            """
            INSERT INTO google_calendar_queue
                (operation, appointment_id, google_event_id, time_off_id)
            VALUES (%s, %s, %s, %s)
            """,
            (operation, appointment_id, google_event_id, time_off_id),
        )
        cursor.execute('RELEASE SAVEPOINT gcal_enqueue')
        return True
    except Exception as e:
        try:
            cursor.execute('ROLLBACK TO SAVEPOINT gcal_enqueue')
        except Exception:
            pass
        log_error(
            logger,
            E_GCAL_002,
            'Takvim isi kuyruga eklenemedi',
            exc=e,
            operation=operation,
            appointment_id=appointment_id,
            google_event_id=google_event_id,
            time_off_id=time_off_id,
        )
        return False


def enqueue_appointment_sync(cursor, appointment_id):
    """Randevu olustu/degisti -> takvime yazilacak (commit ile ayni transaction).

    Takvim hatasi randevu kaydini veya durum guncellemesini asla dusurmez.
    """
    try:
        if not appointment_id or not is_google_calendar_enabled():
            return False
        return _enqueue(cursor, 'upsert', appointment_id=int(appointment_id))
    except Exception as e:
        logger.warning(
            'Takvim kuyrugu randevu akisini kesmedi appointment_id=%s: %s',
            appointment_id,
            str(e).strip()[:200],
        )
        return False


def enqueue_time_off_sync(cursor, time_off_id):
    """Off Day olustu/degisti -> takvime yazilacak (commit ile ayni transaction)."""
    try:
        if not time_off_id or not is_google_calendar_enabled():
            return False
        return _enqueue(cursor, 'upsert', time_off_id=int(time_off_id))
    except Exception as e:
        logger.warning(
            'Takvim kuyrugu Off Day akisini kesmedi time_off_id=%s: %s',
            time_off_id,
            str(e).strip()[:200],
        )
        return False


def enqueue_event_delete(cursor, google_event_id):
    """Randevu satiri silinecek -> takvimdeki etkinlik de silinecek.

    Satir silinmeden ONCE cagirilmali: event_id kuyruga yazilmazsa Google
    cagrisi basarisiz oldugunda etkinligi bir daha bulmanin yolu kalmaz.
    Takvim hatasi silme/iptal islemini asla dusurmez.
    """
    try:
        event_id = (google_event_id or '').strip()
        if not event_id or not is_google_calendar_enabled():
            return False
        return _enqueue(cursor, 'delete', google_event_id=event_id)
    except Exception as e:
        logger.warning(
            'Takvim silme kuyrugu ana islemi kesmedi event_id=%s: %s',
            google_event_id,
            str(e).strip()[:200],
        )
        return False


def enqueue_event_deletes(cursor, google_event_ids):
    """Toplu silme (temizlik isleri, personel silme)."""
    count = 0
    for event_id in google_event_ids or []:
        if enqueue_event_delete(cursor, event_id):
            count += 1
    return count


def _claim_next_item(conn):
    """Siradaki isi kirala (kisa lease ile), boylece baska worker ayni isi almaz."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            WITH claimed AS (
                SELECT id
                  FROM google_calendar_queue
                 WHERE dead_at IS NULL
                   AND next_attempt_at <= NOW()
                 ORDER BY next_attempt_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE google_calendar_queue q
               SET attempts = q.attempts + 1,
                   next_attempt_at = NOW() + %s * INTERVAL '1 second'
              FROM claimed c
             WHERE q.id = c.id
            RETURNING q.id, q.operation, q.appointment_id, q.google_event_id, q.attempts, q.time_off_id
            """,
            (_CLAIM_LEASE_SECONDS,),
        )
        row = cursor.fetchone()
        conn.commit()
        return row
    finally:
        cursor.close()


def _finish_item(conn, item_id, operation, appointment_id, time_off_id=None):
    """Basarili isi kuyruktan dusur.

    Ayni kayit icin biriken eski isler de dusurulur (coalescing), ama YALNIZCA
    isledigimiz isten eski olanlar. Google cagrisi surerken kayit tekrar
    degisip yeni is eklenmis olabilir; onu silersek takvimde bayat veri kalir.
    """
    cursor = conn.cursor()
    try:
        if operation == 'upsert' and appointment_id:
            cursor.execute(
                """
                DELETE FROM google_calendar_queue
                 WHERE operation = 'upsert'
                   AND appointment_id = %s
                   AND dead_at IS NULL
                   AND id <= %s
                """,
                (appointment_id, item_id),
            )
        elif operation == 'upsert' and time_off_id:
            cursor.execute(
                """
                DELETE FROM google_calendar_queue
                 WHERE operation = 'upsert'
                   AND time_off_id = %s
                   AND dead_at IS NULL
                   AND id <= %s
                """,
                (time_off_id, item_id),
            )
        else:
            cursor.execute('DELETE FROM google_calendar_queue WHERE id = %s', (item_id,))
        conn.commit()
    finally:
        cursor.close()


def _reschedule_item(conn, item_id, attempts, error_text, soon=False):
    """Basarisiz isi yeniden planla. Deneme hakki bittiyse birak. Donus: dead mi?"""
    cursor = conn.cursor()
    try:
        if soon:
            # Gecici cakisma (baska senkron devam ediyor) — deneme hakki yakmaz.
            # Ayri bir sayac tutulur: kilit kalici olarak alinamazsa is sonsuza
            # kadar her 60 saniyede yeniden denenmesin.
            cursor.execute(
                """
                UPDATE google_calendar_queue
                   SET attempts = GREATEST(attempts - 1, 0),
                       busy_deferrals = busy_deferrals + 1,
                       next_attempt_at = NOW() + INTERVAL '60 seconds'
                 WHERE id = %s
                RETURNING busy_deferrals
                """,
                (item_id,),
            )
            row = cursor.fetchone()
            deferrals = int(row[0]) if row else 0
            if deferrals < GCAL_MAX_BUSY_DEFERRALS:
                conn.commit()
                return False
            cursor.execute(
                """
                UPDATE google_calendar_queue
                   SET dead_at = NOW(),
                       last_error = %s
                 WHERE id = %s
                """,
                (f'busy: kilit {deferrals} denemede alinamadi', item_id),
            )
            conn.commit()
            return True

        if attempts >= GCAL_MAX_ATTEMPTS:
            cursor.execute(
                """
                UPDATE google_calendar_queue
                   SET dead_at = NOW(), last_error = %s
                 WHERE id = %s
                """,
                ((error_text or '')[:2000], item_id),
            )
            conn.commit()
            return True

        delay = _BACKOFF_SECONDS[min(attempts, len(_BACKOFF_SECONDS)) - 1]
        cursor.execute(
            """
            UPDATE google_calendar_queue
               SET next_attempt_at = NOW() + %s * INTERVAL '1 second',
                   last_error = %s
             WHERE id = %s
            """,
            (delay, (error_text or '')[:2000], item_id),
        )
        conn.commit()
        return False
    finally:
        cursor.close()


def _reschedule_rate_limit(conn, item_id, delay_seconds):
    """Kota hatalarinda deneme hakki yakmadan bekle."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE google_calendar_queue
               SET attempts = GREATEST(attempts - 1, 0),
                   next_attempt_at = NOW() + %s * INTERVAL '1 second',
                   last_error = 'rate_limit'
             WHERE id = %s
            """,
            (int(delay_seconds), item_id),
        )
        conn.commit()
    finally:
        cursor.close()


def _notify_dead_item(item_id, operation, appointment_id, event_id, exc):
    log_error(
        logger,
        E_GCAL_003,
        'Takvim isi tum denemelerde basarisiz, birakildi',
        exc=exc,
        queue_id=item_id,
        operation=operation,
        appointment_id=appointment_id,
        google_event_id=event_id,
    )
    try:
        from error_notifier import send_error_notification

        send_error_notification(
            'GoogleCalendarSyncError',
            f'Takvim isi {GCAL_MAX_ATTEMPTS} denemede tamamlanamadi ({operation}).',
            {
                'hata_kodu': E_GCAL_003,
                'kuyruk_id': item_id,
                'islem': operation,
                'randevu_id': appointment_id,
                'google_event_id': event_id,
                'hata': str(exc)[:400],
            },
        )
    except Exception as notify_err:
        logger.warning('Takvim hata bildirimi gonderilemedi: %s', notify_err)


def drain_queue(max_items=25):
    """Bekleyen takvim islerini isle (arka plan isi + acilis sonrasi telafi)."""
    summary = {'processed': 0, 'failed': 0, 'dead': 0, 'busy': 0}
    if not is_google_calendar_enabled():
        return summary

    conn = None
    try:
        conn = _connect()
        for _ in range(max_items):
            item = _claim_next_item(conn)
            if not item:
                break
            item_id, operation, appointment_id, event_id, attempts, time_off_id = item
            try:
                if operation == 'upsert':
                    if time_off_id:
                        status, _event = _perform_time_off_sync(time_off_id)
                    else:
                        status, _event = _perform_appointment_sync(appointment_id)
                    if status == 'busy':
                        if _reschedule_item(conn, item_id, attempts, None, soon=True):
                            summary['dead'] += 1
                            _notify_dead_item(
                                item_id, operation, appointment_id, event_id,
                                RuntimeError(
                                    'Google senkron kilidi surekli mesgul '
                                    '(takilmis transaction olabilir)'
                                ),
                            )
                        else:
                            summary['busy'] += 1
                        continue
                else:
                    _perform_event_delete(event_id)
                _finish_item(conn, item_id, operation, appointment_id, time_off_id)
                summary['processed'] += 1
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    delay = _retry_after_seconds(exc) or 60
                    delay += random.randint(0, 30)
                    _reschedule_rate_limit(conn, item_id, delay)
                    summary['failed'] += 1
                    log_error(
                        logger,
                        E_GCAL_001,
                        'Takvim kotasi, tekrar denenecek',
                        exc=exc,
                        queue_id=item_id,
                        retry_in=delay,
                    )
                    continue
                error_text = f'{type(exc).__name__}: {exc}'
                if _reschedule_item(conn, item_id, attempts, error_text):
                    summary['dead'] += 1
                    _notify_dead_item(item_id, operation, appointment_id, event_id, exc)
                else:
                    summary['failed'] += 1
                    log_error(
                        logger,
                        E_GCAL_001,
                        'Takvim isi basarisiz, tekrar denenecek',
                        exc=exc,
                        queue_id=item_id,
                        operation=operation,
                        appointment_id=appointment_id,
                        attempts=attempts,
                    )
    except Exception as e:
        log_error(logger, E_GCAL_002, 'Takvim kuyrugu islenemedi', exc=e)
    finally:
        _disconnect(conn)

    if summary['processed'] or summary['failed'] or summary['dead']:
        logger.info(
            'Takvim kuyrugu: islenen=%s basarisiz=%s birakilan=%s bekleyen_cakisma=%s',
            summary['processed'],
            summary['failed'],
            summary['dead'],
            summary['busy'],
        )
    return summary


_drain_guard = threading.Lock()
_drain_in_flight = False


def kick_queue_worker():
    """Kuyrugu arka planda bosalt; HTTP istegini bloklamaz.

    Process basina tek drain calisir. Kacan isleri zamanlanmis is toplar, bu
    yuzden basarisizlik sessizce veri kaybina donusmez.
    """
    global _drain_in_flight
    if not is_google_calendar_enabled():
        return False
    with _drain_guard:
        if _drain_in_flight:
            return False
        _drain_in_flight = True

    def _run():
        global _drain_in_flight
        try:
            drain_queue()
        except Exception as e:
            logger.warning('Takvim kuyrugu arka planda bosaltilamadi: %s', e)
        finally:
            with _drain_guard:
                _drain_in_flight = False

    threading.Thread(target=_run, name='gcal-queue-drain', daemon=True).start()
    return True


def queue_stats():
    """Health/monitoring icin kuyruk ozeti."""
    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE dead_at IS NULL),
                COUNT(*) FILTER (WHERE dead_at IS NOT NULL),
                MIN(created_at) FILTER (WHERE dead_at IS NULL)
            FROM google_calendar_queue
            """
        )
        pending, dead, oldest = cursor.fetchone()
        cursor.close()
        conn.commit()
        return {
            'pending': int(pending or 0),
            'dead': int(dead or 0),
            'oldest_pending': oldest.isoformat() if oldest else None,
        }
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning('Takvim kuyruk durumu alinamadi: %s', e)
        return {'pending': None, 'dead': None, 'oldest_pending': None}
    finally:
        _disconnect(conn)


# Scheduler 2 dakikada bir yoklar; birkaç kaçan turdan sonra gerçekten durmuş say.
_INBOUND_STALE_SECONDS = 8 * 60


def _aware_utc(value):
    if value is None:
        return None
    if getattr(value, 'tzinfo', None) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def inbound_sync_health(calendar_id=None):
    """Admin oturumuna bağlı olmayan arka plan senkron sağlığı."""
    cfg = get_google_calendar_config()
    calendar_id = (calendar_id or cfg.get('calendar_id') or '').strip()
    empty = {
        'last_events_at': None,
        'last_busy_at': None,
        'last_sync_at': None,
        'stale': None,
        'age_seconds': None,
    }
    if not calendar_id:
        return empty
    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT last_events_at, last_busy_at, updated_at
              FROM google_calendar_sync_state
             WHERE calendar_id = %s
            """,
            (calendar_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.commit()
        if not row:
            return empty
        last_events, last_busy, updated = row
        stamps = [_aware_utc(x) for x in (last_events, last_busy, updated) if x is not None]
        last_sync = max(stamps) if stamps else None
        age_seconds = None
        stale = None
        if last_sync is not None:
            age_seconds = max(0, int((datetime.now(timezone.utc) - last_sync).total_seconds()))
            stale = age_seconds > _INBOUND_STALE_SECONDS
        return {
            'last_events_at': last_events.isoformat() if last_events else None,
            'last_busy_at': last_busy.isoformat() if last_busy else None,
            'last_sync_at': last_sync.isoformat() if last_sync else None,
            'stale': stale,
            'age_seconds': age_seconds,
        }
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning('Takvim senkron sagligi alinamadi: %s', e)
        return empty
    finally:
        _disconnect(conn)


# =============================================
# FAZ 2a / 2b — yerel meşguliyet + inbound (yankı filtresi)
# =============================================

_slot_validator = None
_cancel_notifier = None


def set_slot_validator(fn):
    """app.py compute_available_start_slots sarmalayicisi (dongusel import yok)."""
    global _slot_validator
    _slot_validator = fn


def set_cancel_notifier(fn):
    """Google'dan silinen randevu icin musteri bildirimi (dongusel import yok).

    fn(appointment_ids) transaction COMMIT edildikten sonra, arka plan
    thread'inden cagrilir. Bildirim hatasi inbound senkronu asla dusurmez.
    """
    global _cancel_notifier
    _cancel_notifier = fn


def _cancel_notify_grace_seconds():
    """Takvimden yanlislikla silinen bir etkinligin musteriye 'iptal edildi'
    mesaji gitmeden once duzeltilebilecegi bekleme suresi.

    Sanatci/personel takvimde yanlis event'i silerse, bu sure icinde admin
    panelden randevuyu tekrar 'confirmed' yaparsa musteri hicbir zaman yanlis
    iptal mesaji almaz (bkz. _gcal_notify_cancelled_from_google: gonderim
    aninda durum tekrar kontrol edilir).
    """
    try:
        return max(0, int(os.getenv('GCAL_CANCEL_NOTIFY_GRACE_SECONDS', '600')))
    except (TypeError, ValueError):
        return 600


def _dispatch_cancel_notifications(appointment_ids):
    """Iptal bildirimlerini commit sonrasi arka planda, bir bekleme suresinin
    ardindan gonder (bkz. _cancel_notify_grace_seconds).

    Scheduler turunu WhatsApp cagrilariyla (mesaj basina 25 sn'ye kadar)
    bloklamamak icin ayri thread kullanilir.
    """
    ids = [int(i) for i in (appointment_ids or [])]
    notifier = _cancel_notifier
    if not ids or notifier is None:
        return

    grace = _cancel_notify_grace_seconds()

    def _run():
        if grace:
            time.sleep(grace)
        try:
            notifier(ids)
        except Exception as exc:
            logger.warning(
                'Google iptal bildirimi gonderilemedi | ids=%s hata=%s',
                ids, str(exc).strip()[:200],
            )

    threading.Thread(target=_run, name='gcal-cancel-notify', daemon=True).start()


def _parse_event_datetimes(event):
    """Etkinlik baslangic/bitis (stüdyo TZ). all_day ise ucuncu deger True."""
    start = event.get('start') or {}
    end = event.get('end') or {}
    tz = _studio_tz()
    tz_name = get_google_calendar_config().get('timezone') or 'Europe/Istanbul'

    def _aware(dt_value, fallback_tz_name):
        if dt_value.tzinfo is None:
            try:
                from zoneinfo import ZoneInfo
                dt_value = dt_value.replace(tzinfo=ZoneInfo(fallback_tz_name))
            except Exception:
                pass
        if tz is not None and dt_value.tzinfo is not None:
            return dt_value.astimezone(tz)
        return dt_value

    if start.get('date') and not start.get('dateTime'):
        d0 = datetime.strptime(str(start['date'])[:10], '%Y-%m-%d').date()
        if end.get('date'):
            d1 = datetime.strptime(str(end['date'])[:10], '%Y-%m-%d').date()
        else:
            d1 = d0 + timedelta(days=1)
        start_dt = datetime.combine(d0, dt_time(0, 0))
        end_dt = datetime.combine(d1, dt_time(0, 0))
        start_dt = _aware(start_dt, tz_name)
        end_dt = _aware(end_dt, tz_name)
        return start_dt, end_dt, True

    def _parse_block(block):
        raw = (block.get('dateTime') or '').strip()
        if not raw:
            return None
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return _aware(parsed, block.get('timeZone') or tz_name)

    start_dt = _parse_block(start)
    end_dt = _parse_block(end)
    if not start_dt or not end_dt:
        return None, None, False
    return start_dt, end_dt, False


# app.py'deki lock_staff_day ile AYNI namespace/key formatı — aynı sanatçı/gün
# için hem müşteri/admin yazım yolu hem Google inbound import aynı advisory
# lock üzerinde sıraya girer, aksi halde ikisi arasında double-booking olabilir.
_STAFF_DAY_LOCK_NAMESPACE = 0x524F4F46  # 'ROOF'


def _lock_staff_day(cursor, staff_id, formatted_date):
    cursor.execute(
        'SELECT pg_advisory_xact_lock(%s, hashtext(%s))',
        (_STAFF_DAY_LOCK_NAMESPACE, f"{int(staff_id or 0)}:{formatted_date}"),
    )


def _round_duration_minutes(start_dt, end_dt):
    """Google etkinlik suresini studio izgarasina (60 dk) YUKARI yuvarla.

    30 dk'ya yuvarlamak _studio_slot_grid_ok ile celisiyordu: 90 dakikalik elle
    olusturulan etkinlik hicbir zaman iceri alinamiyordu. Yukari yuvarlama en
    fazla bir saat fazla bloklar; asagi yuvarlamak randevunun uzerine slot
    acardi.
    """
    seconds = max(0, int((end_dt - start_dt).total_seconds()))
    minutes = max(SLOT_GRID_MINUTES, int(round(seconds / 60.0)))
    if minutes % SLOT_GRID_MINUTES:
        minutes = ((minutes // SLOT_GRID_MINUTES) + 1) * SLOT_GRID_MINUTES
    return minutes


def _exact_duration_minutes(start_dt, end_dt):
    """Etkinligin yuvarlanmamis suresi (yanki tespitinde kullanilir)."""
    if not start_dt or not end_dt:
        return 0
    return max(0, int(round((end_dt - start_dt).total_seconds() / 60.0)))


def _studio_slot_grid_ok(start_dt, duration_minutes):
    """Stüdyo slotu: saat başı başlangıç, süre 60/120/180…"""
    if not start_dt:
        return False
    if int(getattr(start_dt, 'minute', 0) or 0) != 0:
        return False
    if int(getattr(start_dt, 'second', 0) or 0) != 0:
        return False
    dur = int(duration_minutes or 0)
    return dur >= SLOT_GRID_MINUTES and dur % SLOT_GRID_MINUTES == 0


def _inbound_slot_allowed(
    cursor, staff_id, start_dt, duration_minutes,
    exclude_appointment_id=None, body_area=None,
):
    if not staff_id or not _studio_slot_grid_ok(start_dt, duration_minutes):
        return False
    if _slot_validator is None:
        return True
    try:
        return bool(_slot_validator(
            cursor,
            staff_id,
            start_dt.date().isoformat(),
            start_dt.strftime('%H:%M'),
            duration_minutes,
            exclude_appointment_id,
            body_area,
        ))
    except Exception as exc:
        logger.warning('Google slot dogrulamasi hata: %s', str(exc)[:160])
        return False


def load_external_busy_minutes(cursor, formatted_date):
    """Yerel gun icin stüdyo geneli meşgul dakikalar (Google HTTP yok)."""
    tz = _studio_tz()
    try:
        day = datetime.strptime(formatted_date, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return []
    if tz is not None:
        day_start = datetime.combine(day, dt_time(0, 0), tzinfo=tz)
    else:
        day_start = datetime.combine(day, dt_time(0, 0))
    day_end = day_start + timedelta(days=1)
    try:
        cursor.execute('SAVEPOINT gcal_busy_read')
        cursor.execute(
            """
            SELECT start_at, end_at
              FROM google_external_busy
             WHERE start_at < %s AND end_at > %s
            """,
            (day_end, day_start),
        )
        rows = cursor.fetchall()
        cursor.execute('RELEASE SAVEPOINT gcal_busy_read')
    except Exception:
        try:
            cursor.execute('ROLLBACK TO SAVEPOINT gcal_busy_read')
        except Exception:
            pass
        return []

    intervals = []
    for start_at, end_at in rows:
        if start_at is None or end_at is None:
            continue
        if tz is not None:
            if getattr(start_at, 'tzinfo', None):
                start_at = start_at.astimezone(tz)
            else:
                start_at = start_at.replace(tzinfo=tz)
            if getattr(end_at, 'tzinfo', None):
                end_at = end_at.astimezone(tz)
            else:
                end_at = end_at.replace(tzinfo=tz)
        clip_s = max(start_at, day_start)
        clip_e = min(end_at, day_end)
        if clip_e <= clip_s:
            continue
        start_m = clip_s.hour * 60 + clip_s.minute
        if clip_e.date() > day or (clip_e.hour == 0 and clip_e.minute == 0 and clip_e != clip_s):
            end_m = 24 * 60
        else:
            end_m = clip_e.hour * 60 + clip_e.minute
        if end_m > start_m:
            intervals.append((start_m, end_m))
    return intervals


def _list_events_window(service, calendar_id, time_min, time_max):
    events = []
    page_token = None
    while True:
        token = page_token

        def _make_request(page=token):
            return _get_calendar_service().events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                showDeleted=False,
                maxResults=250,
                pageToken=page,
                fields=(
                    'items(id,status,transparency,start,end,summary,etag,'
                    'extendedProperties,description,recurringEventId),'
                    'nextPageToken'
                ),
            )

        resp = _google_execute(_make_request)
        events.extend(resp.get('items') or [])
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return events


def _apply_inbound_busy_side_effect(cursor, calendar_id, event, action):
    """Incremental poll: eslesmeyen etkinlik slotlari 15 dk beklemeden kilitlesin.

    Iceri alinan / bizim olan / silinen etkinlik busy tablosundan dusulur.
    """
    event_id = (event.get('id') or '').strip()
    if not event_id:
        return
    drop = action in ('imported', 'moved', 'echo', 'revert', 'cancel')
    if (
        drop
        or (event.get('status') or '') == 'cancelled'
        or (event.get('transparency') or '') == 'transparent'
        or _is_our_event(event)
    ):
        cursor.execute(
            'DELETE FROM google_external_busy WHERE google_event_id = %s',
            (event_id,),
        )
        return
    start_dt, end_dt, all_day = _parse_event_datetimes(event)
    if all_day or not start_dt or not end_dt or end_dt <= start_dt:
        return
    cursor.execute(
        'DELETE FROM google_external_busy WHERE google_event_id = %s',
        (event_id,),
    )
    cursor.execute(
        """
        INSERT INTO google_external_busy
            (calendar_id, start_at, end_at, google_event_id, synced_at)
        VALUES (%s, %s, %s, %s, NOW())
        """,
        (calendar_id, start_dt, end_dt, event_id),
    )


def refresh_external_busy(force=False):
    """Elle/yabancı etkinlikleri yerel tabloya yazar. Booking yolu Google çağırmaz."""
    if not is_google_calendar_enabled():
        return {'ok': False, 'reason': 'disabled'}
    calendar_id = get_google_calendar_config()['calendar_id']
    tz = _studio_tz()
    # Naive utcnow().isoformat() offset'siz string uretir; Google RFC3339
    # bekledigi icin 400 doner.
    now = datetime.now(tz) if tz else datetime.now(timezone.utc)

    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        if not force:
            cursor.execute(
                """
                SELECT last_busy_at FROM google_calendar_sync_state
                 WHERE calendar_id = %s
                """,
                (calendar_id,),
            )
            row = cursor.fetchone()
            last_busy = _aware_utc(row[0]) if row and row[0] else None
            if last_busy is not None:
                age = int((datetime.now(timezone.utc) - last_busy).total_seconds())
                if age < _BUSY_REFRESH_MIN_SECONDS:
                    cursor.close()
                    conn.commit()
                    return {
                        'ok': True,
                        'skipped': True,
                        'age_seconds': max(0, age),
                        'count': None,
                    }
        cursor.close()
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning('Dis mesguliyet yenileme kontrolu atlandi: %s', str(e)[:160])
    finally:
        _disconnect(conn)
        conn = None

    time_min = (now - timedelta(days=_BUSY_LOOKBACK_DAYS)).isoformat()
    time_max = (now + timedelta(days=_BUSY_LOOKAHEAD_DAYS)).isoformat()
    try:
        events = _list_events_window(_get_calendar_service(), calendar_id, time_min, time_max)
        conn = _connect()
        cursor = conn.cursor()
        imported = 0
        for event in events:
            try:
                cursor.execute('SAVEPOINT gcal_busy_import')
                result = _import_manual_google_event(cursor, event, calendar_id)
                cursor.execute('RELEASE SAVEPOINT gcal_busy_import')
                if result == 'imported':
                    imported += 1
            except Exception as exc:
                try:
                    cursor.execute('ROLLBACK TO SAVEPOINT gcal_busy_import')
                except Exception:
                    pass
                logger.warning(
                    'Google busy import atlandi | event=%s hata=%s',
                    (event.get('id') or '')[:80],
                    str(exc).strip()[:200],
                )

        # Etkinlik basina iki sorgu yerine iki toplu sorgu: yuzlerce etkinlikte
        # N+1 gidip geliyordu.
        cursor.execute(
            """
            SELECT google_event_id FROM appointments
             WHERE google_event_id IS NOT NULL
               AND status IS DISTINCT FROM 'cancelled'
            """
        )
        linked_ids = {r[0] for r in cursor.fetchall() or [] if r[0]}
        cursor.execute(
            'SELECT google_event_id FROM time_off WHERE google_event_id IS NOT NULL'
        )
        linked_ids.update(r[0] for r in cursor.fetchall() or [] if r[0])

        rows = []
        for event in events:
            if (event.get('status') or '') == 'cancelled':
                continue
            if (event.get('transparency') or '') == 'transparent':
                continue
            if _is_our_event(event):
                continue
            event_id = (event.get('id') or '').strip()
            if event_id and event_id in linked_ids:
                continue
            start_dt, end_dt, all_day = _parse_event_datetimes(event)
            if not start_dt or not end_dt or end_dt <= start_dt:
                continue
            # Tüm-gün sistemden kapatılır; Google all-day randevu/meşguliyet değil.
            if all_day:
                continue
            # Saatli etkinlik randevu olmadıysa (eşleşmedi / çakıştı / grid dışı)
            # o aralık stüdyo geneli kilitlenir — sitede boş görünmesin.
            rows.append((calendar_id, start_dt, end_dt, event.get('id')))

        # Eskiden her turda (2 dk) tablo silinip satir satir yeniden yaziliyordu:
        # gunde yuz binlerce gereksiz yazma ve olu tuple. Artik once karsilastirilir,
        # gercekten degistiyse tek seferde toplu yazilir.
        cursor.execute(
            """
            SELECT start_at, end_at, google_event_id
              FROM google_external_busy
             WHERE calendar_id = %s
            """,
            (calendar_id,),
        )
        existing = {
            (_aware_utc(s), _aware_utc(e), gid)
            for s, e, gid in (cursor.fetchall() or [])
        }
        desired = {
            (_aware_utc(start_at), _aware_utc(end_at), gid)
            for _cal, start_at, end_at, gid in rows
        }
        if existing != desired:
            cursor.execute(
                'DELETE FROM google_external_busy WHERE calendar_id = %s',
                (calendar_id,),
            )
            chunk = 500
            for offset in range(0, len(rows), chunk):
                batch = rows[offset:offset + chunk]
                placeholders = ', '.join(['(%s, %s, %s, %s, NOW())'] * len(batch))
                params = []
                for row in batch:
                    params.extend(row)
                cursor.execute(
                    """
                    INSERT INTO google_external_busy
                        (calendar_id, start_at, end_at, google_event_id, synced_at)
                    VALUES
                    """
                    + placeholders,
                    params,
                )
        cursor.execute(
            """
            INSERT INTO google_calendar_sync_state (calendar_id, last_busy_at, updated_at)
            VALUES (%s, NOW(), NOW())
            ON CONFLICT (calendar_id) DO UPDATE
               SET last_busy_at = NOW(), updated_at = NOW()
            """,
            (calendar_id,),
        )
        conn.commit()
        cursor.close()
        logger.info(
            'Google dis mesguliyet yenilendi: %s aralik, manuel randevu: %s',
            len(rows), imported,
        )
        return {'ok': True, 'count': len(rows)}
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        log_error(logger, E_GCAL_001, 'Dis mesguliyet tablosu yenilenemedi', exc=e)
        return {'ok': False, 'reason': str(e)[:200]}
    finally:
        _disconnect(conn)


def reset_inbound_state(old_calendar_id=None):
    """Takvim kimliği değişince syncToken ve eski busy satırlarını düşür."""
    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        if old_calendar_id:
            cursor.execute(
                'DELETE FROM google_external_busy WHERE calendar_id = %s',
                (old_calendar_id,),
            )
            cursor.execute(
                'DELETE FROM google_calendar_sync_state WHERE calendar_id = %s',
                (old_calendar_id,),
            )
        conn.commit()
        cursor.close()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning('Takvim inbound durumu sifirlanamadi: %s', e)
    finally:
        _disconnect(conn)


def _times_match_appointment(
    start_dt, duration_minutes, apt_date, apt_time, apt_duration, exact_minutes=None,
):
    """Google etkinligi yereldeki randevuyla ayni mi (yani mi, tasima mi)."""
    if not start_dt:
        return False
    if start_dt.date() != _as_date(apt_date):
        return False
    if start_dt.strftime('%H:%M') != _time_to_str(apt_time):
        return False
    stored = int(apt_duration or 0)
    if int(duration_minutes or 0) == stored:
        return True
    # Izgaraya uymayan eski kayitlar (ornegin 90 dk): Google'daki gercek sure
    # birebir ayniysa bu bir yankidir, tasima degil. Yuvarlanmis degere bakip
    # tasima saymak randevu suresini sessizce buyuturdu.
    return exact_minutes is not None and int(exact_minutes) == stored


def _load_appointment_for_inbound(cursor, appointment_id):
    cursor.execute(
        """
        SELECT
            a.id, a.staff_id, a.status, a.appointment_date, a.appointment_time,
            a.duration_minutes, a.google_event_id, a.google_etag, a.source,
            COALESCE(tr.body_area, '')
        FROM appointments a
        LEFT JOIN tattoo_requests tr ON a.tattoo_request_id = tr.id
        WHERE a.id = %s
        """,
        (appointment_id,),
    )
    return cursor.fetchone()


def _soft_cancel_from_google(cursor, appointment_id):
    cursor.execute(
        """
        UPDATE appointments
           SET status = 'cancelled', cancelled_at = COALESCE(cancelled_at, NOW())
         WHERE id = %s
           AND status NOT IN ('cancelled', 'completed')
        RETURNING id
        """,
        (appointment_id,),
    )
    return cursor.fetchone() is not None


def _apply_inbound_move(cursor, appointment_id, local_date, local_time, duration_minutes, etag):
    cursor.execute(
        """
        UPDATE appointments
           SET appointment_date = %s,
               appointment_time = %s,
               duration_minutes = %s,
               google_etag = %s,
               google_updated_at = NOW()
         WHERE id = %s
           AND status NOT IN ('cancelled', 'completed')
        RETURNING id
        """,
        (local_date, local_time, duration_minutes, etag, appointment_id),
    )
    return cursor.fetchone() is not None


def _refresh_google_source_identity(
    cursor, appointment_id, event, calendar_id,
    current_staff_id, source, start_dt, duration_minutes,
):
    """source=google: başlık değişince müşteri/sanatçı güncelle. Adı ezme."""
    if (source or '').lower() != 'google' or not start_dt:
        return
    artists = _load_bookable_artists(cursor)
    new_staff, _staff_name, cust_name, cust_surname, phone = _parse_manual_event_title(
        event.get('summary') or '', artists
    )
    if phone or not _is_placeholder_person(cust_name, cust_surname):
        customer_id = _resolve_or_create_gcal_customer(
            cursor, cust_name, cust_surname, phone, (event.get('id') or '').strip()
        )
        cursor.execute(
            """
            UPDATE appointments
               SET customer_id = %s
             WHERE id = %s
               AND customer_id IS DISTINCT FROM %s
            """,
            (customer_id, appointment_id, customer_id),
        )
    if new_staff and int(new_staff) != int(current_staff_id or 0):
        if _inbound_slot_allowed(
            cursor, new_staff, start_dt, duration_minutes,
            exclude_appointment_id=appointment_id,
        ):
            cursor.execute(
                """
                UPDATE appointments
                   SET staff_id = %s
                 WHERE id = %s
                   AND status NOT IN ('cancelled', 'completed')
                """,
                (new_staff, appointment_id),
            )
            _stamp_origin_on_event(
                calendar_id, (event.get('id') or '').strip(), appointment_id,
                (start_dt.date(), start_dt.strftime('%H:%M') + ':00', duration_minutes, new_staff),
            )
        else:
            logger.warning(
                'Google baslikta sanatci degisti ama yeni slot uygun degil | apt=%s staff=%s->%s',
                appointment_id, current_staff_id, new_staff,
            )


_ARTISTS_CACHE_TTL_SECONDS = 30
_artists_cache_lock = threading.Lock()
_artists_cache = {'rows': None, 'at': 0.0}


def reset_artists_cache():
    """Sanatci eklenince/adi degisince cache'i dusur."""
    with _artists_cache_lock:
        _artists_cache['rows'] = None
        _artists_cache['at'] = 0.0


def _load_bookable_artists(cursor):
    """Kitaplanabilir sanatcilar (kisa omurlu cache).

    Bir inbound turunda yuzlerce etkinlik islenebiliyor ve her biri bu listeyi
    yeniden sorguluyordu (N+1). Sanatci listesi nadiren degisir.
    """
    now = time.time()
    with _artists_cache_lock:
        cached = _artists_cache['rows']
        if cached is not None and (now - _artists_cache['at']) < _ARTISTS_CACHE_TTL_SECONDS:
            return cached
    cursor.execute(
        """
        SELECT id, name, COALESCE(calendar_aliases, '{}'::text[])
          FROM artists
         WHERE role IS DISTINCT FROM 'tech_support'
         ORDER BY display_order ASC, id ASC
        """
    )
    rows = cursor.fetchall() or []
    with _artists_cache_lock:
        _artists_cache['rows'] = rows
        _artists_cache['at'] = time.time()
    return rows


def _match_customer_by_name(cursor, name, surname):
    cursor.execute(
        """
        SELECT id, phone, name, surname
          FROM customers
         WHERE COALESCE(TRIM(name), '') <> ''
        """
    )
    customer_id = _match_customer_from_rows(name, surname, cursor.fetchall() or [])
    if customer_id:
        logger.info(
            'Google etkinligi kayitli musteriyle eslesti | customer_id=%s name=%s %s',
            customer_id, name, surname,
        )
    return customer_id


def _resolve_or_create_gcal_customer(cursor, name, surname, phone, event_id):
    """Telefon varsa mevcut müşteriyi bağla; dolu adı/soyadı ezme."""
    name = (name or '').strip()
    surname = (surname or '').strip()
    if phone:
        cursor.execute('SELECT id FROM customers WHERE phone = %s', (phone,))
        found = cursor.fetchone()
        if found:
            return found[0]
        cursor.execute(
            """
            INSERT INTO customers (phone, name, surname)
            VALUES (%s, %s, %s)
            ON CONFLICT (phone) DO UPDATE
               SET phone = customers.phone
            RETURNING id
            """,
            (phone, name, surname),
        )
        return cursor.fetchone()[0]

    if not _is_placeholder_person(name, surname):
        matched_id = _match_customer_by_name(cursor, name, surname)
        if matched_id:
            return matched_id

    resolved_phone = _synthetic_gcal_phone(event_id)
    cursor.execute(
        """
        INSERT INTO customers (phone, name, surname)
        VALUES (%s, %s, %s)
        ON CONFLICT (phone) DO UPDATE
           SET phone = customers.phone
        RETURNING id
        """,
        (resolved_phone, name, surname),
    )
    return cursor.fetchone()[0]


def _stamp_origin_on_event(calendar_id, event_id, appointment_id, row_for_hash):
    if not event_id or not appointment_id:
        return
    try:
        content_hash = _content_hash(
            row_for_hash[0], row_for_hash[1], row_for_hash[2], 'confirmed', row_for_hash[3],
        )
        staff_id = row_for_hash[3] if len(row_for_hash) > 3 else None
        body = {'extendedProperties': _extended_properties(appointment_id, content_hash)}
        if staff_id:
            body['colorId'] = _color_id_for_staff(staff_id)
        _google_execute(
            lambda: _get_calendar_service().events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
            )
        )
    except Exception as exc:
        logger.warning(
            'Google etkinligine origin yazilamadi | event=%s apt=%s hata=%s',
            event_id, appointment_id, str(exc)[:160],
        )


def refresh_google_event_colors(limit=400):
    """Mevcut etkinliklerin colorId'sini sanatçıya göre günceller; başlığı değiştirmez."""
    if not is_google_calendar_enabled():
        return {'ok': False, 'reason': 'disabled'}
    calendar_id = get_google_calendar_config()['calendar_id']
    conn = None
    updated = 0
    failed = 0
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.id, a.staff_id, a.google_event_id, ar.name
              FROM appointments a
              JOIN artists ar ON ar.id = a.staff_id
             WHERE a.google_event_id IS NOT NULL
               AND a.status IS DISTINCT FROM 'cancelled'
             ORDER BY a.appointment_date DESC, a.id DESC
             LIMIT %s
            """,
            (int(limit),),
        )
        rows = cursor.fetchall() or []
        cursor.execute(
            """
            SELECT id, google_event_id
              FROM time_off
             WHERE google_event_id IS NOT NULL
             ORDER BY off_date DESC, id DESC
             LIMIT %s
            """,
            (int(limit),),
        )
        off_rows = cursor.fetchall() or []
        cursor.close()
        for apt_id, staff_id, event_id, staff_name in rows:
            try:
                _google_execute(
                    lambda eid=event_id, sid=staff_id, sname=staff_name: (
                        _get_calendar_service().events().patch(
                            calendarId=calendar_id,
                            eventId=eid,
                            body={'colorId': _color_id_for_staff(sid, sname)},
                        )
                    )
                )
                updated += 1
            except Exception as exc:
                failed += 1
                logger.warning(
                    'Google renk guncellenemedi | apt=%s event=%s hata=%s',
                    apt_id, event_id, str(exc)[:160],
                )
        off_updated = 0
        for off_id, event_id in off_rows:
            try:
                _google_execute(
                    lambda eid=event_id: (
                        _get_calendar_service().events().patch(
                            calendarId=calendar_id,
                            eventId=eid,
                            body={'colorId': GCAL_COLOR_GRAPHITE},
                        )
                    )
                )
                updated += 1
                off_updated += 1
            except Exception as exc:
                failed += 1
                logger.warning(
                    'Google Off Day rengi guncellenemedi | time_off=%s event=%s hata=%s',
                    off_id, event_id, str(exc)[:160],
                )
        logger.info(
            'Google etkinlik renkleri guncellendi | ok=%s fail=%s off_day=%s',
            updated, failed, off_updated,
        )
        return {
            'ok': True,
            'updated': updated,
            'failed': failed,
            'total': len(rows) + len(off_rows),
            'off_day_updated': off_updated,
        }
    except Exception as e:
        log_error(logger, E_GCAL_001, 'Google etkinlik renkleri guncellenemedi', exc=e)
        return {'ok': False, 'updated': updated, 'failed': failed, 'error': str(e)[:200]}
    finally:
        # conn.close() havuzdan alinan baglantiyi havuza geri vermez; slot
        # kalici olarak sizardi. _disconnect dogru saglayiciyi kullanir.
        _disconnect(conn)


def _import_manual_google_event(cursor, event, calendar_id):
    """Elle Google etkinliği: Off Day veya (telefon varsa) source=google randevu."""
    if (event.get('status') or '') == 'cancelled':
        return 'skip'
    if (event.get('transparency') or '') == 'transparent':
        return 'skip'
    if event.get('recurringEventId'):
        return 'skip'
    event_id = (event.get('id') or '').strip()
    if not event_id:
        return 'skip'

    artists = _load_bookable_artists(cursor)
    if not artists:
        logger.warning('Google manuel import: kitaplanabilir sanatci yok')
        return 'skip'

    summary = event.get('summary') or ''
    staff_id, staff_name, has_keyword, phone, reason = _parse_off_day_from_title(
        summary, artists
    )
    start_dt, end_dt, all_day = _parse_event_datetimes(event)

    # "sanatci eslesti + telefon yok" tek basina Off Day sayilmaz: elle
    # yazilmis, telefonu unutulmus gercek bir randevu olabilir (musteri adi
    # basliktan okunabiliyorsa). _resolve_or_create_gcal_customer boyle bir
    # durumda isme gore eslestirme/synthetic telefon ile randevuyu yine de
    # olusturabiliyor, o yuzden burada erken davranip yutmayalim. All-day
    # etkinliklerde zamanli randevu kurulamayacagindan (saat araligi yok)
    # bu ayrim uygulanmaz, dogrudan Off Day kabul edilir.
    parsed_staff, _staff_name, cust_name, cust_surname, parsed_phone = _parse_manual_event_title(
        summary, artists
    )
    staff_id = staff_id or parsed_staff
    phone = phone or parsed_phone
    has_real_customer_name = not _is_placeholder_person(cust_name, cust_surname)

    is_off_day = bool(
        has_keyword
        or (staff_id and not phone and (all_day or not has_real_customer_name))
    )
    if is_off_day:
        if not staff_id:
            _log_unmatched_artist(event_id, summary)
            return 'unmatched'
        return _import_off_day_event(
            cursor, event, calendar_id, staff_id, staff_name or _staff_name, reason,
        )

    if all_day or not start_dt or not end_dt:
        return 'skip'

    duration_minutes = _round_duration_minutes(start_dt, end_dt)
    local_date = start_dt.date()
    local_time = start_dt.strftime('%H:%M') + ':00'

    if not staff_id:
        _log_unmatched_artist(event_id, summary)
        return 'unmatched'

    cursor.execute(
        'SELECT id FROM appointments WHERE google_event_id = %s',
        (event_id,),
    )
    if cursor.fetchone():
        return 'skip'

    # Müşteri/admin randevu yazım yoluyla aynı sanatçı/gün için yarışa
    # girmesin — aksi halde çakışma kontrolü ile INSERT arasına başka bir
    # randevu girip double-booking oluşabilir.
    _lock_staff_day(cursor, staff_id, local_date.isoformat())

    cursor.execute(
        'DELETE FROM google_external_busy WHERE google_event_id = %s',
        (event_id,),
    )
    if not _inbound_slot_allowed(cursor, staff_id, start_dt, duration_minutes):
        logger.warning(
            'Google manuel randevu slot/cakisma nedeniyle yazilmadi | event=%s staff=%s %s %s %s dk',
            event_id, staff_id, local_date, local_time, duration_minutes,
        )
        return 'conflict'

    try:
        cursor.execute('SAVEPOINT gcal_import')
        customer_id = _resolve_or_create_gcal_customer(
            cursor, cust_name, cust_surname, phone, event_id
        )
        cursor.execute(
            """
            INSERT INTO appointments (
                customer_id, staff_id, tattoo_request_id,
                appointment_date, appointment_time, status,
                duration_minutes, price, source,
                google_event_id, google_etag, google_calendar_id, google_updated_at
            )
            VALUES (%s, %s, NULL, %s, %s, 'confirmed', %s, 0, 'google', %s, %s, %s, NOW())
            RETURNING id
            """,
            (
                customer_id, staff_id, local_date, local_time,
                duration_minutes, event_id, event.get('etag'), calendar_id,
            ),
        )
        appointment_id = cursor.fetchone()[0]
        cursor.execute('RELEASE SAVEPOINT gcal_import')
    except Exception as exc:
        try:
            cursor.execute('ROLLBACK TO SAVEPOINT gcal_import')
        except Exception:
            pass
        logger.warning(
            'Google manuel randevu yazilamadi | event=%s hata=%s',
            event_id, str(exc).strip()[:200],
        )
        return 'skip'

    _stamp_origin_on_event(
        calendar_id, event_id, appointment_id,
        (local_date, local_time, duration_minutes, staff_id),
    )
    logger.info(
        'Google manuel etkinlik randevu oldu (WhatsApp yok) apt #%s event=%s staff=%s customer=%s',
        appointment_id, event_id, staff_id, customer_id,
    )
    return 'imported'


def _off_day_day_blocks(event):
    """Bir Off Day etkinligini, her biri time_off'a bir satir olarak yazilacak
    (off_date, start_time, end_time) ucluleri listesine ayirir.

    time_off satir basina tek gun tutar (kolon: tek off_date), bu yuzden
    coklu gun suren (all-day araligi veya gece yarisini asan) bir Google
    etkinligi birden fazla satira bolunur — hepsi ayni google_event_id'yi
    paylasir (bkz. uq_time_off_google_event_id_date, (google_event_id,
    off_date) uzerinde UNIQUE). start_time/end_time None ise o gun tam
    gun kapali demektir (bkz. _count_overlapping_appointments).

    Tek gunluk etkinlikler icin tek elemanli liste doner.
    """
    start_dt, end_dt, all_day = _parse_event_datetimes(event)
    if not start_dt or not end_dt or end_dt <= start_dt:
        return []

    if all_day:
        first_day = start_dt.date()
        last_day = end_dt.date() - timedelta(days=1)  # Google end tarihi exclusive
        if last_day < first_day:
            last_day = first_day
        blocks = []
        d = first_day
        while d <= last_day:
            blocks.append((d, None, None))
            d += timedelta(days=1)
        return blocks

    first_day = start_dt.date()
    last_day = end_dt.date()

    if last_day == first_day:
        start_m = start_dt.hour * 60 + start_dt.minute
        end_m = end_dt.hour * 60 + end_dt.minute
        if end_m <= start_m:
            end_m = 24 * 60
        start_hh = f'{start_m // 60:02d}:{start_m % 60:02d}'
        end_hh = '00:00' if end_m >= 24 * 60 else f'{end_m // 60:02d}:{end_m % 60:02d}'
        return [(first_day, start_hh, end_hh)]

    # Gece yarisini asan / coklu gun suren saatli blok:
    # ilk gun baslangictan gece yarisina, ara gunler tam gun,
    # son gun gece yarisindan bitis saatine kadar.
    blocks = [(first_day, f'{start_dt.hour:02d}:{start_dt.minute:02d}', '00:00')]
    d = first_day + timedelta(days=1)
    while d < last_day:
        blocks.append((d, None, None))
        d += timedelta(days=1)
    end_hh = f'{end_dt.hour:02d}:{end_dt.minute:02d}'
    if end_hh != '00:00':
        blocks.append((last_day, '00:00', end_hh))
    return blocks


def _count_overlapping_appointments(cursor, staff_id, off_date, start_time, end_time):
    cursor.execute(
        """
        SELECT appointment_time, duration_minutes
          FROM appointments
         WHERE staff_id = %s AND appointment_date = %s AND status != 'cancelled'
        """,
        (staff_id, off_date),
    )
    rows = cursor.fetchall() or []
    if start_time is None:
        return len(rows)
    off_s, off_e = _time_off_minutes(start_time, end_time)
    count = 0
    for appt_time, dur in rows:
        apt_s = _time_str_to_minutes_local(str(appt_time)[:5])
        apt_e = apt_s + int(dur or 60)
        if apt_s < off_e and off_s < apt_e:
            count += 1
    return count


def _stamp_origin_on_off_day_event(calendar_id, event_id, time_off_id, staff_id, staff_name=None):
    if not event_id or not time_off_id:
        return
    try:
        body = {
            'extendedProperties': _off_day_extended_properties(time_off_id),
            'transparency': 'opaque',
            'colorId': GCAL_COLOR_GRAPHITE,
        }
        _google_execute(
            lambda: _get_calendar_service().events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=body,
            )
        )
    except Exception as exc:
        logger.warning(
            'Google Off Day origin yazilamadi | event=%s id=%s hata=%s',
            event_id, time_off_id, str(exc)[:160],
        )


def _import_off_day_event(cursor, event, calendar_id, staff_id, staff_name, reason):
    """Elle Google etkinliğini time_off yapar. WhatsApp yok."""
    if (event.get('status') or '') == 'cancelled':
        return 'skip'
    if (event.get('transparency') or '') == 'transparent':
        return 'skip'
    if event.get('recurringEventId'):
        return 'skip'
    event_id = (event.get('id') or '').strip()
    if not event_id or not staff_id:
        return 'skip'

    blocks = _off_day_day_blocks(event)
    if not blocks:
        return 'skip'

    cursor.execute(
        'SELECT 1 FROM time_off WHERE google_event_id = %s LIMIT 1',
        (event_id,),
    )
    if cursor.fetchone():
        return 'skip'

    cursor.execute(
        'DELETE FROM google_external_busy WHERE google_event_id = %s',
        (event_id,),
    )

    first_time_off_id = None
    inserted_days = []
    for off_date, start_time, end_time in blocks:
        overlap = _count_overlapping_appointments(cursor, staff_id, off_date, start_time, end_time)
        if overlap:
            # Sadece log dosyasina degil e-postaya da dusun ki admin fark etsin —
            # randevu otomatik iptal edilmiyor, elle kontrol gerekiyor.
            log_error(
                logger, E_GCAL_004,
                'Off Day, mevcut onayli randevuyla cakisiyor (randevu iptal edilmedi)',
                event_id=event_id, staff_id=staff_id, date=off_date, overlap_count=overlap,
            )

        try:
            cursor.execute('SAVEPOINT gcal_off_import')
            cursor.execute(
                """
                INSERT INTO time_off (
                    staff_id, off_date, start_time, end_time, reason,
                    google_event_id, google_etag, google_calendar_id, google_updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    staff_id, off_date, start_time, end_time,
                    (reason or '')[:100],
                    event_id, event.get('etag'), calendar_id,
                ),
            )
            row_id = cursor.fetchone()[0]
            cursor.execute('RELEASE SAVEPOINT gcal_off_import')
            if first_time_off_id is None:
                first_time_off_id = row_id
            inserted_days.append(off_date)
        except Exception as exc:
            try:
                cursor.execute('ROLLBACK TO SAVEPOINT gcal_off_import')
            except Exception:
                pass
            logger.warning(
                'Google Off Day gunu yazilamadi | event=%s tarih=%s hata=%s',
                event_id, off_date, str(exc).strip()[:200],
            )

    if not inserted_days:
        return 'skip'

    _stamp_origin_on_off_day_event(
        calendar_id, event_id, first_time_off_id, staff_id, staff_name,
    )
    logger.info(
        'Google etkinlik Off Day oldu (WhatsApp yok) event=%s staff=%s %d gun (%s .. %s)',
        event_id, staff_id, len(inserted_days), inserted_days[0], inserted_days[-1],
    )
    return 'imported'


def _handle_inbound_time_off(cursor, event, calendar_id, time_off_id):
    """Google'da Off Day etkinligi silindi/tasindi/yeniden boyutlandirildi.

    Bir etkinlik artik birden fazla time_off satirina karsilik gelebilir
    (coklu gun, bkz. _off_day_day_blocks) — gelen time_off_id yalnizca "bu
    bizim event'imiz" tespiti icindir; asil islem ayni google_event_id'yi
    paylasan TUM satirlar uzerinde yapilir. Guncellemede kismi diff yerine
    en guvenilir yol izlenir: mevcut gunler silinip yeni gun bloklari
    yeniden yazilir.
    """
    event_id = (event.get('id') or '').strip()
    staff_id = None

    cursor.execute('SELECT staff_id, google_event_id FROM time_off WHERE id = %s', (time_off_id,))
    row = cursor.fetchone()
    if row:
        staff_id, stored_event_id = row
        event_id = stored_event_id or event_id
    elif event_id:
        # Gelen time_off_id gecersiz/eski olabilir — onceki bir tasima
        # islemi ayni event icin satirlari silip yeniden yazmis, dolayisiyla
        # Google'a damgalanan id artik yok. event_id uzerinden gercek
        # satirlara geri don ki tasima/silme zinciri kopmasin.
        cursor.execute('SELECT staff_id FROM time_off WHERE google_event_id = %s LIMIT 1', (event_id,))
        fallback = cursor.fetchone()
        if fallback:
            staff_id = fallback[0]

    if not event_id or staff_id is None:
        return 'skip'

    if (event.get('status') or '') == 'cancelled':
        cursor.execute('DELETE FROM time_off WHERE google_event_id = %s', (event_id,))
        removed = cursor.rowcount
        logger.info('Google Off Day silme -> %d time_off satiri silindi (event=%s, WhatsApp yok)', removed, event_id)
        return 'cancel'

    cursor.execute(
        """
        SELECT off_date, start_time, end_time, google_etag, reason
          FROM time_off
         WHERE google_event_id = %s
         ORDER BY off_date
        """,
        (event_id,),
    )
    existing_rows = cursor.fetchall()
    if not existing_rows:
        return 'skip'

    blocks = _off_day_day_blocks(event)
    if not blocks:
        return 'skip'

    stored_etag = existing_rows[0][3]
    stored_reason = existing_rows[0][4]
    existing_shape = [
        (r[0], str(r[1])[:5] if r[1] is not None else None, str(r[2])[:5] if r[2] is not None else None)
        for r in existing_rows
    ]
    if existing_shape == blocks:
        if event.get('etag') and event.get('etag') != stored_etag:
            cursor.execute(
                """
                UPDATE time_off
                   SET google_etag = %s, google_updated_at = NOW(), google_calendar_id = %s
                 WHERE google_event_id = %s
                """,
                (event.get('etag'), calendar_id, event_id),
            )
        return 'echo'

    cursor.execute('DELETE FROM time_off WHERE google_event_id = %s', (event_id,))

    written_days = []
    new_first_id = None
    for off_date, start_time, end_time in blocks:
        overlap = _count_overlapping_appointments(cursor, staff_id, off_date, start_time, end_time)
        if overlap:
            log_error(
                logger, E_GCAL_004,
                'Google Off Day tasima mevcut onayli randevuyla cakisiyor (randevu iptal edilmedi)',
                event_id=event_id, staff_id=staff_id, date=off_date, overlap_count=overlap,
            )
        try:
            cursor.execute('SAVEPOINT gcal_off_move')
            cursor.execute(
                """
                INSERT INTO time_off (
                    staff_id, off_date, start_time, end_time, reason,
                    google_event_id, google_etag, google_calendar_id, google_updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (staff_id, off_date, start_time, end_time, stored_reason, event_id, event.get('etag'), calendar_id),
            )
            row_id = cursor.fetchone()[0]
            cursor.execute('RELEASE SAVEPOINT gcal_off_move')
            if new_first_id is None:
                new_first_id = row_id
            written_days.append(off_date)
        except Exception as exc:
            try:
                cursor.execute('ROLLBACK TO SAVEPOINT gcal_off_move')
            except Exception:
                pass
            logger.warning(
                'Google Off Day tasima gunu yazilamadi | event=%s tarih=%s hata=%s',
                event_id, off_date, str(exc).strip()[:200],
            )

    if not written_days:
        logger.warning('Google Off Day tasima sonrasi hicbir gun yazilamadi | event=%s', event_id)
        return 'skip'

    # Eski satirlar silinip yeni id'lerle yeniden yazildigi icin Google
    # etkinligindeki damgayi (extendedProperties.time_off_id) guncel
    # tutmazsak bir sonraki tasima/silme bu event'i taniyamaz (stale id).
    _stamp_origin_on_off_day_event(calendar_id, event_id, new_first_id, staff_id)

    logger.info(
        'Google Off Day tasima uygulandi event=%s %d gun (%s .. %s) (WhatsApp yok)',
        event_id, len(written_days), written_days[0], written_days[-1],
    )
    return 'moved'


def _handle_inbound_event(cursor, event, calendar_id, cancelled_ids=None):
    if _is_off_day_origin(event):
        time_off_id = _our_time_off_id_from_event(event)
        if not time_off_id:
            event_id = (event.get('id') or '').strip()
            if event_id:
                cursor.execute(
                    'SELECT id FROM time_off WHERE google_event_id = %s',
                    (event_id,),
                )
                found = cursor.fetchone()
                time_off_id = found[0] if found else None
        if time_off_id:
            return _handle_inbound_time_off(cursor, event, calendar_id, time_off_id)
        return _import_manual_google_event(cursor, event, calendar_id)

    appointment_id = _our_appointment_id_from_event(event)
    if not appointment_id:
        event_id = (event.get('id') or '').strip()
        if event_id:
            cursor.execute(
                'SELECT id FROM appointments WHERE google_event_id = %s',
                (event_id,),
            )
            found = cursor.fetchone()
            appointment_id = found[0] if found else None
    if not appointment_id:
        time_off_id = _our_time_off_id_from_event(event)
        if not time_off_id:
            event_id = (event.get('id') or '').strip()
            if event_id:
                cursor.execute(
                    'SELECT id FROM time_off WHERE google_event_id = %s',
                    (event_id,),
                )
                found = cursor.fetchone()
                time_off_id = found[0] if found else None
        if time_off_id:
            return _handle_inbound_time_off(cursor, event, calendar_id, time_off_id)
        return _import_manual_google_event(cursor, event, calendar_id)

    deleted = (event.get('status') or '') == 'cancelled'

    row = _load_appointment_for_inbound(cursor, appointment_id)
    if not row:
        return 'skip'

    (
        _id, staff_id, status, apt_date, apt_time, apt_duration,
        google_event_id, stored_etag, source, body_area,
    ) = row
    source = (source or 'admin').lower()

    if status == 'cancelled':
        return 'skip'

    start_dt, end_dt, all_day = _parse_event_datetimes(event)
    duration_minutes = _round_duration_minutes(start_dt, end_dt) if start_dt and end_dt else 0
    exact_minutes = _exact_duration_minutes(start_dt, end_dt)

    if status == 'completed':
        if deleted:
            enqueue_appointment_sync(cursor, appointment_id)
            return 'revert'
        if all_day or not _times_match_appointment(
            start_dt, duration_minutes, apt_date, apt_time, apt_duration, exact_minutes
        ):
            enqueue_appointment_sync(cursor, appointment_id)
            return 'revert'
        return 'skip'

    if deleted:
        if source in ('customer', 'admin', 'google'):
            if _soft_cancel_from_google(cursor, appointment_id):
                logger.info('Google silme -> soft iptal apt #%s', appointment_id)
                # Musteri iptalden habersiz stüdyoya gelmesin. Bildirim commit
                # sonrasi toplu gonderilir; burada sadece kuyruklanir.
                if cancelled_ids is not None:
                    cancelled_ids.append(appointment_id)
                return 'cancel'
        return 'skip'

    if all_day or not start_dt or not end_dt:
        enqueue_appointment_sync(cursor, appointment_id)
        return 'revert'

    local_date = start_dt.date()
    local_time = start_dt.strftime('%H:%M')

    if _times_match_appointment(
        start_dt, duration_minutes, apt_date, apt_time, apt_duration, exact_minutes
    ):
        if event.get('etag') and event.get('etag') != stored_etag:
            cursor.execute(
                'UPDATE appointments SET google_etag = %s, google_updated_at = NOW() WHERE id = %s',
                (event.get('etag'), appointment_id),
            )
        _refresh_google_source_identity(
            cursor, appointment_id, event, calendar_id,
            staff_id, source, start_dt, duration_minutes,
        )
        return 'echo'

    allowed = _inbound_slot_allowed(
        cursor, staff_id, start_dt, duration_minutes,
        exclude_appointment_id=appointment_id,
        body_area=body_area or None,
    )
    if not allowed:
        enqueue_appointment_sync(cursor, appointment_id)
        return 'revert'

    if _apply_inbound_move(
        cursor, appointment_id, local_date, local_time, duration_minutes, event.get('etag')
    ):
        logger.info(
            'Google tasima uygulandi (WhatsApp yok) apt #%s %s %s',
            appointment_id, local_date, local_time,
        )
        _refresh_google_source_identity(
            cursor, appointment_id, event, calendar_id,
            staff_id, source, start_dt, duration_minutes,
        )
        return 'moved'
    enqueue_appointment_sync(cursor, appointment_id)
    return 'revert'


def poll_inbound_changes():
    """syncToken ile değişen etkinlikleri işler: origin=roof taşı/sil/geri al;
    origin=roof_off Off Day taşı/sil. Elle saatli etkinlik: telefon varsa
    source=google randevu, yoksa veya Off Day anahtar kelimesi varsa time_off.
    Tüm-gün randevu üretmez; tüm-gün Off Day olur.
    """
    if not is_google_calendar_enabled():
        return {'ok': False, 'reason': 'disabled'}
    calendar_id = get_google_calendar_config()['calendar_id']
    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT events_sync_token FROM google_calendar_sync_state WHERE calendar_id = %s',
            (calendar_id,),
        )
        state = cursor.fetchone()
        sync_token = state[0] if state else None

        service = _get_calendar_service()
        items = []
        next_token = None
        # syncToken suresi dolarsa (410) token dusurulup bir kez tam senkron
        # yapilir. Ozyineleme yerine sinirli dongu: Google israrla 410 donerse
        # yigin tasmasi olmaz ve baglanti tek yerden birakilir.
        for attempt in range(2):
            items = []
            next_token = None
            page_token = None
            full_sync = not sync_token
            try:
                while True:
                    kwargs = {
                        'calendarId': calendar_id,
                        'maxResults': 250,
                        'pageToken': page_token,
                        'showDeleted': True,
                        'singleEvents': True,
                        'fields': (
                            'items(id,status,transparency,start,end,etag,summary,'
                            'extendedProperties,description,recurringEventId),'
                            'nextPageToken,nextSyncToken'
                        ),
                    }
                    if sync_token and not full_sync:
                        kwargs['syncToken'] = sync_token
                    else:
                        tz = _studio_tz()
                        now = datetime.now(tz) if tz else datetime.now(timezone.utc)
                        kwargs['timeMin'] = (now - timedelta(days=_BUSY_LOOKBACK_DAYS)).isoformat()
                        kwargs['timeMax'] = (now + timedelta(days=_BUSY_LOOKAHEAD_DAYS)).isoformat()
                    resp = _google_execute(lambda kw=kwargs: _get_calendar_service().events().list(**kw))
                    items.extend(resp.get('items') or [])
                    page_token = resp.get('nextPageToken')
                    next_token = resp.get('nextSyncToken') or next_token
                    if not page_token:
                        break
                break
            except Exception as exc:
                if _http_status(exc) == 410 and sync_token and attempt == 0:
                    logger.warning('Google syncToken suresi doldu, tam senkron')
                    cursor.execute(
                        """
                        INSERT INTO google_calendar_sync_state (calendar_id, events_sync_token, updated_at)
                        VALUES (%s, NULL, NOW())
                        ON CONFLICT (calendar_id) DO UPDATE
                           SET events_sync_token = NULL, updated_at = NOW()
                        """,
                        (calendar_id,),
                    )
                    conn.commit()
                    sync_token = None
                    continue
                raise

        summary = {
            'echo': 0, 'moved': 0, 'cancel': 0, 'revert': 0,
            'skip': 0, 'imported': 0, 'unmatched': 0, 'conflict': 0,
        }
        cancelled_ids = []
        for event in items:
            if event.get('recurringEventId') and not event.get('start'):
                summary['skip'] += 1
                continue
            marker = len(cancelled_ids)
            try:
                cursor.execute('SAVEPOINT gcal_inbound_event')
                action = _handle_inbound_event(
                    cursor, event, calendar_id, cancelled_ids
                ) or 'skip'
                cursor.execute('RELEASE SAVEPOINT gcal_inbound_event')
            except Exception as exc:
                try:
                    cursor.execute('ROLLBACK TO SAVEPOINT gcal_inbound_event')
                except Exception:
                    pass
                # Savepoint geri alindiysa iptal de gerceklesmedi; bildirim
                # gonderilmemeli.
                del cancelled_ids[marker:]
                logger.warning(
                    'Google inbound event atlandi | event=%s hata=%s',
                    (event.get('id') or '')[:80],
                    str(exc).strip()[:200],
                )
                action = 'skip'
            summary[action] = summary.get(action, 0) + 1
            try:
                _apply_inbound_busy_side_effect(cursor, calendar_id, event, action)
            except Exception as busy_exc:
                logger.warning(
                    'Google inbound busy yan etki atlandi | event=%s hata=%s',
                    (event.get('id') or '')[:80],
                    str(busy_exc).strip()[:160],
                )

        if next_token:
            cursor.execute(
                """
                INSERT INTO google_calendar_sync_state
                    (calendar_id, events_sync_token, last_events_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                ON CONFLICT (calendar_id) DO UPDATE
                   SET events_sync_token = EXCLUDED.events_sync_token,
                       last_events_at = NOW(),
                       updated_at = NOW()
                """,
                (calendar_id, next_token),
            )
        conn.commit()
        cursor.close()
        # Yalnizca commit basarili olduktan sonra: iptal edilmemis randevu icin
        # musteriye "iptal edildi" mesaji gitmesin.
        _dispatch_cancel_notifications(cancelled_ids)
        if (
            summary['moved'] or summary['cancel'] or summary['revert']
            or summary['imported'] or summary['unmatched'] or summary['conflict']
        ):
            if summary['moved'] or summary['cancel'] or summary['revert'] or summary['imported']:
                kick_queue_worker()
            logger.info('Google inbound: %s', summary)
        return {'ok': True, **summary}
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        log_error(logger, E_GCAL_001, 'Google inbound yoklama basarisiz', exc=e)
        return {'ok': False, 'reason': str(e)[:200]}
    finally:
        _disconnect(conn)


def enqueue_identity_backfill(cursor=None):
    """Mevcut etkinliklere extendedProperties / etag / calendar_id yazar."""
    if not is_google_calendar_enabled():
        return 0
    own_conn = cursor is None
    conn = None
    try:
        if own_conn:
            conn = _connect()
            cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id
              FROM appointments
             WHERE google_event_id IS NOT NULL
               AND status IS DISTINCT FROM 'cancelled'
               AND COALESCE(source, '') IS DISTINCT FROM 'google'
               AND (google_etag IS NULL OR google_calendar_id IS NULL)
            """
        )
        ids = [row[0] for row in cursor.fetchall()]
        count = 0
        for apt_id in ids:
            if enqueue_appointment_sync(cursor, apt_id):
                count += 1
        if own_conn:
            conn.commit()
            cursor.close()
            if count:
                kick_queue_worker()
        return count
    except Exception as e:
        if own_conn and conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning('Takvim kimlik backfill atlandi: %s', e)
        return 0
    finally:
        if own_conn:
            _disconnect(conn)


def run_gcal_inbound_tick():
    """Scheduler: kimlik backfill, incremental inbound, sonra (seyrek) tam mesguliyet."""
    enqueue_identity_backfill()
    inbound = poll_inbound_changes()
    busy = refresh_external_busy()
    return {'busy': busy, 'inbound': inbound}
