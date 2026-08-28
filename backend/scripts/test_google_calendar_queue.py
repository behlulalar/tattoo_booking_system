#!/usr/bin/env python3
"""
Takvim senkron kuyrugunun (outbox) davranisini dogrular.

Gercek veriye dokunmaz: olmayan bir randevu id'si ve olmayan bir Google
etkinlik id'si kullanir, kendi ekledigi satirlari sonunda temizler.

Kullanim:
    /opt/roof_tattoo/venv/bin/python scripts/test_google_calendar_queue.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import google_calendar_sync as gcal  # noqa: E402

PASS = 'GECTI'
FAIL = 'BASARISIZ'
_results = []


def check(label, condition, detail=''):
    _results.append(bool(condition))
    mark = PASS if condition else FAIL
    print(f'  [{mark}] {label}' + (f' -> {detail}' if detail else ''))


def _one(conn, sql, params=()):
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        conn.commit()
        return row
    finally:
        cursor.close()


def _exec(conn, sql, params=()):
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()


def main():
    print('=' * 62)
    print('Google Takvim senkron kuyrugu testi')
    print('=' * 62)

    cfg = gcal.get_google_calendar_config()
    print(f"takvim: {cfg.get('calendar_id') or '(bos)'}  timezone: {cfg.get('timezone')}")
    print(f"senkron aktif: {gcal.is_google_calendar_enabled()}")
    print(f"HTTP timeout: {gcal.GCAL_HTTP_TIMEOUT}s  max deneme: {gcal.GCAL_MAX_ATTEMPTS}")
    print()

    print('1) Kuyruk tablosu ve indeksler')
    check('ensure_queue_table()', gcal.ensure_queue_table())
    conn = gcal._connect()
    try:
        check(
            'google_calendar_queue mevcut',
            _one(conn, "SELECT to_regclass('public.google_calendar_queue')")[0] is not None,
        )
        check(
            'appointments.google_event_id unique index',
            _one(
                conn,
                "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_appointments_google_event_id'",
            )
            is not None,
        )

        print()
        print('2) Olmayan randevu icin upsert -> is dusurulmeli (sonsuz denenmemeli)')
        ghost_id = _one(
            conn,
            'SELECT COALESCE(MAX(id), 0) + 100000 FROM appointments',
        )[0]
        queue_id = _one(
            conn,
            """
            INSERT INTO google_calendar_queue (operation, appointment_id)
            VALUES ('upsert', %s) RETURNING id
            """,
            (ghost_id,),
        )[0]
        summary = gcal.drain_queue(max_items=10)
        remaining = _one(
            conn, 'SELECT COUNT(*) FROM google_calendar_queue WHERE id = %s', (queue_id,)
        )[0]
        check('is kuyruktan dusuruldu', remaining == 0, f'kalan={remaining}')
        check('islenen sayaci arttı', summary['processed'] >= 1, str(summary))

        print()
        print('3) Olmayan Google etkinligi icin delete -> 404 basari sayilmali')
        bogus_event = 'roofqueuetest' + uuid.uuid4().hex[:16]
        queue_id = _one(
            conn,
            """
            INSERT INTO google_calendar_queue (operation, google_event_id)
            VALUES ('delete', %s) RETURNING id
            """,
            (bogus_event,),
        )[0]
        gcal.drain_queue(max_items=10)
        row = _one(
            conn,
            'SELECT COUNT(*), MAX(dead_at) FROM google_calendar_queue WHERE id = %s',
            (queue_id,),
        )
        check('is kuyruktan dusuruldu', row[0] == 0, f'kalan={row[0]} dead={row[1]}')

        print()
        print('4) Deneme hakki bitince is birakilmali (dead-letter)')
        queue_id = _one(
            conn,
            """
            INSERT INTO google_calendar_queue (operation, google_event_id, attempts)
            VALUES ('delete', %s, %s) RETURNING id
            """,
            ('roofqueuetest' + uuid.uuid4().hex[:16], gcal.GCAL_MAX_ATTEMPTS),
        )[0]
        became_dead = gcal._reschedule_item(
            conn, queue_id, gcal.GCAL_MAX_ATTEMPTS, 'test: kalici hata'
        )
        dead_at = _one(
            conn, 'SELECT dead_at FROM google_calendar_queue WHERE id = %s', (queue_id,)
        )[0]
        check('dead olarak isaretlendi', became_dead and dead_at is not None, str(dead_at))
        check(
            'dead is tekrar cekilmiyor',
            _one(
                conn,
                """
                SELECT COUNT(*) FROM google_calendar_queue
                 WHERE id = %s AND dead_at IS NULL AND next_attempt_at <= NOW()
                """,
                (queue_id,),
            )[0]
            == 0,
        )
        _exec(conn, 'DELETE FROM google_calendar_queue WHERE id = %s', (queue_id,))

        print()
        print('5) Tekrar deneme araligi (backoff) artiyor mu')
        queue_id = _one(
            conn,
            """
            INSERT INTO google_calendar_queue (operation, google_event_id, attempts)
            VALUES ('delete', %s, 1) RETURNING id
            """,
            ('roofqueuetest' + uuid.uuid4().hex[:16],),
        )[0]
        gcal._reschedule_item(conn, queue_id, 1, 'test: gecici hata')
        delay = _one(
            conn,
            """
            SELECT EXTRACT(EPOCH FROM (next_attempt_at - NOW()))::int
              FROM google_calendar_queue WHERE id = %s
            """,
            (queue_id,),
        )[0]
        check('1. denemeden sonra ~60s bekliyor', 50 <= delay <= 70, f'{delay}s')
        gcal._reschedule_item(conn, queue_id, 3, 'test: gecici hata')
        delay = _one(
            conn,
            """
            SELECT EXTRACT(EPOCH FROM (next_attempt_at - NOW()))::int
              FROM google_calendar_queue WHERE id = %s
            """,
            (queue_id,),
        )[0]
        check('3. denemeden sonra ~900s bekliyor', 880 <= delay <= 920, f'{delay}s')
        _exec(conn, 'DELETE FROM google_calendar_queue WHERE id = %s', (queue_id,))

        print()
        print('6) Bayat event_id tespiti')

        class _Resp:
            def __init__(self, status):
                self.status = status

        class _Err(Exception):
            def __init__(self, status):
                self.resp = _Resp(status)
                super().__init__(f'HTTP {status}')

        check('404 -> bayat', gcal._is_missing_event_error(_Err(404)))
        check('410 -> bayat', gcal._is_missing_event_error(_Err(410)))
        check('403 -> bayat degil (yetki)', not gcal._is_missing_event_error(_Err(403)))
        check('500 -> bayat degil (gecici)', not gcal._is_missing_event_error(_Err(500)))

        print()
        print('7) Kuyruk ozeti')
        stats = gcal.queue_stats()
        print(f'  bekleyen={stats["pending"]} birakilan={stats["dead"]} en_eski={stats["oldest_pending"]}')
        check('ozet okunabiliyor', stats['pending'] is not None)
        check('test artigi kalmadi', (stats['pending'] or 0) == 0, str(stats))
    finally:
        gcal._disconnect(conn)

    print()
    print('=' * 62)
    failed = _results.count(False)
    print(f'{len(_results) - failed}/{len(_results)} kontrol gecti')
    print('=' * 62)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
