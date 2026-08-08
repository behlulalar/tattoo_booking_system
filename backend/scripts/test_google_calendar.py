#!/usr/bin/env python3
"""Google Calendar Faz 1 teşhis + isteğe bağlı randevu senkronu.

Kullanım (sunucuda):
  cd /opt/roof_tattoo/backend
  ../venv/bin/python scripts/test_google_calendar.py
  ../venv/bin/python scripts/test_google_calendar.py --sync 42
"""
import argparse
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv

load_dotenv(os.path.join(_BACKEND, '.env'))

from config import GOOGLE_CALENDAR_CONFIG
from google_calendar_sync import is_google_calendar_enabled, sync_appointment_to_google


def main():
    parser = argparse.ArgumentParser(description='Google Calendar bağlantı testi')
    parser.add_argument('--sync', type=int, metavar='APPOINTMENT_ID', help='Belirli randevuyu Calendar\'a gönder')
    args = parser.parse_args()

    print('=== Google Calendar config ===')
    print(f"  enabled env     : {GOOGLE_CALENDAR_CONFIG.get('enabled')}")
    print(f"  calendar_id     : {GOOGLE_CALENDAR_CONFIG.get('calendar_id') or '(BOŞ)'}")
    print(f"  credentials_path: {GOOGLE_CALENDAR_CONFIG.get('credentials_path')}")
    cred = GOOGLE_CALENDAR_CONFIG.get('credentials_path')
    print(f"  credentials ok  : {os.path.isfile(cred) if cred else False}")
    print(f"  timezone        : {GOOGLE_CALENDAR_CONFIG.get('timezone')}")
    print(f"  is_enabled()    : {is_google_calendar_enabled()}")

    if not is_google_calendar_enabled():
        print('\n❌ Calendar senkronu KAPALI veya eksik ayar. .env kontrol edin:')
        print('   GOOGLE_CALENDAR_ENABLED=true')
        print('   GOOGLE_CALENDAR_ID=...@group.calendar.google.com')
        print('   GOOGLE_CALENDAR_CREDENTIALS_PATH=/opt/roof_tattoo/backend/credentials/google-calendar.json')
        sys.exit(1)

    try:
        from google_calendar_sync import _get_calendar_service
        service = _get_calendar_service()
        cal = service.calendars().get(calendarId=GOOGLE_CALENDAR_CONFIG['calendar_id']).execute()
        print(f"\n✅ Takvim erişimi OK: {cal.get('summary', '?')}")
    except Exception as e:
        print(f'\n❌ Takvim API hatası: {e}')
        print('   Takvimi service account ile paylaştınız mı?')
        print('   tattoo-calendar@tattoo-studios-498419.iam.gserviceaccount.com → Etkinlikleri değiştir')
        sys.exit(1)

    if args.sync:
        print(f'\n--- Randevu #{args.sync} senkron ediliyor ---')
        event_id = sync_appointment_to_google(args.sync)
        if event_id:
            print(f'✅ google_event_id: {event_id}')
        else:
            print('❌ Senkron başarısız — app.log veya journalctl kontrol edin')
            sys.exit(1)


if __name__ == '__main__':
    main()
