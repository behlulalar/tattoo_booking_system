"""
PostgreSQL randevulari paylaşılan Google Calendar ile senkronlar.

Sistem randevusu -> Google (kuyruk). Elle Google etkinliği -> source=google
randevu (WhatsApp yok). origin=roof taşı/sil inbound. Tüm-gün ve yinelenen
master randevu olmaz; meşgul zaman olarak kalabilir.
"""
import hashlib
import logging
import json
import os
import random
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta, time as dt_time

import psycopg2

from config import DATABASE_CONFIG, SITE_CONFIG, get_google_calendar_config
from error_codes import E_GCAL_001, E_GCAL_002, E_GCAL_003
from logging_setup import log_error

logger = logging.getLogger(__name__)

_SCOPES = ['https://www.googleapis.com/auth/calendar']

# googleapiclient Resource nesnesi (altindaki httplib2.Http) thread-safe degil;
# her thread kendi ornegini kurar. _fingerprint degisince yeniden kurulur.
_thread_local = threading.local()

# Google API cagrilarinda timeout yoksa askida kalan baglanti gunicorn
# thread'ini timeout suresi kadar tutar.
GCAL_HTTP_TIMEOUT = int(os.getenv('GOOGLE_CALENDAR_HTTP_TIMEOUT', '30'))

# Kuyruk isi kac denemeden sonra birakilir + denemeler arasi bekleme
GCAL_MAX_ATTEMPTS = int(os.getenv('GOOGLE_CALENDAR_MAX_ATTEMPTS', '6'))
_BACKOFF_SECONDS = (60, 300, 900, 3600, 10800, 21600)
# Bir is islenirken baska worker'in ayni isi almasini engelleyen kiralama suresi
_CLAIM_LEASE_SECONDS = 300
# Ayni randevunun iki paralel senkronunda mukerrer etkinlik olusmasini onler
_GCAL_ADVISORY_NAMESPACE = 0x6743

GCAL_EVENT_ORIGIN = 'roof'
_BUSY_LOOKBACK_DAYS = 90
_BUSY_LOOKAHEAD_DAYS = 90
_GCAL_PHONE_RE = re.compile(r'(?<!\d)(0?5\d{9})(?!\d)')
_MIN_ARTIST_KEY_LEN = 3
_unmatched_artist_logged = set()
_UNMATCHED_LOG_CAP = 400

GCAL_STAFF_COLOR_IDS = (
    '7',   # Peacock (mavi)
    '6',   # Tangerine (turuncu)
    '10',  # Basil (yeşil)
    '9',   # Blueberry (lacivert)
    '4',   # Flamingo (pembe)
    '11',  # Tomato (kırmızı)
    '3',   # Grape (mor)
    '5',   # Banana (sarı)
    '2',   # Sage (açık yeşil)
    '1',   # Lavender
)

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


def _color_id_for_staff(staff_id):
    """Her sanatçıya Google Calendar colorId (1-11) — sabit eşleme."""
    if not staff_id:
        return '8'
    return GCAL_STAFF_COLOR_IDS[int(staff_id) % len(GCAL_STAFF_COLOR_IDS)]


def _staff_color_label(staff_id):
    color_id = _color_id_for_staff(staff_id)
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


def _event_private(event):
    props = (event or {}).get('extendedProperties') or {}
    private = props.get('private') or {}
    return private if isinstance(private, dict) else {}


def _is_our_event(event):
    private = _event_private(event)
    if (private.get('origin') or '').strip() == GCAL_EVENT_ORIGIN:
        return True
    description = (event or {}).get('description') or ''
    return 'Randevu ID:' in description


def _our_appointment_id_from_event(event):
    private = _event_private(event)
    raw = (private.get('appointment_id') or '').strip()
    if raw.isdigit():
        return int(raw)
    match = re.search(r'Randevu ID:\s*(\d+)', (event or {}).get('description') or '')
    return int(match.group(1)) if match else None


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
    color_id = _color_id_for_staff(staff_id)
    color_label = _staff_color_label(staff_id)

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
        f"Sanatçı: {artist} (takvim rengi: {color_label})",
        '',
        '— Müşteri —',
        f"Ad Soyad: {customer}",
        f"Telefon: {phone}",
        '',
        '— Dövme —',
        f"Tarz: {style_label}",
        f"Bölge: {area_label}",
        f"Boyut: {size}",
        f"Süre: {duration} dk",
    ]
    if reference_number:
        lines.append(f"Referans No: {reference_number}")
    if request_description and str(request_description).strip():
        lines.append(f"Not: {str(request_description).strip()}")
    if price is not None and float(price or 0) > 0:
        lines.append(f"Ücret: {float(price):.2f} ₺")
    lines.extend([
        '',
        f"Randevu ID: {appointment_id}",
        SITE_CONFIG.get('business_name', ''),
    ])
    if SITE_CONFIG.get('business_phone'):
        lines.append(f"Stüdyo tel: {SITE_CONFIG['business_phone']}")
    if SITE_CONFIG.get('business_address'):
        lines.append(f"Adres: {SITE_CONFIG['business_address']}")

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
    address = (SITE_CONFIG.get('business_address') or '').strip()
    if address:
        body['location'] = address[:500]
    return body


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
        service = _get_calendar_service()
        body = {
            key: payload[key]
            for key in (
                'summary', 'description', 'start', 'end', 'location',
                'colorId', 'extendedProperties',
            )
            if key in payload
        }

        event_id = None
        etag = None
        if existing_id:
            try:
                event = (
                    service.events()
                    .update(calendarId=calendar_id, eventId=existing_id, body=body)
                    .execute()
                )
                event_id = event.get('id') or existing_id
                etag = event.get('etag')
                logger.info(
                    'Google Calendar guncellendi: apt #%s event %s', appointment_id, event_id
                )
            except Exception as exc:
                if not _is_missing_event_error(exc):
                    raise
                # Etkinlik Google tarafinda elle silinmis. Bayat id temizlenmezse
                # bu randevu bir daha asla takvime dusmez.
                logger.warning(
                    'Google Calendar etkinligi yok, yeniden olusturuluyor | apt=%s event=%s',
                    appointment_id,
                    existing_id,
                )
                cursor.execute(
                    'UPDATE appointments SET google_event_id = NULL WHERE id = %s',
                    (appointment_id,),
                )
                existing_id = None

        if not existing_id:
            event = service.events().insert(calendarId=calendar_id, body=body).execute()
            event_id = event.get('id')
            etag = event.get('etag')
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
                    service.events().delete(
                        calendarId=calendar_id, eventId=event_id
                    ).execute()
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


def _perform_event_delete(google_event_id):
    """Takvimden etkinligi sil. Zaten yoksa basarili sayar."""
    if not is_google_calendar_enabled():
        return 'disabled'
    if not google_event_id:
        return 'ok'

    service = _get_calendar_service()
    try:
        service.events().delete(
            calendarId=get_google_calendar_config()['calendar_id'],
            eventId=google_event_id,
        ).execute()
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


def _enqueue(cursor, operation, appointment_id=None, google_event_id=None):
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
            INSERT INTO google_calendar_queue (operation, appointment_id, google_event_id)
            VALUES (%s, %s, %s)
            """,
            (operation, appointment_id, google_event_id),
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
            RETURNING q.id, q.operation, q.appointment_id, q.google_event_id, q.attempts
            """,
            (_CLAIM_LEASE_SECONDS,),
        )
        row = cursor.fetchone()
        conn.commit()
        return row
    finally:
        cursor.close()


def _finish_item(conn, item_id, operation, appointment_id):
    """Basarili isi kuyruktan dusur."""
    cursor = conn.cursor()
    try:
        if operation == 'upsert' and appointment_id:
            # Ayni randevu icin biriken diger upsert isleri gereksiz: senkron
            # her zaman guncel DB durumunu yazar.
            cursor.execute(
                """
                DELETE FROM google_calendar_queue
                 WHERE operation = 'upsert'
                   AND appointment_id = %s
                   AND dead_at IS NULL
                """,
                (appointment_id,),
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
            cursor.execute(
                """
                UPDATE google_calendar_queue
                   SET attempts = GREATEST(attempts - 1, 0),
                       next_attempt_at = NOW() + INTERVAL '60 seconds'
                 WHERE id = %s
                """,
                (item_id,),
            )
            conn.commit()
            return False

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
            item_id, operation, appointment_id, event_id, attempts = item
            try:
                if operation == 'upsert':
                    status, _event = _perform_appointment_sync(appointment_id)
                    if status == 'busy':
                        summary['busy'] += 1
                        _reschedule_item(conn, item_id, attempts, None, soon=True)
                        continue
                else:
                    _perform_event_delete(event_id)
                _finish_item(conn, item_id, operation, appointment_id)
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


# =============================================
# FAZ 2a / 2b — yerel meşguliyet + inbound (yankı filtresi)
# =============================================

_slot_validator = None


def set_slot_validator(fn):
    """app.py compute_available_start_slots sarmalayicisi (dongusel import yok)."""
    global _slot_validator
    _slot_validator = fn


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


def _round_duration_minutes(start_dt, end_dt):
    seconds = max(0, int((end_dt - start_dt).total_seconds()))
    minutes = max(30, int(round(seconds / 60.0)))
    if minutes % 30:
        minutes = ((minutes // 30) + 1) * 30
    return minutes


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
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            showDeleted=False,
            maxResults=250,
            pageToken=page_token,
            fields=(
                'items(id,status,transparency,start,end,summary,'
                'extendedProperties,description,recurringEventId),'
                'nextPageToken'
            ),
        ).execute()
        events.extend(resp.get('items') or [])
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return events


def refresh_external_busy():
    """Elle/yabancı etkinlikleri yerel tabloya yazar. Booking yolu Google çağırmaz."""
    if not is_google_calendar_enabled():
        return {'ok': False, 'reason': 'disabled'}
    calendar_id = get_google_calendar_config()['calendar_id']
    tz = _studio_tz()
    now = datetime.now(tz) if tz else datetime.utcnow()
    time_min = (now - timedelta(days=_BUSY_LOOKBACK_DAYS)).isoformat()
    time_max = (now + timedelta(days=_BUSY_LOOKAHEAD_DAYS)).isoformat()
    conn = None
    try:
        service = _get_calendar_service()
        events = _list_events_window(service, calendar_id, time_min, time_max)
        conn = _connect()
        cursor = conn.cursor()
        imported = 0
        for event in events:
            if _import_manual_google_event(cursor, event, calendar_id) == 'imported':
                imported += 1

        rows = []
        for event in events:
            if (event.get('status') or '') == 'cancelled':
                continue
            if (event.get('transparency') or '') == 'transparent':
                continue
            if _is_our_event(event):
                continue
            event_id = (event.get('id') or '').strip()
            if event_id:
                cursor.execute(
                    """
                    SELECT 1 FROM appointments
                     WHERE google_event_id = %s
                       AND status IS DISTINCT FROM 'cancelled'
                    """,
                    (event_id,),
                )
                if cursor.fetchone():
                    continue
            start_dt, end_dt, all_day = _parse_event_datetimes(event)
            if not start_dt or not end_dt or end_dt <= start_dt:
                continue
            # Saatli elle etkinlik sanatçıya bağlanır; eşleşmezse herkesi kilitleme.
            # Tüm-gün / yinelenen etkinlik stüdyo geneli meşgul kalır.
            if not all_day and not event.get('recurringEventId'):
                continue
            rows.append((calendar_id, start_dt, end_dt, event.get('id')))

        cursor.execute(
            'DELETE FROM google_external_busy WHERE calendar_id = %s',
            (calendar_id,),
        )
        for row in rows:
            cursor.execute(
                """
                INSERT INTO google_external_busy
                    (calendar_id, start_at, end_at, google_event_id, synced_at)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                row,
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


def _times_match_appointment(start_dt, duration_minutes, apt_date, apt_time, apt_duration):
    if not start_dt:
        return False
    local_date = start_dt.date()
    local_time = start_dt.strftime('%H:%M')
    return (
        local_date == _as_date(apt_date)
        and local_time == _time_to_str(apt_time)
        and int(duration_minutes or 0) == int(apt_duration or 0)
    )


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


def _load_bookable_artists(cursor):
    cursor.execute(
        """
        SELECT id, name, COALESCE(calendar_aliases, '{}'::text[])
          FROM artists
         WHERE role IS DISTINCT FROM 'tech_support'
         ORDER BY display_order ASC, id ASC
        """
    )
    return cursor.fetchall() or []


def _resolve_or_create_gcal_customer(cursor, name, surname, phone, event_id):
    resolved_phone = phone or _synthetic_gcal_phone(event_id)
    cursor.execute(
        """
        INSERT INTO customers (phone, name, surname)
        VALUES (%s, %s, %s)
        ON CONFLICT (phone) DO UPDATE
           SET name = COALESCE(NULLIF(EXCLUDED.name, ''), customers.name),
               surname = COALESCE(NULLIF(EXCLUDED.surname, ''), customers.surname)
        RETURNING id
        """,
        (resolved_phone, name, surname),
    )
    return cursor.fetchone()[0]


def _stamp_origin_on_event(calendar_id, event_id, appointment_id, row_for_hash):
    if not event_id or not appointment_id:
        return
    try:
        service = _get_calendar_service()
        content_hash = _content_hash(
            row_for_hash[0], row_for_hash[1], row_for_hash[2], 'confirmed', row_for_hash[3],
        )
        service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body={'extendedProperties': _extended_properties(appointment_id, content_hash)},
        ).execute()
    except Exception as exc:
        logger.warning(
            'Google etkinligine origin yazilamadi | event=%s apt=%s hata=%s',
            event_id, appointment_id, str(exc)[:160],
        )


def _import_manual_google_event(cursor, event, calendar_id):
    """Elle Google etkinligini source=google randevuya cevirir. WhatsApp yok."""
    if (event.get('status') or '') == 'cancelled':
        return 'skip'
    if (event.get('transparency') or '') == 'transparent':
        return 'skip'
    if event.get('recurringEventId'):
        return 'skip'
    event_id = (event.get('id') or '').strip()
    if not event_id:
        return 'skip'

    start_dt, end_dt, all_day = _parse_event_datetimes(event)
    if all_day or not start_dt or not end_dt:
        return 'skip'

    duration_minutes = _round_duration_minutes(start_dt, end_dt)
    local_date = start_dt.date()
    local_time = start_dt.strftime('%H:%M') + ':00'

    artists = _load_bookable_artists(cursor)
    if not artists:
        logger.warning('Google manuel randevu: kitaplanabilir sanatci yok')
        return 'skip'

    staff_id, _staff_name, cust_name, cust_surname, phone = _parse_manual_event_title(
        event.get('summary') or '', artists
    )
    if not staff_id:
        _log_unmatched_artist(event_id, event.get('summary') or '')
        return 'unmatched'

    cursor.execute(
        'SELECT id FROM appointments WHERE google_event_id = %s',
        (event_id,),
    )
    if cursor.fetchone():
        return 'skip'

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
        'Google manuel etkinlik randevu oldu (WhatsApp yok) apt #%s event=%s staff=%s',
        appointment_id, event_id, staff_id,
    )
    return 'imported'


def _handle_inbound_event(cursor, event, calendar_id):
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

    if status == 'completed':
        if deleted:
            enqueue_appointment_sync(cursor, appointment_id)
            return 'revert'
        if all_day or not _times_match_appointment(
            start_dt, duration_minutes, apt_date, apt_time, apt_duration
        ):
            enqueue_appointment_sync(cursor, appointment_id)
            return 'revert'
        return 'skip'

    if deleted:
        if source in ('customer', 'admin', 'google'):
            if _soft_cancel_from_google(cursor, appointment_id):
                logger.info('Google silme -> soft iptal (WhatsApp yok) apt #%s', appointment_id)
                return 'cancel'
        return 'skip'

    if all_day or not start_dt or not end_dt:
        enqueue_appointment_sync(cursor, appointment_id)
        return 'revert'

    local_date = start_dt.date()
    local_time = start_dt.strftime('%H:%M')

    if _times_match_appointment(start_dt, duration_minutes, apt_date, apt_time, apt_duration):
        if event.get('etag') and event.get('etag') != stored_etag:
            cursor.execute(
                'UPDATE appointments SET google_etag = %s, google_updated_at = NOW() WHERE id = %s',
                (event.get('etag'), appointment_id),
            )
        return 'echo'

    allowed = True
    if source != 'google' and _slot_validator is not None:
        allowed = bool(_slot_validator(
            cursor,
            staff_id,
            local_date.isoformat(),
            local_time,
            duration_minutes,
            appointment_id,
            body_area or None,
        ))
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
        return 'moved'
    enqueue_appointment_sync(cursor, appointment_id)
    return 'revert'


def poll_inbound_changes():
    """syncToken ile yalniz origin=roof etkinliklerini isler. Randevu uretmez."""
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
                    now = datetime.now(tz) if tz else datetime.utcnow()
                    kwargs['timeMin'] = (now - timedelta(days=_BUSY_LOOKBACK_DAYS)).isoformat()
                    kwargs['timeMax'] = (now + timedelta(days=_BUSY_LOOKAHEAD_DAYS)).isoformat()
                resp = service.events().list(**kwargs).execute()
                items.extend(resp.get('items') or [])
                page_token = resp.get('nextPageToken')
                next_token = resp.get('nextSyncToken') or next_token
                if not page_token:
                    break
        except Exception as exc:
            if _http_status(exc) == 410:
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
                cursor.close()
                _disconnect(conn)
                return poll_inbound_changes()
            raise

        summary = {
            'echo': 0, 'moved': 0, 'cancel': 0, 'revert': 0,
            'skip': 0, 'imported': 0, 'unmatched': 0,
        }
        for event in items:
            if event.get('recurringEventId') and not event.get('start'):
                summary['skip'] += 1
                continue
            action = _handle_inbound_event(cursor, event, calendar_id) or 'skip'
            summary[action] = summary.get(action, 0) + 1

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
        if (
            summary['moved'] or summary['cancel'] or summary['revert']
            or summary['imported'] or summary['unmatched']
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
    """Scheduler: kimlik backfill, yerel meşguliyet, sonra inbound."""
    enqueue_identity_backfill()
    busy = refresh_external_busy()
    inbound = poll_inbound_changes()
    return {'busy': busy, 'inbound': inbound}
