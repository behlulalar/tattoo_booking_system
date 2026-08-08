#!/usr/bin/env python3
"""CLI: Wapio API uyumluluk kontrolü."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from wapio_compat import run_wapio_compat_check


def main() -> int:
    webhook = os.getenv("WAPIO_WEBHOOK_URL", "")
    report = run_wapio_compat_check(webhook_url=webhook or None)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("compatible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
