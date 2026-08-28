#!/usr/bin/env python3
"""Sanatçı başlık eşlemesi — DB/Google yok (kaynak dosyadan saf fonksiyonlar)."""
import os
import re

SYNC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'google_calendar_sync.py',
)


def _load_match_fns():
    src = open(SYNC_PATH, encoding='utf-8').read()
    start = src.index('def _fold_tr')
    end = src.index('\ndef _subscribe_calendar')
    import logging
    ns = {
        're': re,
        'logging': logging,
        'logger': logging.getLogger('gcal-match-test'),
        '_MIN_ARTIST_KEY_LEN': 3,
        '_GCAL_PHONE_RE': re.compile(r'(?<!\d)(0?5\d{9})(?!\d)'),
        '_unmatched_artist_logged': set(),
        '_UNMATCHED_LOG_CAP': 400,
    }
    exec(src[start:end], ns)
    return ns['_parse_manual_event_title'], ns['_resolve_staff_from_title']


ARTISTS = [
    (1, 'Tuncer Ürer'),
    (2, 'Mert'),
    (3, 'Nihal'),
    (4, 'Ali Onur D'),
]


def main():
    parse, resolve = _load_match_fns()

    def staff(title):
        sid, name, *_rest = parse(title, ARTISTS)
        return sid, name

    cases = [
        ('Tuncer', 1),
        ('tuncer', 1),
        ('[Tuncer Ürer]', 1),
        ('mert', 2),
        ('Mert', 2),
        ('Nihal', 3),
        ('Ali Onur D', 4),
        ('Tunxer', None),
        ('Toplantı', None),
        ('', None),
    ]
    failed = 0
    for title, expected in cases:
        sid, name = staff(title)
        ok = sid == expected
        print(('OK ' if ok else 'FAIL'), repr(title), '->', sid, name)
        if not ok:
            failed += 1

    sid, name, cust_n, cust_s, phone = parse(
        '[Tuncer Ürer] Ayşe Yılmaz 05551112233', ARTISTS
    )
    phone_ok = sid == 1 and phone == '5551112233' and bool(cust_n)
    print(('OK ' if phone_ok else 'FAIL'), 'detaylı başlık', sid, cust_n, cust_s, phone)
    if not phone_ok:
        failed += 1

    two_ali = [(10, 'Ali Veli'), (4, 'Ali Onur D')]
    sid, _name, _key = resolve('Ali', two_ali)
    amb_ok = sid is None
    print(('OK ' if amb_ok else 'FAIL'), 'belirsiz Ali ->', sid)
    if not amb_ok:
        failed += 1

    sid, _name, _key = resolve('Ali Onur D', two_ali)
    long_ok = sid == 4
    print(('OK ' if long_ok else 'FAIL'), 'uzun Ali Onur D ->', sid)
    if not long_ok:
        failed += 1

    if failed:
        print(f'{failed} test failed')
        return 1
    print('all passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
