"""Google Takvim ice aktarma ONIZLEMESI — takvime ve veritabanina KALICI HICBIR SEY yazmaz.

Takvimdeki etkinlikleri (ilk aktarim penceresi: Ekim) okur, gercek ice aktarma
mantigini bir transaction icinde calistirir, sonucu raporlar ve transaction'i
GERI ALIR. Google'a yazma (damga/renk), bildirim ve e-posta devre disi birakilir.

Kullanim (sunucuda, backend dizininde):
    ../venv/bin/python scripts/gcal_import_preview.py <takvim_id>
"""
import os
import sys
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

import google_calendar_sync as gcs  # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit('Kullanim: gcal_import_preview.py <takvim_id>')
    calendar_id = sys.argv[1]

    tz = gcs._studio_tz()
    now = datetime.now(tz)
    window = gcs._initial_import_window(now, tz)
    if not window:
        sys.exit('Ilk aktarim penceresi kapali (bitis tarihi gecti).')
    time_min, time_max = window

    service = gcs._get_calendar_service()
    events, page = [], None
    while True:
        resp = service.events().list(
            calendarId=calendar_id, timeMin=time_min.isoformat(), timeMax=time_max.isoformat(),
            singleEvents=True, showDeleted=False, maxResults=250, pageToken=page,
            fields='items(id,status,transparency,start,end,etag,summary,extendedProperties,description,recurringEventId),nextPageToken',
        ).execute()
        events.extend(resp.get('items') or [])
        page = resp.get('nextPageToken')
        if not page:
            break
    print(f'Pencere: {time_min.date()} .. {(time_max - timedelta(days=1)).date()} | okunan etkinlik: {len(events)}')

    conn = gcs._connect()
    conn.autocommit = False
    cursor = conn.cursor()
    counts, rows = Counter(), []
    # Google'a yazma / bildirim / e-posta yok.
    gcs._stamp_origin_on_event = lambda *a, **k: None
    gcs._stamp_origin_on_off_day_event = lambda *a, **k: None
    gcs._notify_import_conflict = lambda *a, **k: None
    gcs.log_error = lambda *a, **k: None
    try:
        for ev in sorted(events, key=lambda e: (e.get('start') or {}).get('dateTime') or (e.get('start') or {}).get('date') or ''):
            title = (ev.get('summary') or '').strip()
            start = (ev.get('start') or {}).get('dateTime') or (ev.get('start') or {}).get('date') or '?'
            if gcs._is_our_event(ev):
                action = 'sistemin kendi etkinligi'
            else:
                action = gcs._import_manual_google_event(cursor, ev, calendar_id, [], [])
            counts[action] += 1
            rows.append((start[:16], action, title[:60]))
        cursor.execute(
            """SELECT a.appointment_date, a.appointment_time, s.name, c.name, c.surname, c.instagram,
                      c.phone !~ '^1[0-9]{9}$' AS has_phone, a.duration_minutes
                 FROM appointments a JOIN artists s ON s.id=a.staff_id JOIN customers c ON c.id=a.customer_id
                WHERE a.source='google' AND a.created_at >= NOW() - INTERVAL '5 minutes'
                ORDER BY a.appointment_date, a.appointment_time"""
        )
        apts = cursor.fetchall()
        cursor.execute("SELECT off_date, start_time, end_time, staff_id, reason FROM time_off WHERE created_at >= NOW() - INTERVAL '5 minutes' ORDER BY off_date")
        offs = cursor.fetchall()
    finally:
        conn.rollback()  # HICBIR SEY KALICI DEGIL
        conn.close()

    print('\n--- Etkinlik bazinda sonuc ---')
    for start, action, title in rows:
        print(f'{start:16}  {action:22}  {title}')
    print('\n--- Ozet ---')
    for k, v in counts.most_common():
        print(f'{k:24} {v}')
    print('\n--- Randevu olacaklar (onizleme) ---')
    for d, t, staff, n, sn, ig, has_phone, dur in apts:
        contact = 'tel var' if has_phone else (f'@{ig}' if ig else 'Tel no yok')
        print(f'{d} {str(t)[:5]}  {dur:>3} dk  {staff:<16} {n} {sn}  [{contact}]')
    print('\n--- Izin olacaklar (onizleme) ---')
    for d, st, et, sid, reason in offs:
        print(f'{d} {st or "tum gun"}-{et or ""}  personel#{sid}  {reason or ""}')
    print('\nNOT: Bu bir onizlemedir; veritabani degisikligi geri alindi, takvime yazilmadi.')


if __name__ == '__main__':
    main()
