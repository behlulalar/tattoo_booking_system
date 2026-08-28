#!/usr/bin/env python3
"""
Takvim ile veritabani arasindaki tutarsizliklari bulur (ve istenirse duzeltir).

Iki yonlu kontrol:
  1. HAYALET etkinlik  : takvimde bizim olusturdugumuz etkinlik var, DB'de randevu yok
  2. EKSIK etkinlik    : DB'de randevu var, takvimde etkinligi yok/erisilemiyor

Sadece bizim olusturdugumuz etkinlikler degerlendirilir: extendedProperties.private.origin=roof
veya aciklamadaki "Randevu ID:" satiri. Stüdyonun elle ekledigi etkinliklere dokunulmaz.

Kullanim:
    python scripts/audit_google_calendar.py                  # sadece rapor
    python scripts/audit_google_calendar.py --days 400
    python scripts/audit_google_calendar.py --fix            # kuyruga duzeltme isi ekler
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import google_calendar_sync as gcal  # noqa: E402


def _our_appointment_id(event):
    """Etkinlik bizim mi, hangi randevuya ait? Degilse None."""
    return gcal._our_appointment_id_from_event(event)


def _list_events(service, calendar_id, days_back, days_forward):
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_forward)).isoformat()
    events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            maxResults=250,
            pageToken=page_token,
        ).execute()
        events.extend(resp.get('items') or [])
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=400, help='geriye taranacak gun')
    parser.add_argument('--days-forward', type=int, default=400, help='ileriye taranacak gun')
    parser.add_argument('--fix', action='store_true', help='duzeltmeleri kuyruga ekle')
    args = parser.parse_args()

    if not gcal.is_google_calendar_enabled():
        print('Google Takvim kapali veya yapilandirilmamis.')
        return 1

    calendar_id = gcal.get_google_calendar_config()['calendar_id']
    service = gcal._get_calendar_service()
    print('takvim: %s' % calendar_id)
    print('aralik: -%s gun / +%s gun' % (args.days, args.days_forward))
    print()

    events = _list_events(service, calendar_id, args.days, args.days_forward)
    ours = {}
    foreign = 0
    for event in events:
        apt_id = _our_appointment_id(event)
        if apt_id is None:
            foreign += 1
            continue
        ours.setdefault(apt_id, []).append(event)

    print('takvimde toplam etkinlik : %s' % len(events))
    print('  bizim olusturdugumuz   : %s' % sum(len(v) for v in ours.values()))
    print('  stüdyonun kendi girdigi: %s (dokunulmaz)' % foreign)
    print()

    conn = gcal._connect()
    cursor = conn.cursor()
    cursor.execute('SELECT id, google_event_id FROM appointments')
    db_rows = cursor.fetchall()
    db_ids = {r[0] for r in db_rows}
    db_event_by_apt = {r[0]: r[1] for r in db_rows}
    calendar_event_ids = {e.get('id') for e in events}

    # 1) Hayalet etkinlikler
    ghosts = []
    for apt_id, evs in sorted(ours.items()):
        for event in evs:
            if apt_id not in db_ids:
                ghosts.append((apt_id, event))
            elif db_event_by_apt.get(apt_id) != event.get('id'):
                # DB baska bir event'e bakiyor -> bu kopya artik
                ghosts.append((apt_id, event))

    print('1) HAYALET etkinlikler (DB\'de randevu yok / baska event\'e bagli): %s' % len(ghosts))
    for apt_id, event in ghosts:
        start = (event.get('start') or {}).get('dateTime') or (event.get('start') or {}).get('date')
        print('   apt#%-6s %s  %s  event=%s' % (
            apt_id, start, (event.get('summary') or '')[:45], event.get('id')
        ))

    # 2) Eksik etkinlikler
    missing = []
    for apt_id, event_id in sorted(db_event_by_apt.items()):
        if not event_id:
            missing.append((apt_id, None))
        elif event_id not in calendar_event_ids:
            missing.append((apt_id, event_id))

    print()
    print('2) EKSIK etkinlikler (DB\'de randevu var, takvimde yok): %s' % len(missing))
    for apt_id, event_id in missing:
        cursor.execute(
            'SELECT appointment_date, appointment_time, status FROM appointments WHERE id = %s',
            (apt_id,),
        )
        row = cursor.fetchone()
        print('   apt#%-6s %s %s  %-10s event=%s' % (
            apt_id, row[0], str(row[1])[:5], row[2], event_id or '(bos)'
        ))

    if args.fix and (ghosts or missing):
        print()
        print('3) Duzeltmeler kuyruga ekleniyor')
        for _apt_id, event in ghosts:
            gcal.enqueue_event_delete(cursor, event.get('id'))
        for apt_id, _event_id in missing:
            gcal.enqueue_appointment_sync(cursor, apt_id)
        conn.commit()
        print('   %s silme + %s yeniden senkron kuyruga eklendi' % (len(ghosts), len(missing)))
        summary = gcal.drain_queue(max_items=len(ghosts) + len(missing) + 5)
        print('   tahliye: %s' % summary)
    elif ghosts or missing:
        print()
        print('Duzeltmek icin --fix ile tekrar calistirin.')
    else:
        print()
        print('Takvim ile veritabani tutarli.')

    conn.commit()
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
