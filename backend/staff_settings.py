"""Personel takvim rengi ve kazanç yüzdesi ayarları.

Flask/DB bağımlılığı olmayan küçük yardımcılar: Google Takvim etkinlik rengi
seçimi, kazanç yüzdesi doğrulaması ve personel payı hesabı. app.py ve
google_calendar_sync.py birlikte kullanır (döngüsel import olmasın diye ayrı).
"""

from decimal import Decimal

# Google Takvim etkinlik renkleri (colorId 1-11). Renkler ADLARLA tanınır: Google
# Takvim arayüzünde görünen adlar ile birebir aynıdır. `hex`, yeni Takvim
# arayüzündeki tonlara yakın örnek renktir (API'nin eski palet kodları değil);
# yalnızca formdaki renk kutusu içindir, asıl tanımlayıcı renk numarası/adıdır.
# https://developers.google.com/workspace/calendar/api/v3/reference/colors
CALENDAR_COLORS = (
    {'id': '1', 'name_en': 'Lavender', 'name_tr': 'Lavanta', 'hex': '#7986CB'},
    {'id': '2', 'name_en': 'Sage', 'name_tr': 'Adaçayı', 'hex': '#33B679'},
    {'id': '3', 'name_en': 'Grape', 'name_tr': 'Üzüm', 'hex': '#8E24AA'},
    {'id': '4', 'name_en': 'Flamingo', 'name_tr': 'Flamingo', 'hex': '#E67C73'},
    {'id': '5', 'name_en': 'Banana', 'name_tr': 'Muz', 'hex': '#F6BF26'},
    {'id': '6', 'name_en': 'Tangerine', 'name_tr': 'Mandalina', 'hex': '#F4511E'},
    {'id': '7', 'name_en': 'Peacock', 'name_tr': 'Tavuskuşu', 'hex': '#039BE5'},
    {'id': '8', 'name_en': 'Graphite', 'name_tr': 'Grafit', 'hex': '#616161'},
    {'id': '9', 'name_en': 'Blueberry', 'name_tr': 'Yaban Mersini', 'hex': '#3F51B5'},
    {'id': '10', 'name_en': 'Basil', 'name_tr': 'Fesleğen', 'hex': '#0B8043'},
    {'id': '11', 'name_en': 'Tomato', 'name_tr': 'Domates', 'hex': '#D50000'},
)

# Grafit, Off Day etkinlikleri için ayrılmıştır: personele seçtirilmez.
RESERVED_COLOR_ID = '8'

SELECTABLE_COLORS = tuple(c for c in CALENDAR_COLORS if c['id'] != RESERVED_COLOR_ID)
SELECTABLE_COLOR_IDS = tuple(c['id'] for c in SELECTABLE_COLORS)
COLOR_BY_ID = {c['id']: c for c in CALENDAR_COLORS}

# Rengi henüz atanmamış personel için dönüşümlü yedek sıra (eski davranışla aynı).
_FALLBACK_ROTATION = ('6', '11', '5', '2', '7', '10', '9', '4', '3', '1')

ALLOWED_COMMISSION_PERCENTS = (30, 50, 70)
DEFAULT_COMMISSION_PERCENT = 50


def color_label(color_id):
    """'11' -> 'Domates (Tomato)'; bilinmeyen değer olduğu gibi döner."""
    color = COLOR_BY_ID.get(str(color_id))
    if not color:
        return str(color_id)
    return f"{color['name_tr']} ({color['name_en']})"


def normalize_color_id(value):
    """Formdan gelen renk değerini doğrular. Boş -> None; geçersiz/ayrılmış -> ValueError."""
    if value is None or str(value).strip() == '':
        return None
    color_id = str(value).strip()
    if color_id not in SELECTABLE_COLOR_IDS:
        raise ValueError('Geçersiz takvim rengi')
    return color_id


def normalize_commission_percent(value):
    """Kazanç yüzdesi yalnızca 30, 50 veya 70 olabilir; aksi halde ValueError."""
    try:
        percent = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError('Kazanç yüzdesi 30, 50 veya 70 olmalı') from None
    if percent not in ALLOWED_COMMISSION_PERCENTS:
        raise ValueError('Kazanç yüzdesi 30, 50 veya 70 olmalı')
    return percent


def staff_share_amount(full_price, percent=DEFAULT_COMMISSION_PERCENT):
    """Personelin net kazancı: yapılan işin %percent'i (kuruş hassasiyetinde)."""
    return (Decimal(full_price or 0) * Decimal(int(percent)) / Decimal(100)).quantize(Decimal('0.01'))


def fallback_color_id(staff_id):
    """Rengi atanmamış personel için sabit yedek renk. staff_id yoksa Grafit."""
    try:
        sid = int(staff_id) if staff_id else None
    except (TypeError, ValueError):
        sid = None
    if not sid:
        return RESERVED_COLOR_ID
    return _FALLBACK_ROTATION[(max(sid, 1) - 1) % len(_FALLBACK_ROTATION)]


def colors_in_use(cursor, exclude_staff_id=None):
    """Aktif personelin kullandığı renkler: {color_id: [personel adı, ...]}."""
    cursor.execute(
        """
        SELECT calendar_color_id, name
          FROM artists
         WHERE calendar_color_id IS NOT NULL
           AND COALESCE(is_active, TRUE)
           AND (%s::int IS NULL OR id <> %s::int)
         ORDER BY display_order, id
        """,
        (exclude_staff_id, exclude_staff_id),
    )
    used = {}
    for color_id, name in cursor.fetchall() or []:
        used.setdefault(str(color_id), []).append(name)
    return used


def first_free_color_id(cursor, exclude_staff_id=None):
    """Kimsenin kullanmadığı ilk seçilebilir renk; hepsi doluysa None."""
    used = colors_in_use(cursor, exclude_staff_id)
    for color_id in SELECTABLE_COLOR_IDS:
        if color_id not in used:
            return color_id
    return None
