#!/usr/bin/env python3
"""UptimeRobot HTTP monitörlerini oluşturur (API anahtarı gerekir).

Kullanım:
  UPTIMEROBOT_API_KEY=... ../venv/bin/python scripts/setup_uptimerobot.py

Anahtar: UptimeRobot → My Settings → API Settings → Main API Key.
Heartbeat monitörü API ile oluşturulmaz; dashboard’dan alıp
UPTIMEROBOT_HEARTBEAT_URL olarak .env’e yazın.
"""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
load_dotenv(os.path.join(_BACKEND, '.env'))

from config import SITE_CONFIG  # noqa: E402
from uptime_monitor import uptime_catalog  # noqa: E402

V2 = 'https://api.uptimerobot.com/v2'
INTERVAL = 300  # 5 dk — ücretsiz plan


def _api_key() -> str:
    key = (os.getenv('UPTIMEROBOT_API_KEY') or '').strip()
    if not key:
        print('UPTIMEROBOT_API_KEY eksik. UptimeRobot → My Settings → API.')
        sys.exit(1)
    return key


def _post(path: str, data: dict) -> dict:
    payload = {'api_key': _api_key(), 'format': 'json'}
    payload.update(data)
    resp = requests.post(f'{V2}/{path}', data=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if body.get('stat') != 'ok':
        raise RuntimeError(body.get('error') or body)
    return body


def existing_names() -> set[str]:
    body = _post('getMonitors', {'logs': 0})
    names = set()
    for mon in body.get('monitors') or []:
        name = (mon.get('friendly_name') or '').strip()
        if name:
            names.add(name)
    return names


def create_http(name: str, url: str) -> None:
    _post(
        'newMonitor',
        {
            'friendly_name': name,
            'url': url,
            'type': 1,
            'interval': INTERVAL,
            'timeout': 30,
        },
    )
    print(f'Oluşturuldu: {name} → {url}')


def main() -> None:
    catalog = uptime_catalog()
    base = catalog.get('base_url') or (SITE_CONFIG.get('randevu_url') or '').rstrip('/')
    if not base.startswith('http'):
        print('RANDEVU_URL ayarlı değil; canlı adres gerekli.')
        sys.exit(1)

    names = existing_names()
    created = 0
    for item in catalog['monitors']:
        if not item.get('url'):
            continue
        name = f"Roof Tattoo — {item['name']}"
        if name in names:
            print(f'Zaten var: {name}')
            continue
        create_http(name, item['url'])
        created += 1

    print()
    print(f'Yeni HTTP monitör: {created}')
    print('Scheduler için: UptimeRobot → Add Monitor → Heartbeat.')
    print('URL’yi .env içine yazın: UPTIMEROBOT_HEARTBEAT_URL=...')
    print('Sonra roof-tattoo-backend servisini yeniden başlatın.')


if __name__ == '__main__':
    main()
