#!/usr/bin/env python3
"""google_event_id olmayan randevuları Google Calendar'a gönderir.

Kullanım (sunucuda, .env ve credentials düzeltildikten sonra):
  cd /opt/roof_tattoo/backend
  ../venv/bin/python scripts/backfill_google_calendar.py
  ../venv/bin/python scripts/backfill_google_calendar.py --limit 50
  ../venv/bin/python scripts/backfill_google_calendar.py --refresh-colors
"""
import argparse
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv

load_dotenv(os.path.join(_BACKEND, '.env'))

import psycopg2

from config import DATABASE_CONFIG
from google_calendar_sync import is_google_calendar_enabled, refresh_google_event_colors, sync_appointment_to_google


def _connect():
    cfg = dict(DATABASE_CONFIG)
    sslmode = cfg.pop('sslmode', None)
    if sslmode:
        cfg['sslmode'] = sslmode
    return psycopg2.connect(**cfg)


def main():
    parser = argparse.ArgumentParser(description='Eksik Google Calendar senkronu')
    parser.add_argument('--limit', type=int, default=200, help='En fazla kaç randevu')
    parser.add_argument(
        '--refresh-colors',
        action='store_true',
        help='Mevcut Google etkinliklerini sanatçı rengiyle yeniden güncelle',
    )
    args = parser.parse_args()

    if not is_google_calendar_enabled():
        print('❌ Google Calendar kapalı veya eksik ayar (.env + credentials)')
        sys.exit(1)

    if args.refresh_colors:
        result = refresh_google_event_colors(limit=args.limit)
        if not result.get('ok'):
            print('❌ Renk güncellenemedi:', result.get('reason') or result.get('error') or 'hata')
            sys.exit(1)
        print(
            f"Renk güncellendi: {result.get('updated', 0)} başarılı, "
            f"{result.get('failed', 0)} başarısız, toplam {result.get('total', 0)}"
        )
        return

    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM appointments
        WHERE google_event_id IS NULL
          AND status NOT IN ('cancelled')
        ORDER BY appointment_date DESC, id DESC
        LIMIT %s
        """,
        (args.limit,),
    )
    ids = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    if not ids:
        print('✅ Senkron bekleyen randevu yok.')
        return

    print(f'{len(ids)} randevu senkron edilecek...')
    ok = 0
    fail = 0
    for apt_id in ids:
        event_id = sync_appointment_to_google(apt_id)
        if event_id:
            ok += 1
            print(f'  ✅ #{apt_id} → {event_id}')
        else:
            fail += 1
            print(f'  ❌ #{apt_id}')

    print(f'\nBitti: {ok} başarılı, {fail} başarısız')


if __name__ == '__main__':
    main()
