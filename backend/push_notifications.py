"""
PWA Push Bildirimleri (Web Push / VAPID)
Roof Tattoo Gallery - Randevu Sistemi

Personel admin panelini PWA olarak ana ekrana ekleyip bildirimlere izin
verdiginde, tarayicidan alinan abonelik (endpoint + sifreleme anahtarlari)
push_subscriptions tablosunda saklanir. Bu modul o abonelige gercek push
mesaji gondermekten sorumlu.

Baglanti yonetimi burada yok — app.py acilisinda set_db_accessors ile
get_db_connection/release_db_connection enjekte edilir (dongusel import
onlemek icin, google_calendar_sync.py'deki set_cancel_notifier deseniyle
ayni mantik).
"""

import json
import logging
import os

from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

_get_db_connection = None
_release_db_connection = None


def set_db_accessors(get_conn_fn, release_conn_fn):
    global _get_db_connection, _release_db_connection
    _get_db_connection = get_conn_fn
    _release_db_connection = release_conn_fn


def get_vapid_public_key():
    return (os.getenv('VAPID_PUBLIC_KEY') or '').strip()


def _vapid_private_key():
    return (os.getenv('VAPID_PRIVATE_KEY') or '').strip()


def _vapid_claims():
    subject = (os.getenv('VAPID_SUBJECT') or '').strip()
    return {'sub': subject or 'mailto:info@example.com'}


def push_enabled():
    return bool(get_vapid_public_key() and _vapid_private_key())


def save_subscription(cursor, staff_id, endpoint, p256dh, auth, user_agent=None):
    """Abonelik kaydi olustur/gunceller (ayni endpoint tekrar gelirse ustune yazar)."""
    cursor.execute(
        """
        INSERT INTO push_subscriptions (staff_id, endpoint, p256dh, auth, user_agent)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (endpoint) DO UPDATE
           SET staff_id = EXCLUDED.staff_id,
               p256dh = EXCLUDED.p256dh,
               auth = EXCLUDED.auth,
               user_agent = EXCLUDED.user_agent,
               last_used_at = NULL
        """,
        (int(staff_id), endpoint, p256dh, auth, user_agent),
    )


def remove_subscription(cursor, endpoint):
    cursor.execute('DELETE FROM push_subscriptions WHERE endpoint = %s', (endpoint,))


def push_to_role(role, title, body, url=None):
    """Belirli bir role sahip TUM personelin abone cihazlarina push gonderir.

    Ör. kritik sistem uyarilari (WhatsApp/Google Takvim baglantisi kopunca)
    icin role='super_admin'.
    """
    if not push_enabled():
        return
    if _get_db_connection is None:
        logger.warning('push_to_role: db accessors henuz set edilmedi')
        return

    conn = None
    staff_ids = []
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM artists WHERE role = %s', (role,))
        staff_ids = [r[0] for r in cursor.fetchall() or []]
        cursor.close()
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning(f"push_to_role: personel okunamadi: {e}")
        return
    finally:
        _release_db_connection(conn)

    for staff_id in staff_ids:
        push_to_staff(staff_id, title, body, url=url)


def push_to_staff(staff_id, title, body, url=None):
    """Bir personelin TUM abone cihazlarina push bildirimi gonderir.

    Kendi DB baglantisini acar (arka plan thread'inden cagrildigi icin
    disaridan cursor alamaz). Gecersiz/suresi dolmus abonelikler (404/410)
    sessizce tablodan silinir. push_enabled() False ise (VAPID anahtari
    yoksa) hicbir sey yapmaz.
    """
    if not push_enabled() or not staff_id:
        return
    if _get_db_connection is None:
        logger.warning('push_to_staff: db accessors henuz set edilmedi')
        return

    conn = None
    rows = []
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE staff_id = %s',
            (int(staff_id),),
        )
        rows = cursor.fetchall() or []
        cursor.close()
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning(f"push_to_staff: abonelikler okunamadi: {e}")
        return
    finally:
        _release_db_connection(conn)

    if not rows:
        return

    payload = json.dumps({'title': title, 'body': body, 'url': url or '/sp-admin-x7k.html'})
    stale_ids = []
    for sub_id, endpoint, p256dh, auth in rows:
        try:
            webpush(
                subscription_info={
                    'endpoint': endpoint,
                    'keys': {'p256dh': p256dh, 'auth': auth},
                },
                data=payload,
                vapid_private_key=_vapid_private_key(),
                vapid_claims=dict(_vapid_claims()),
            )
        except WebPushException as exc:
            status = getattr(exc.response, 'status_code', None)
            if status in (404, 410):
                stale_ids.append(sub_id)
            else:
                logger.warning(f"push_to_staff gonderim hatasi (id={sub_id}): {exc}")
        except Exception as exc:
            logger.warning(f"push_to_staff beklenmeyen hata (id={sub_id}): {exc}")

    if stale_ids:
        conn = None
        try:
            conn = _get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM push_subscriptions WHERE id = ANY(%s)', (stale_ids,)
            )
            conn.commit()
            cursor.close()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.warning(f"push_to_staff: gecersiz abonelikler silinemedi: {e}")
        finally:
            _release_db_connection(conn)
