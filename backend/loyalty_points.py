"""
Müşteri sadakat puanı: tamamlanan randevularda puan kazanma, 5. dövme indirimi.
"""
import logging
import secrets
from datetime import datetime, timedelta

import psycopg2

from config import LOYALTY_CONFIG

logger = logging.getLogger(__name__)


class LoyaltyCodeError(Exception):
    """Geçersiz veya kullanılamaz sadakat indirim kodu."""


def _points_per_completion():
    return max(1, int(LOYALTY_CONFIG.get('points_per_completion', 100)))


def _milestone_completions():
    return max(1, int(LOYALTY_CONFIG.get('milestone_completions', 5)))


def _redeem_points_cost():
    return max(1, int(LOYALTY_CONFIG.get('redeem_points_cost', 500)))


def _discount_percent():
    return max(1, min(50, int(LOYALTY_CONFIG.get('discount_percent', 10))))


def _redemption_valid_days():
    return max(7, int(LOYALTY_CONFIG.get('redemption_valid_days', 90)))


def _count_completed_appointments(cursor, customer_id):
    cursor.execute(
        """
        SELECT COUNT(*) FROM appointments
        WHERE customer_id = %s AND status = 'completed'
        """,
        (customer_id,),
    )
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def _count_loyalty_earns(cursor, customer_id):
    """Puan kazanılmış tamamlanan randevu sayısı (bakiye ile senkron)."""
    cursor.execute(
        """
        SELECT COUNT(*) FROM loyalty_transactions
        WHERE customer_id = %s AND transaction_type = 'earn'
        """,
        (customer_id,),
    )
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def sync_missing_loyalty_points(cursor, customer_id):
    """Tamamlanmış ama puanı yazılmamış randevuları senkronize et."""
    if not LOYALTY_CONFIG.get('enabled'):
        return 0
    cursor.execute(
        """
        SELECT a.id FROM appointments a
        WHERE a.customer_id = %s AND a.status = 'completed'
          AND NOT EXISTS (
            SELECT 1 FROM loyalty_transactions lt
            WHERE lt.appointment_id = a.id AND lt.transaction_type = 'earn'
          )
        ORDER BY a.id
        """,
        (customer_id,),
    )
    awarded = 0
    for (apt_id,) in cursor.fetchall():
        if award_loyalty_on_completion(cursor, customer_id, apt_id):
            awarded += 1
    return awarded


def _get_customer_balance(cursor, customer_id):
    cursor.execute(
        'SELECT COALESCE(loyalty_points, 0) FROM customers WHERE id = %s',
        (customer_id,),
    )
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def _has_active_redemption(cursor, customer_id):
    cursor.execute(
        """
        SELECT id, redemption_code, discount_percent, expires_at
        FROM loyalty_redemptions
        WHERE customer_id = %s
          AND used_at IS NULL
          AND expires_at > NOW()
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (customer_id,),
    )
    return cursor.fetchone()


def award_loyalty_on_completion(cursor, customer_id, appointment_id):
    """Randevu tamamlandığında puan ver (aynı randevu için tekrar vermez)."""
    if not LOYALTY_CONFIG.get('enabled'):
        return 0

    points = _points_per_completion()
    cursor.execute(
        """
        SELECT 1 FROM loyalty_transactions
        WHERE appointment_id = %s AND transaction_type = 'earn'
        LIMIT 1
        """,
        (appointment_id,),
    )
    if cursor.fetchone():
        logger.info('Sadakat puanı zaten verilmiş: randevu #%s', appointment_id)
        return 0

    cursor.execute(
        """
        UPDATE customers
        SET loyalty_points = COALESCE(loyalty_points, 0) + %s
        WHERE id = %s
        RETURNING loyalty_points
        """,
        (points, customer_id),
    )
    row = cursor.fetchone()
    if not row:
        logger.warning('Sadakat puanı: müşteri #%s bulunamadı', customer_id)
        return 0

    balance_after = int(row[0])
    cursor.execute(
        """
        INSERT INTO loyalty_transactions (
            customer_id, appointment_id, points_delta, balance_after,
            transaction_type, description
        )
        VALUES (%s, %s, %s, %s, 'earn', %s)
        """,
        (
            customer_id,
            appointment_id,
            points,
            balance_after,
            f'Randevu #{appointment_id} tamamlandı (+{points} puan)',
        ),
    )
    logger.info(
        'Sadakat puanı verildi: müşteri #%s, randevu #%s, +%s (bakiye: %s)',
        customer_id, appointment_id, points, balance_after,
    )
    return points


def build_loyalty_summary(cursor, customer_id, *, sync_missing=True):
    """Müşteri paneli için sadakat özeti."""
    if sync_missing:
        sync_missing_loyalty_points(cursor, customer_id)

    balance = _get_customer_balance(cursor, customer_id)
    ppc = _points_per_completion()
    earned_completions = _count_loyalty_earns(cursor, customer_id)
    completed_total = _count_completed_appointments(cursor, customer_id)
    # Gösterim: puan kazanılan dövme sayısı (bakiye = earned * ppc, indirim harici)
    progress_completions = earned_completions
    milestone = _milestone_completions()
    redeem_cost = _redeem_points_cost()
    discount = _discount_percent()

    points_until_redeem = max(0, redeem_cost - balance)
    completions_until_milestone = max(0, milestone - progress_completions)

    active = _has_active_redemption(cursor, customer_id)
    active_redemption = None
    if active:
        active_redemption = {
            'code': active[1],
            'discount_percent': int(active[2]),
            'expires_at': active[3].strftime('%d.%m.%Y') if active[3] else None,
        }

    can_redeem = (
        progress_completions >= milestone
        and balance >= redeem_cost
        and active_redemption is None
    )

    cursor.execute(
        """
        SELECT points_delta, balance_after, transaction_type, description, created_at
        FROM loyalty_transactions
        WHERE customer_id = %s
        ORDER BY created_at DESC
        LIMIT 15
        """,
        (customer_id,),
    )
    history = []
    for row in cursor.fetchall():
        history.append({
            'points_delta': int(row[0]),
            'balance_after': int(row[1]),
            'type': row[2],
            'description': row[3] or '',
            'created_at': row[4].strftime('%d.%m.%Y %H:%M') if row[4] else None,
        })

    return {
        'balance': balance,
        'completed_tattoos': progress_completions,
        'completed_total': completed_total,
        'milestone_completions': milestone,
        'points_per_completion': ppc,
        'redeem_points_cost': redeem_cost,
        'discount_percent': discount,
        'points_until_redeem': points_until_redeem,
        'completions_until_milestone': completions_until_milestone,
        'can_redeem': can_redeem,
        'active_redemption': active_redemption,
        'history': history,
    }


def redeem_loyalty_discount(cursor, customer_id):
    """5+ tamamlanan dövme ve yeterli puan varsa indirim kodu oluştur."""
    if not LOYALTY_CONFIG.get('enabled'):
        return None, 'Sadakat programı şu an kapalı'

    summary = build_loyalty_summary(cursor, customer_id)
    if summary['active_redemption']:
        return summary['active_redemption'], None
    if summary['completed_tattoos'] < summary['milestone_completions']:
        need = summary['completions_until_milestone']
        return None, f'İndirim için {need} dövme daha tamamlamanız gerekiyor'
    if summary['balance'] < summary['redeem_points_cost']:
        need_pts = summary['points_until_redeem']
        return None, f'İndirim için {need_pts} puan daha kazanmanız gerekiyor'

    cost = summary['redeem_points_cost']
    discount = summary['discount_percent']
    code = f"LOYAL-{secrets.token_hex(3).upper()}"

    cursor.execute(
        """
        UPDATE customers
        SET loyalty_points = loyalty_points - %s
        WHERE id = %s AND loyalty_points >= %s
        RETURNING loyalty_points
        """,
        (cost, customer_id, cost),
    )
    row = cursor.fetchone()
    if not row:
        return None, 'Yeterli puanınız yok'

    balance_after = int(row[0])
    expires_at = datetime.utcnow() + timedelta(days=_redemption_valid_days())

    cursor.execute(
        """
        INSERT INTO loyalty_transactions (
            customer_id, points_delta, balance_after, transaction_type, description
        )
        VALUES (%s, %s, %s, 'redeem', %s)
        """,
        (
            customer_id,
            -cost,
            balance_after,
            f'%{discount} indirim kodu oluşturuldu ({code})',
        ),
    )
    cursor.execute(
        """
        INSERT INTO loyalty_redemptions (
            customer_id, redemption_code, discount_percent, points_spent, expires_at
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING redemption_code, discount_percent, expires_at
        """,
        (customer_id, code, discount, cost, expires_at),
    )
    redemption = cursor.fetchone()
    logger.info(
        'Sadakat indirimi oluşturuldu: müşteri #%s, kod=%s, -%s puan',
        customer_id, code, cost,
    )
    return {
        'code': redemption[0],
        'discount_percent': int(redemption[1]),
        'expires_at': redemption[2].strftime('%d.%m.%Y') if redemption[2] else None,
    }, None


def _normalize_loyalty_code(code):
    return (code or '').strip().upper()


def apply_percent_discount(price, discount_percent):
    """Liste fiyatından indirimli fiyat hesapla."""
    original = float(price or 0)
    if original <= 0:
        return 0.0, 0.0, 0
    pct = max(1, min(50, int(discount_percent or 0)))
    final = round(original * (1 - pct / 100), 2)
    saved = round(original - final, 2)
    return final, original, pct


def _fetch_redemption_by_code(cursor, code):
    cursor.execute(
        """
        SELECT id, customer_id, redemption_code, discount_percent, used_at, expires_at
        FROM loyalty_redemptions
        WHERE UPPER(redemption_code) = %s
        LIMIT 1
        """,
        (_normalize_loyalty_code(code),),
    )
    return cursor.fetchone()


def attach_loyalty_code_to_request(cursor, customer_id, tattoo_request_id, code):
    """
    Müşteri talebine tek kullanımlık indirim kodu bağla.
    Returns: (redemption_id, code, discount_percent)
    """
    if not LOYALTY_CONFIG.get('enabled'):
        raise LoyaltyCodeError('Sadakat programı şu an kapalı')

    normalized = _normalize_loyalty_code(code)
    if not normalized:
        raise LoyaltyCodeError('İndirim kodu girin')

    row = _fetch_redemption_by_code(cursor, normalized)
    if not row:
        raise LoyaltyCodeError('İndirim kodu bulunamadı')

    redemption_id, owner_id, redemption_code, discount_percent, used_at, expires_at = row

    if int(owner_id) != int(customer_id):
        raise LoyaltyCodeError('Bu indirim kodu size ait değil')
    if used_at is not None:
        raise LoyaltyCodeError('Bu indirim kodu zaten kullanılmış')
    if expires_at and expires_at < datetime.utcnow():
        raise LoyaltyCodeError('Bu indirim kodunun süresi dolmuş')

    cursor.execute(
        """
        SELECT tr.id FROM tattoo_requests tr
        WHERE tr.loyalty_redemption_id = %s
          AND tr.status IN ('new', 'offered')
          AND tr.id != %s
        LIMIT 1
        """,
        (redemption_id, tattoo_request_id),
    )
    if cursor.fetchone():
        raise LoyaltyCodeError('Bu kod başka bir aktif talepte kullanılıyor')

    try:
        cursor.execute(
            """
            UPDATE tattoo_requests
            SET loyalty_redemption_id = %s,
                loyalty_discount_code = %s,
                loyalty_discount_percent = %s
            WHERE id = %s
            """,
            (redemption_id, redemption_code, int(discount_percent), tattoo_request_id),
        )
        cursor.execute(
            """
            UPDATE loyalty_redemptions
            SET tattoo_request_id = %s
            WHERE id = %s
            """,
            (tattoo_request_id, redemption_id),
        )
    except psycopg2.Error as db_err:
        err_s = str(db_err).lower()
        if 'loyalty_redemption_id' in err_s or 'loyalty_discount_code' in err_s:
            raise LoyaltyCodeError(
                'Sadakat kodu sistemi sunucuda eksik. Migration çalıştırılmalı.'
            ) from db_err
        raise

    logger.info(
        'Sadakat kodu talebe bağlandı: request #%s, kod=%s',
        tattoo_request_id, redemption_code,
    )
    return redemption_id, redemption_code, int(discount_percent)


def validate_loyalty_code_for_customer(cursor, customer_id, code):
    """Kod geçerli mi (talep öncesi doğrulama)."""
    normalized = _normalize_loyalty_code(code)
    if not normalized:
        raise LoyaltyCodeError('İndirim kodu girin')
    row = _fetch_redemption_by_code(cursor, normalized)
    if not row:
        raise LoyaltyCodeError('İndirim kodu bulunamadı')
    redemption_id, owner_id, redemption_code, discount_percent, used_at, expires_at = row
    if int(owner_id) != int(customer_id):
        raise LoyaltyCodeError('Bu indirim kodu size ait değil')
    if used_at is not None:
        raise LoyaltyCodeError('Bu indirim kodu zaten kullanılmış')
    if expires_at and expires_at < datetime.utcnow():
        raise LoyaltyCodeError('Bu indirim kodunun süresi dolmuş')
    cursor.execute(
        """
        SELECT tr.id FROM tattoo_requests tr
        WHERE tr.loyalty_redemption_id = %s
          AND tr.status IN ('new', 'offered')
        LIMIT 1
        """,
        (redemption_id,),
    )
    if cursor.fetchone():
        raise LoyaltyCodeError('Bu kod başka bir aktif talepte kullanılıyor')
    return {
        'code': redemption_code,
        'discount_percent': int(discount_percent),
    }


def get_request_loyalty_discount(cursor, tattoo_request_id):
    """Talebe bağlı aktif indirim kodu bilgisi."""
    cursor.execute(
        """
        SELECT
            lr.id,
            COALESCE(tr.loyalty_discount_code, lr.redemption_code),
            COALESCE(tr.loyalty_discount_percent, lr.discount_percent),
            lr.used_at
        FROM tattoo_requests tr
        LEFT JOIN loyalty_redemptions lr ON tr.loyalty_redemption_id = lr.id
        WHERE tr.id = %s
          AND (tr.loyalty_redemption_id IS NOT NULL OR tr.loyalty_discount_code IS NOT NULL)
        """,
        (tattoo_request_id,),
    )
    row = cursor.fetchone()
    if not row or not row[1]:
        return None

    redemption_id = row[0]
    code = row[1]
    discount_percent = int(row[2] or 10)
    used_at = row[3]

    if redemption_id is None and code:
        fallback = _fetch_redemption_by_code(cursor, code)
        if fallback:
            redemption_id = fallback[0]
            used_at = fallback[4]

    return {
        'redemption_id': redemption_id,
        'code': code,
        'discount_percent': discount_percent,
        'used_at': used_at,
    }


def mark_redemption_used_for_offer(cursor, redemption_id, tattoo_request_id):
    """Teklif gönderilince kodu tek kullanımlık olarak kapat."""
    cursor.execute(
        """
        UPDATE loyalty_redemptions
        SET used_at = CURRENT_TIMESTAMP, tattoo_request_id = %s
        WHERE id = %s AND used_at IS NULL
        RETURNING redemption_code
        """,
        (tattoo_request_id, redemption_id),
    )
    row = cursor.fetchone()
    if row:
        logger.info('Sadakat kodu kullanıldı: %s (talep #%s)', row[0], tattoo_request_id)
    return row[0] if row else None
