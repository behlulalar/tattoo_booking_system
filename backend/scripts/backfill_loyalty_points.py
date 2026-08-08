#!/usr/bin/env python3
"""Tamamlanmış randevular için geriye dönük sadakat puanı (henüz verilmemiş olanlar).

Kullanım:
  cd /opt/roof_tattoo/backend
  ../venv/bin/python scripts/backfill_loyalty_points.py
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv

load_dotenv(os.path.join(_BACKEND, '.env'))

import psycopg2
from config import DATABASE_CONFIG
from loyalty_points import award_loyalty_on_completion


def main():
    conn = psycopg2.connect(
        host=DATABASE_CONFIG['host'],
        port=DATABASE_CONFIG['port'],
        user=DATABASE_CONFIG['user'],
        password=DATABASE_CONFIG['password'],
        database=DATABASE_CONFIG['database'],
        **({'sslmode': DATABASE_CONFIG['sslmode']} if DATABASE_CONFIG.get('sslmode') else {}),
    )
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.id, a.customer_id
        FROM appointments a
        WHERE a.status = 'completed'
          AND NOT EXISTS (
            SELECT 1 FROM loyalty_transactions lt
            WHERE lt.appointment_id = a.id AND lt.transaction_type = 'earn'
          )
        ORDER BY a.id
        """
    )
    rows = cur.fetchall()
    total = 0
    for apt_id, customer_id in rows:
        pts = award_loyalty_on_completion(cur, customer_id, apt_id)
        if pts:
            total += pts
            print(f'  +{pts} puan → randevu #{apt_id} (müşteri #{customer_id})')
    conn.commit()
    cur.close()
    conn.close()
    print(f'Toplam {len(rows)} randevu işlendi, +{total} puan verildi.')


if __name__ == '__main__':
    main()
