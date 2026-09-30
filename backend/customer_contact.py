"""Müşteri iletişim bilgisi yardımcıları: telefonu olmayan müşteri + Instagram adı.

Flask/DB bağımlılığı yok. customers.phone zorunlu ve benzersiz olduğundan telefonu
olmayan müşteriye teknik bir "yer tutucu" numara verilir: 10 hane ve '1' ile
başlar (gerçek TR cep numarası 5 ile başlar). Bu numara hiçbir yerde gösterilmez
ve ona asla WhatsApp mesajı gönderilmez; müşteri Instagram adıyla tanınır.
"""

import hashlib
import re
import uuid

NO_PHONE_LABEL = 'Tel no yok'

_INSTAGRAM_RE = re.compile(r'^[a-z0-9._]{1,30}$')
# Başlıkta "@kullanici" (e-posta değil: öncesinde harf/rakam olmamalı).
INSTAGRAM_IN_TEXT_RE = re.compile(r'(?<![\w.])@([A-Za-z0-9._]{1,30})(?![\w@])')


def is_placeholder_phone(phone):
    """Yer tutucu (gerçek olmayan) numara mı: 10 hane, '1' ile başlar."""
    raw = str(phone or '')
    if '@' in raw:  # WhatsApp kimlikleri (@lid / @c.us) gerçek sayılır
        return False
    digits = ''.join(ch for ch in raw if ch.isdigit())
    return len(digits) == 10 and digits.startswith('1')


def make_placeholder_phone(seed=None):
    """Yer tutucu numara üretir; seed verilirse aynı seed aynı numarayı verir."""
    seed = seed or uuid.uuid4().hex
    digest = hashlib.sha256(str(seed).encode('utf-8')).hexdigest()
    return ('1' + ''.join(ch for ch in digest if ch.isdigit()))[:10].ljust(10, '0')


def normalize_instagram(value):
    """'@Kullanici' / 'instagram.com/kullanici' -> 'kullanici'. Boş -> None; geçersiz -> ValueError."""
    raw = str(value or '').strip()
    if not raw:
        return None
    raw = re.sub(r'^(?:https?://)?(?:www\.)?instagram\.com/', '', raw, flags=re.I)
    raw = raw.split('?')[0].strip('/').lstrip('@').lower()
    if not _INSTAGRAM_RE.match(raw):
        raise ValueError('Geçersiz Instagram kullanıcı adı (harf, rakam, nokta ve alt çizgi)')
    return raw


def extract_instagram(text):
    """Metindeki ilk @kullanici'yı döndürür: (kullanici_adi | None, @'siz metin)."""
    match = INSTAGRAM_IN_TEXT_RE.search(text or '')
    if not match:
        return None, text
    cleaned = (text[:match.start()] + ' ' + text[match.end():])
    return match.group(1).lower(), ' '.join(cleaned.split())


def contact_label(phone, instagram=None, display_phone=None):
    """Panelde/mesajda gösterilecek iletişim: gerçek telefon, yoksa @instagram, yoksa 'Tel no yok'."""
    if phone and not is_placeholder_phone(phone):
        return display_phone(phone) if display_phone else str(phone)
    if instagram:
        return f'@{instagram}'
    return NO_PHONE_LABEL
