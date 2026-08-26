"""
Phase 1: One-way sync PostgreSQL appointments -> single shared Google Calendar.
Google -> system is NOT implemented (manual calendar events are ignored).
"""
import logging
import json
import os
from datetime import date, datetime, timedelta, time as dt_time

import psycopg2

from config import DATABASE_CONFIG, SITE_CONFIG, get_google_calendar_config
from error_codes import E_GCAL_001
from logging_setup import log_error

logger = logging.getLogger(__name__)

_CALENDAR_SERVICE = None
_SCOPES = ['https://www.googleapis.com/auth/calendar']

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


def _get_calendar_service():
    global _CALENDAR_SERVICE
    if _CALENDAR_SERVICE is not None:
        return _CALENDAR_SERVICE
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    cfg = get_google_calendar_config()
    creds = service_account.Credentials.from_service_account_file(
        cfg['credentials_path'],
        scopes=_SCOPES,
    )
    _CALENDAR_SERVICE = build('calendar', 'v3', credentials=creds, cache_discovery=False)
    return _CALENDAR_SERVICE


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


def _connect():
    return psycopg2.connect(
        host=DATABASE_CONFIG['host'],
        port=DATABASE_CONFIG['port'],
        user=DATABASE_CONFIG['user'],
        password=DATABASE_CONFIG['password'],
        database=DATABASE_CONFIG['database'],
        **({'sslmode': DATABASE_CONFIG['sslmode']} if DATABASE_CONFIG.get('sslmode') else {}),
    )


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


def sync_appointment_to_google(appointment_id):
    """Create or update Google Calendar event for an appointment."""
    if not is_google_calendar_enabled():
        return None

    conn = None
    try:
        conn = _connect()
        cursor = conn.cursor()
        row = _fetch_appointment_row(cursor, appointment_id)
        if not row:
            logger.warning('Google Calendar: randevu #%s bulunamadı', appointment_id)
            return None

        payload = _build_event_body(row)
        existing_id = payload.pop('existing_event_id', None)
        calendar_id = get_google_calendar_config()['calendar_id']
        service = _get_calendar_service()
        body = {
            key: payload[key]
            for key in ('summary', 'description', 'start', 'end', 'location', 'colorId')
            if key in payload
        }

        if existing_id:
            event = (
                service.events()
                .update(calendarId=calendar_id, eventId=existing_id, body=body)
                .execute()
            )
            event_id = event.get('id', existing_id)
            logger.info('Google Calendar güncellendi: apt #%s event %s', appointment_id, event_id)
        else:
            event = (
                service.events()
                .insert(calendarId=calendar_id, body=body)
                .execute()
            )
            event_id = event.get('id')
            if event_id:
                cursor.execute(
                    'UPDATE appointments SET google_event_id = %s WHERE id = %s',
                    (event_id, appointment_id),
                )
            logger.info('Google Calendar oluşturuldu: apt #%s event %s', appointment_id, event_id)

        conn.commit()
        cursor.close()
        return event_id if not existing_id else existing_id
    except Exception as e:
        if conn:
            conn.rollback()
        log_error(logger, E_GCAL_001, "Google Takvim senkronu basarisiz", exc=e, appointment_id=appointment_id)
        return None
    finally:
        if conn:
            conn.close()


def delete_google_calendar_event(google_event_id):
    """Remove event from shared calendar (idempotent)."""
    if not is_google_calendar_enabled() or not google_event_id:
        return False

    try:
        service = _get_calendar_service()
        service.events().delete(
            calendarId=get_google_calendar_config()['calendar_id'],
            eventId=google_event_id,
        ).execute()
        logger.info('Google Calendar etkinlik silindi: %s', google_event_id)
        return True
    except Exception as e:
        err = str(e).lower()
        if '404' in err or 'not found' in err:
            logger.info('Google Calendar etkinlik zaten yok: %s', google_event_id)
            return True
        log_error(logger, E_GCAL_001, "Google Takvim etkinligi silinemedi", exc=e, google_event_id=google_event_id)
        return False


def on_appointment_created(appointment_id):
    return sync_appointment_to_google(appointment_id)


def on_appointment_status_changed(appointment_id):
    return sync_appointment_to_google(appointment_id)


def on_appointment_cancelled(google_event_id):
    return delete_google_calendar_event(google_event_id)
