"""WhatsApp mesaj şablonları — Wapio /send-text (karşılama, randevu, hatırlatma)."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from config import SITE_CONFIG, get_evolution_config

MESSAGE_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'message_settings.json')
WELCOME_MESSAGE_MAX_LEN = 4000

WELCOME_PLACEHOLDERS = (
    '{business_name}',
    '{randevu_url}',
    '{phone}',
    '{address}',
    '{hours}',
)


def _biz() -> dict:
    return {
        'name': (SITE_CONFIG.get('business_name') or 'Roof Tattoo Gallery').strip(),
        'phone': (SITE_CONFIG.get('business_phone') or '').strip(),
        'address': (SITE_CONFIG.get('business_address') or '').strip(),
        'hours': (SITE_CONFIG.get('working_hours') or 'Pazartesi - Cumartesi: 09:00 - 20:00').strip(),
        'url': (SITE_CONFIG.get('randevu_url') or '').strip().rstrip('/'),
    }


def _phone_display(phone: str) -> str:
    s = str(phone or '').strip()
    if not s:
        return '-'
    return s if s.startswith('0') else f'0{s}'


def _customer_line(phone: str, customer_name: str | None = None) -> str:
    display = _phone_display(phone)
    if customer_name and str(customer_name).strip():
        return f'📞 Müşteri: {customer_name.strip()} ({display})'
    return f'📞 Müşteri: {display}'


def _truncate_text(text: str, max_len: int = 240) -> str:
    s = str(text or '').strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + '...'


def _tattoo_detail_lines(
    *,
    body_area: str | None = None,
    size: str | None = None,
    description: str | None = None,
    reference_number: str | None = None,
) -> list[str]:
    lines: list[str] = []
    if reference_number:
        lines.append(f'🔖 Referans: *{reference_number}*')
    if body_area:
        lines.append(f'🖋️ Bölge: {body_area}')
    if size:
        lines.append(f'📏 Boyut: {size}')
    if description and str(description).strip():
        lines.append(f'📝 Not: {_truncate_text(description)}')
    return lines


def _price_line(price, prefix='\n💰 Ücret: ') -> str:
    if price is None:
        return ''
    try:
        value = float(price)
    except (TypeError, ValueError):
        return ''
    if value <= 0:
        return ''
    return f'{prefix}{value:.2f} ₺'


def _contact_footer(b: dict) -> str:
    parts = []
    if b['address']:
        parts.append(f"📍 *Adres:*\n{b['address']}")
    if b['phone']:
        parts.append(f"📞 *İletişim:*\n{b['phone']}")
    footer = '\n\n'.join(parts)
    if footer:
        footer += f'\n\n{b["name"]}'
    else:
        footer = b['name']
    return footer


def default_welcome_message_template() -> str:
    return """👋 *{business_name}'ya Hoş Geldiniz!*

Merhaba! Bize ulaştığınız için teşekkür ederiz.

🖋️ *Online Dövme Randevusu:*
{randevu_url}

📞 *Telefon:*
{phone}

📍 *Adres:*
{address}

⏰ *Çalışma Saatlerimiz:*
{hours}

_Randevu almak için yukarıdaki linke tıklayabilirsiniz._

{business_name} 🎨"""


def _placeholder_values() -> dict:
    b = _biz()
    return {
        '{business_name}': b['name'] or 'Roof Tattoo Gallery',
        '{randevu_url}': b['url'] or 'Web sitemizden randevu alabilirsiniz.',
        '{phone}': b['phone'] or 'WhatsApp üzerinden yazabilirsiniz.',
        '{address}': b['address'] or '—',
        '{hours}': b['hours'] or '—',
    }


def welcome_placeholder_values() -> dict:
    return dict(_placeholder_values())


def render_welcome_message(template: str | None = None) -> str:
    text = template if template is not None else get_welcome_message_template()
    for key, value in _placeholder_values().items():
        text = text.replace(key, str(value))
    return text


def get_message_settings() -> dict:
    try:
        if os.path.exists(MESSAGE_SETTINGS_FILE):
            with open(MESSAGE_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                stored = json.load(f)
                if isinstance(stored, dict):
                    return stored
    except Exception:
        pass
    return {}


def get_welcome_message_template() -> str:
    raw = get_message_settings().get('welcome_message')
    if isinstance(raw, str) and raw.strip():
        return raw
    return default_welcome_message_template()


def save_welcome_message_template(text: str) -> str:
    template = (text or '').replace('\r\n', '\n')
    if len(template) > WELCOME_MESSAGE_MAX_LEN:
        template = template[:WELCOME_MESSAGE_MAX_LEN]
    settings = get_message_settings()
    settings['welcome_message'] = template
    with open(MESSAGE_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)
    return template


def build_welcome_message() -> str:
    """Webhook: müşteri ilk mesaj attığında otomatik karşılama."""
    return render_welcome_message()


def build_tattoo_request_received_message(
    reference_number: str,
    staff_name: str,
    *,
    body_area: str | None = None,
    size: str | None = None,
    pre_consultation: bool = False,
    config_undecided: bool = False,
    loyalty_attached: dict | None = None,
) -> str:
    """Müşteriye: dövme talebi alındı."""
    b = _biz()

    if pre_consultation:
        title = 'Ön Görüşme Talebiniz Alındı'
        next_step = 'Sanatçımız talebinizi inceleyip en kısa sürede sizinle iletişime geçecek.'
    elif config_undecided:
        title = 'Talebiniz Alındı'
        next_step = 'Sanatçımız talebinizi inceleyip sizinle iletişime geçecek.'
    else:
        title = 'Dövme Talebiniz Alındı'
        next_step = (
            'Talebiniz inceleniyor. Sanatçı süre belirledikten sonra '
            'randevu saati seçmeniz için size link gönderilecek.'
        )

    lines = [f'📋 *{title}*', '', f'🔖 Referans: *{reference_number}*', f'👤 Sanatçı: {staff_name}']

    if body_area and not pre_consultation:
        lines.append(f'🖋️ Bölge: {body_area}')
    if size and not (pre_consultation or config_undecided):
        lines.append(f'📏 Boyut: {size}')

    lines.extend(['', next_step])

    if loyalty_attached:
        code = loyalty_attached.get('code', '')
        pct = loyalty_attached.get('discount_percent', '')
        if code:
            lines.append('')
            lines.append(
                f'🎁 Sadakat kodunuz (*{code}*) talebe eklendi'
                + (f' — teklifte *%{pct}* indirim uygulanacak.' if pct else '.')
            )

    lines.extend(['', b['name']])
    return '\n'.join(lines)


def build_tattoo_request_staff_message(
    reference_number: str,
    customer_phone: str,
    *,
    customer_name: str | None = None,
    body_area: str | None = None,
    size: str | None = None,
    description: str | None = None,
    pre_consultation: bool = False,
    config_undecided: bool = False,
    loyalty_attached: dict | None = None,
    has_reference_image: bool = False,
) -> str:
    """Sanatçıya: yeni dövme / ön görüşme talebi."""
    b = _biz()

    if pre_consultation:
        title = 'Yeni Ön Görüşme Talebi'
    elif config_undecided:
        title = 'Yeni Dövme Talebi (Detaylar sonra)'
    else:
        title = 'Yeni Dövme Talebi'

    lines = [f'🔔 *{title}*', '', _customer_line(customer_phone, customer_name)]
    lines.extend(
        _tattoo_detail_lines(
            reference_number=reference_number,
            body_area=body_area,
            size=size if not (pre_consultation or config_undecided) else None,
            description=description,
        )
    )

    if has_reference_image:
        lines.append('🖼️ Referans görseli admin panelde mevcut')

    if loyalty_attached:
        code = loyalty_attached.get('code', '')
        pct = loyalty_attached.get('discount_percent', '')
        if code:
            lines.append(
                f'🎁 Sadakat kodu: *{code}*'
                + (f' (%{pct} indirim uygulanacak)' if pct else '')
            )

    lines.extend([
        '',
        'Admin panelden talebi inceleyip süre belirleyerek teklif gönderebilirsiniz.',
        '',
        b['name'],
    ])
    return '\n'.join(lines)


def build_appointment_created_customer_message(
    date_str: str,
    time_str: str,
    duration_minutes: int,
    price=None,
    staff_name: str | None = None,
    *,
    customer_name: str | None = None,
    reference_number: str | None = None,
    body_area: str | None = None,
    tattoo_size: str | None = None,
) -> str:
    """Müşteriye: randevu oluşturuldu."""
    b = _biz()

    lines = ['✅ *Randevunuz Oluşturuldu!*', '']
    if customer_name and str(customer_name).strip():
        lines.append(f'Sayın {customer_name.strip()},')
        lines.append('')

    tattoo_lines = _tattoo_detail_lines(
        reference_number=reference_number,
        body_area=body_area,
        size=tattoo_size,
    )
    if tattoo_lines:
        lines.extend(tattoo_lines)
        lines.append('')

    lines.extend([
        '📋 *Randevu Detayları:*',
        f'📅 Tarih: {date_str}',
        f'⏰ Saat: {time_str}',
        f'🕒 Süre: {duration_minutes} dk',
    ])
    if staff_name:
        lines.append(f'👤 Sanatçı: {staff_name}')
    price_part = _price_line(price, prefix='💰 Ücret: ')
    if price_part:
        lines.append(price_part.lstrip('\n'))

    lines.extend([
        '',
        'Randevunuzu iptal etmek veya detayları görmek için müşteri panelinizi kullanabilirsiniz.',
        '',
        _contact_footer(b),
    ])
    return '\n'.join(lines)


def build_appointment_created_staff_message(
    customer_phone: str,
    date_str: str,
    time_str: str,
    duration_minutes: int,
    price=None,
    customer_name: str | None = None,
    manual: bool = False,
    *,
    reference_number: str | None = None,
    body_area: str | None = None,
    tattoo_size: str | None = None,
    description: str | None = None,
) -> str:
    """Sanatçıya: yeni randevu bildirimi."""
    b = _biz()
    title = 'Manuel Randevu' if manual else 'Yeni Dövme Randevusu'

    lines = [
        f'🔔 *{title}!*',
        '',
        _customer_line(customer_phone, customer_name),
    ]
    lines.extend(
        _tattoo_detail_lines(
            reference_number=reference_number,
            body_area=body_area,
            size=tattoo_size,
            description=description,
        )
    )

    lines.extend([
        '',
        f'📅 Tarih: {date_str}',
        f'⏰ Saat: {time_str}',
        f'🕒 Süre: {duration_minutes} dk',
    ])
    price_part = _price_line(price, prefix='💰 Ücret: ')
    if price_part:
        lines.append(price_part.lstrip('\n'))
    lines.extend(['', b['name']])
    return '\n'.join(lines)


def build_appointment_reminder_message(
    customer_name: str,
    date_str: str,
    time_str: str,
    body_area: str,
    tattoo_size: str,
    staff_name: str,
    hours_before: float = 1,
) -> str:
    """Randevudan X saat önce hatırlatma."""
    b = _biz()
    when = '1 saat' if hours_before == 1 else f'{hours_before:g} saat'
    return f"""🔔 *Randevu Hatırlatması*

Sayın {customer_name},

Randevunuz {when} sonra başlayacak:

📅 Tarih: {date_str}
⏰ Saat: {time_str}
🎨 Bölge: {body_area} · Boyut: {tattoo_size}
👤 Sanatçı: {staff_name}

Sizi bekliyoruz!

📍 {b['name']}"""


def build_aftercare_reminder_message(customer_name: str, staff_name: str) -> str:
    """Tamamlanan randevudan sonra bakım hatırlatması."""
    b = _biz()
    contact = f'\n📞 {b["phone"]}' if b['phone'] else ''
    return f"""🧴 *Bakım Hatırlatması*

Sayın {customer_name},

Randevunuz tamamlandı. Bakım için kısa hatırlatmalar:

• Dövme bölgesine ince tabaka *nötr, kokusuz nemlendirici krem* sürün (çok kalın sürmeyin).
• Sanatçınızın önerdiği şekilde streç / örtü varsa süreye uyun.
• Bol su için; güneş, havuz ve denizden bir süre kaçının.

Sorunuz olursa yazabilirsiniz.

👤 Sanatçı: {staff_name}{contact}

{b['name']}"""


def build_appointment_confirmed_message(
    customer_name: str,
    staff_name: str,
    date_str: str,
    time_str: str,
    duration_minutes: int,
    tattoo_area: str | None = None,
    tattoo_size: str | None = None,
) -> str:
    b = _biz()
    return f"""✅ *Randevunuz Onaylandı!*

Sayın {customer_name},

📋 *Randevu Detayları:*
👤 Sanatçı: {staff_name}
📅 Tarih: {date_str}
⏰ Saat: {time_str}
🕒 Süre: {duration_minutes} dk
🖋️ Bölge: {tattoo_area or '-'}
📏 Boyut: {tattoo_size or '-'}

📍 *Adres:*
{b['address'] or '—'}

Randevunuzu iptal etmek için müşteri panelinden iptal edebilirsiniz.

_Randevunuza zamanında gelmenizi rica ederiz._

{b['name']}"""


def build_appointment_cancelled_message(
    customer_name: str,
    date_str: str,
    time_str: str,
) -> str:
    b = _biz()
    return f"""❌ *Randevunuz İptal Edildi*

Sayın {customer_name},

📅 {date_str} tarihli, ⏰ {time_str} saatli randevunuz iptal edilmiştir.

Yeni randevu almak için iletişime geçin.

📞 {b['phone'] or b['url'] or b['name']}

{b['name']}"""


def build_customer_cancel_confirmation_message(
    customer_name: str,
    staff_name: str,
    date_str: str,
    time_str: str,
    duration_minutes: int,
    tattoo_line: str = '',
    price_line: str = '',
) -> str:
    b = _biz()
    link = b['url'] or ''
    link_block = f'\n📞 *Yeni Randevu İçin:*\n{link}\n' if link else ''
    return f"""✅ *Randevu İptal Edildi*

Sayın {customer_name},

Randevunuz başarıyla iptal edilmiştir.

📋 *İptal Detayları:*
🖋️ Sanatçı: {staff_name}
📅 Tarih: {date_str}
⏰ Saat: {time_str}
🕒 Süre: {duration_minutes} dk{tattoo_line}{price_line}
{link_block}
Teşekkür ederiz,
_{b['name']}_ 🎨"""


def build_staff_cancel_notification_message(
    customer_name: str,
    customer_phone: str,
    date_str: str,
    time_str: str,
    duration_minutes: int,
    tattoo_line: str = '',
    price_line: str = '',
) -> str:
    b = _biz()
    phone_display = customer_phone if str(customer_phone).startswith('0') else f'0{customer_phone}'
    return f"""❌ *Randevu İptal Edildi*

👤 Müşteri: {customer_name}
📞 Telefon: {phone_display}
📅 Tarih: {date_str}
⏰ Saat: {time_str}
🕒 Süre: {duration_minutes} dk{tattoo_line}{price_line}

⚠️ _Müşteri tarafından iptal edildi._

{b['name']}"""


def _otp_web_origin() -> str:
    """Web OTP / klavye önerisi için site host (RANDEVU_URL)."""
    url = (_biz().get('url') or os.getenv('RANDEVU_URL') or '').strip()
    if not url:
        return ''
    if '://' not in url:
        url = f'https://{url}'
    return (urlparse(url).hostname or '').lower()


def build_verification_code_message(code) -> str:
    """Doğrulama kodu — klavye önerisi ve tek tık kopya için optimize metin."""
    code_str = str(code).strip()[:6]
    b = _biz()
    keyboard_hint = bool(get_evolution_config().get('otp_keyboard_hint_enabled', True))

    if not keyboard_hint:
        return f"""🔐 *Doğrulama Kodu*

✅ Kod: *{code_str}*

⏳ Bu kod 2 dakika boyunca geçerlidir.

🔒 Gizliliğiniz bizim için önemlidir.

Teşekkür ederiz,
_{b['name']}_"""

    origin = _otp_web_origin()
    lines = [
        f'{code_str} is your verification code.',
        f'{code_str} {b["name"]} doğrulama kodunuz. 2 dakika geçerlidir.',
        'Bu kodu kimseyle paylaşmayın.',
    ]
    if origin:
        lines.extend(['', f'@{origin} #{code_str}'])
    return '\n'.join(lines)


def get_webhook_url() -> str:
    explicit = (
        os.getenv('WHATSAPP_WEBHOOK_URL')
        or os.getenv('EVOLUTION_WEBHOOK_URL')
        or os.getenv('WAPIO_WEBHOOK_URL')
        or ''
    ).strip()
    if explicit:
        return explicit.rstrip('/')
    base = (SITE_CONFIG.get('randevu_url') or '').strip().rstrip('/')
    if base:
        return f'{base}/api/whatsapp/webhook'
    return ''


def get_reminder_hours_before() -> float:
    try:
        return max(0.25, float(os.getenv('REMINDER_HOURS_BEFORE', '1')))
    except (TypeError, ValueError):
        return 1.0


def get_webhook_cooldown_seconds() -> int:
    try:
        return max(60, int(os.getenv('WEBHOOK_COOLDOWN_SECONDS', '86400')))
    except (TypeError, ValueError):
        return 86400
