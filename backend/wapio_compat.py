"""
Wapio API uyumluluk kontrolü — OpenAPI 3.0 v1.0.0 ile canlı API karşılaştırması.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from config import get_wapio_config
from wapio_api_contract import (
    API_KEY_SOURCE_URL,
    CONTRACT_SOURCE,
    CONTRACT_VERSION,
    DEPRECATED_ENDPOINTS,
    ENDPOINTS,
    OPENAPI_INFO_VERSION,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _status_label(ok: bool, warn: bool = False) -> str:
    if ok:
        return "ok"
    if warn:
        return "warn"
    return "fail"


def _parse_json_safe(response: requests.Response):
    try:
        return response.json()
    except Exception:
        return None


def _session_state_from_body(text: str, payload) -> str | None:
    from wapio_client import parse_session_state
    return parse_session_state(payload, text)


def _check_config(wapio_config: dict) -> dict[str, Any]:
    api_key = (wapio_config.get("api_key") or "").strip()
    session_id = (wapio_config.get("session_id") or wapio_config.get("instance_id") or "").strip()
    domain_key = (wapio_config.get("domain_key") or "").strip()
    missing = []
    if not api_key:
        missing.append(f"api_key (WAPIO_API_KEY — {API_KEY_SOURCE_URL})")
    notes = []
    if not session_id:
        notes.append("session_id yok — send-text (doğrulama kodu dahil) çalışmaz")
    ok = bool(api_key)
    return {
        "id": "config",
        "label": "Yapılandırma",
        "status": _status_label(ok, warn=ok and not session_id),
        "ok": ok,
        "details": {
            "openapi_version": OPENAPI_INFO_VERSION,
            "base_url": wapio_config.get("api_url"),
            "has_api_key": bool(api_key),
            "has_session_id": bool(session_id),
            "has_domain_key": bool(domain_key),
            "missing": missing,
            "notes": notes,
        },
    }


def _check_send_text(base_url: str, session_id: str, spec: dict) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{spec['path']}"
    payload = {
        "phone": "",
        "is_group": False,
        "is_channel": False,
        "data": {"message": "", "messageId": ""},
    }
    headers = {"session_id": session_id, "Content-Type": "application/json"}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        body = _parse_json_safe(res)
        expected = spec["expect_status_any_of"]
        endpoint_exists = res.status_code != 404
        ok = endpoint_exists and res.status_code in expected
        return {
            "id": "send_text",
            "label": spec["label"],
            "status": _status_label(ok, warn=endpoint_exists and res.status_code in (401, 403)),
            "ok": ok,
            "details": {
                "url": url,
                "http_status": res.status_code,
                "auth": "header session_id (OpenAPI — token yok)",
                "expected_any_of": expected,
                "response_preview": (res.text or "")[:300],
                "response_json": body,
            },
        }
    except Exception as e:
        return {"id": "send_text", "label": spec["label"], "status": "fail", "ok": False, "details": {"error": str(e)}}


def _check_send_otp(base_url: str, domain_key: str, spec: dict) -> dict[str, Any]:
    if not domain_key:
        return {
            "id": "send_otp_whatsapp",
            "label": spec["label"],
            "status": "warn",
            "ok": True,
            "details": {"note": "domain_key tanımlı değil — atlandı"},
        }
    url = f"{base_url.rstrip('/')}{spec['path']}"
    headers = {"domain_key": domain_key, "Content-Type": "application/json"}
    payload = {"phone": "905551234567", "otp_code": "000000"}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        body = _parse_json_safe(res)
        expected = spec["expect_status_any_of"]
        endpoint_exists = res.status_code != 404
        ok = endpoint_exists and res.status_code in expected
        return {
            "id": "send_otp_whatsapp",
            "label": spec["label"],
            "status": _status_label(ok, warn=res.status_code in (401, 408)),
            "ok": ok,
            "details": {
                "url": url,
                "http_status": res.status_code,
                "auth": "header domain_key",
                "expected_any_of": expected,
                "response_preview": (res.text or "")[:300],
                "response_json": body,
                "note": "Probe kodu gönderilmez; yalnızca endpoint + auth testi",
            },
        }
    except Exception as e:
        return {"id": "send_otp_whatsapp", "label": spec["label"], "status": "fail", "ok": False, "details": {"error": str(e)}}


def _check_session_status(base_url: str, session_id: str, api_key: str, spec: dict) -> dict[str, Any]:
    if not session_id:
        return {
            "id": "check_session_status",
            "label": spec["label"],
            "status": "warn",
            "ok": False,
            "details": {"note": "session_id yok — QR bağlantısı kurulmamış"},
        }
    url = f"{base_url.rstrip('/')}/CheckSessionStatus/{session_id}"
    try:
        res = requests.get(url, params={"api_key": api_key}, timeout=10)
        body = _parse_json_safe(res)
        session_state = _session_state_from_body(res.text, body)
        expected = spec["expect_status_any_of"]
        ok = res.status_code != 404 and res.status_code in expected
        return {
            "id": "check_session_status",
            "label": spec["label"],
            "status": _status_label(ok and session_state != "disconnected", warn=ok and session_state is None),
            "ok": ok and session_state != "disconnected",
            "details": {
                "url": url,
                "http_status": res.status_code,
                "session_state": session_state,
                "response_preview": (res.text or "")[:300],
                "response_json": body,
            },
        }
    except Exception as e:
        return {"id": "check_session_status", "label": spec["label"], "status": "fail", "ok": False, "details": {"error": str(e)}}


def _check_deprecated(base_url: str) -> dict[str, Any]:
    found = []
    for path in DEPRECATED_ENDPOINTS:
        try:
            res = requests.get(f"{base_url.rstrip('/')}{path}", timeout=5)
            if res.status_code != 404:
                found.append({"path": path, "status": res.status_code})
        except Exception:
            pass
    return {
        "id": "deprecated",
        "label": "Eski endpoint'ler (OpenAPI'de yok)",
        "status": "warn" if found else "ok",
        "ok": True,
        "details": {
            "still_responding": found,
            "note": "GetContact /status gibi eski yollar kullanılmamalı",
        },
    }


def run_wapio_compat_check(webhook_url: str | None = None) -> dict[str, Any]:
    wapio_config = get_wapio_config()
    base_url = (wapio_config.get("api_url") or "").rstrip("/")
    api_key = (wapio_config.get("api_key") or "").strip()
    session_id = (wapio_config.get("session_id") or wapio_config.get("instance_id") or "").strip()
    domain_key = (wapio_config.get("domain_key") or "").strip()

    checks = [_check_config(wapio_config)]

    if api_key:
        checks.append(_check_session_status(base_url, session_id, api_key, ENDPOINTS["check_session_status"]))
        if session_id:
            checks.append(_check_send_text(base_url, session_id, ENDPOINTS["send_text"]))
        checks.append(_check_deprecated(base_url))
    else:
        checks.append({
            "id": "skipped",
            "label": "Canlı API testleri",
            "status": "fail",
            "ok": False,
            "details": {"note": "api_key girilmeden test yapılamaz"},
        })

    critical_ok = checks[0]["ok"]
    if session_id:
        send_check = next((c for c in checks if c["id"] == "send_text"), None)
        if send_check and not send_check.get("ok"):
            critical_ok = False

    return {
        "success": True,
        "compatible": critical_ok,
        "contract_version": CONTRACT_VERSION,
        "contract_source": CONTRACT_SOURCE,
        "openapi_version": OPENAPI_INFO_VERSION,
        "checked_at": _now_iso(),
        "webhook_url": webhook_url,
        "checks": checks,
        "mismatches_fixed": [
            "Doğrulama kodu /send-text ile normal WhatsApp mesajı olarak gönderilir",
            "send-text yalnızca session_id header kullanır (token kaldırıldı)",
        ],
        "action_required": None if critical_ok else "wapio_api_contract.py ve wapio_client.py dosyalarını paneldeki OpenAPI ile karşılaştırın.",
    }
