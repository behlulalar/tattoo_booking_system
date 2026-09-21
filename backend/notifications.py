"""
Panel Ici Bildirim Yardimcisi
Roof Tattoo Gallery - Randevu Sistemi

Sistemin kendi kendine yaptigi ama admin/sanatcinin fark etmeyebilecegi
degisiklikleri (ör. Google Calendar'da mesai/cakisma nedeniyle geri
alinan bir surukleme) panel icinde gorunur kilmak icin kucuk bir
bildirim kaydi. Baglanti yonetimi burada yok, cagiran taraf (app.py,
google_calendar_sync.py) zaten acik olan cursor'u geciriyor —
loyalty_points.py ile ayni desen.
"""

import logging

logger = logging.getLogger(__name__)


def create_notification(cursor, staff_id, notif_type, title, message, appointment_id=None):
    """Tek bir bildirim kaydi olusturur. Hata olursa sessizce loglar,
    cagiran taraftaki asil islemi (ör. Google Calendar senkronu) bozmaz.
    """
    if not staff_id:
        return
    try:
        cursor.execute(
            """
            INSERT INTO notifications (staff_id, type, title, message, appointment_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (int(staff_id), notif_type, title, message, appointment_id),
        )
    except Exception as e:
        logger.error(f"create_notification hatasi: {e}")
