"""
Wapio REST API istemcisi — OpenAPI 3.0 v1.0.0 (my.wapio.com.tr)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from config import get_wapio_config

logger = logging.getLogger(__name__)

SEND_TIMEOUT = int(os.getenv("WAPIO_SEND_TIMEOUT", "25"))


def _base_url(cfg: dict | None = None) -> str:
    cfg = cfg or get_wapio_config()
    return (cfg.get("api_url") or "https://my.wapio.com.tr").rstrip("/")


def _api_key(cfg: dict | None = None) -> str:
    cfg = cfg or get_wapio_config()
    return (cfg.get("api_key") or os.getenv("WAPIO_API_KEY") or "").strip()


def _session_id(cfg: dict | None = None) -> str:
    cfg = cfg or get_wapio_config()
    return (cfg.get("session_id") or cfg.get("instance_id") or "").strip()


def _domain_key(cfg: dict | None = None) -> str:
    cfg = cfg or get_wapio_config()
    return (cfg.get("domain_key") or os.getenv("WAPIO_DOMAIN_KEY") or "").strip()


def is_wapio_configured(for_messages: bool = True) -> bool:
    cfg = get_wapio_config()
    sid = _session_id(cfg)
    if for_messages:
        return bool(sid)
    return bool(_api_key(cfg))


def normalize_phone_for_send(phone: str) -> str:
    """send-text / OTP için numara normalizasyonu."""
    phone = str(phone or "").strip()
    if "@s.whatsapp.net" in phone:
        phone = phone.split("@", 1)[0].strip()
    if "@" in phone:
        return phone
    if phone.startswith("0"):
        phone = phone[1:]
    if not phone.startswith("90") and len(phone) == 10:
        phone = f"90{phone}"
    return phone


def normalize_phone_for_otp(phone: str) -> str | None:
    """OTP endpoint: 90 ile başlayan 12 hane."""
    p = normalize_phone_for_send(phone)
    if "@" in p:
        return None
    if len(p) == 10 and not p.startswith("90"):
        p = f"90{p}"
    if len(p) == 12 and p.startswith("90") and p.isdigit():
        return p
    return None


def _session_headers(cfg: dict | None = None) -> dict[str, str]:
    sid = _session_id(cfg)
    return {"session_id": sid, "Content-Type": "application/json"}


def check_session_status(cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_wapio_config()
    sid = _session_id(cfg)
    key = _api_key(cfg)
    if not sid or not key:
        return 0, None, "session_id ve api_key gerekli"
    url = f"{_base_url(cfg)}/CheckSessionStatus/{sid}"
    res = requests.get(url, params={"api_key": key}, timeout=10)
    try:
        body = res.json()
    except Exception:
        body = None
    return res.status_code, body, res.text


def check_number(number: str, cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    """GET /CheckNumber — oturumun WhatsApp ile gerçekten konuşabildiğini doğrular."""
    cfg = cfg or get_wapio_config()
    sid = _session_id(cfg)
    if not sid:
        return 0, None, "session_id gerekli"
    phone = normalize_phone_for_send(number)
    if not phone:
        return 0, None, "numara gerekli"
    url = f"{_base_url(cfg)}/CheckNumber"
    res = requests.get(
        url,
        headers=_session_headers(cfg),
        params={"number": phone},
        timeout=10,
    )
    try:
        body = res.json()
    except Exception:
        body = None
    return res.status_code, body, res.text


def _probe_phone_number(cfg: dict | None = None) -> str | None:
    explicit = (os.getenv("WAPIO_PROBE_PHONE") or "").strip()
    if explicit:
        return normalize_phone_for_send(explicit)
    try:
        from config import SITE_CONFIG
        biz = (SITE_CONFIG.get("business_phone") or "").strip()
        if biz:
            return normalize_phone_for_send(biz)
    except Exception:
        pass
    bot = (os.getenv("BOT_PHONE_NUMBER") or "").strip()
    if bot:
        return normalize_phone_for_send(bot)
    return None


def _iter_status_payloads(body) -> list[dict]:
    payloads: list[dict] = []
    if isinstance(body, dict):
        payloads.append(body)
        data = body.get("data")
        if isinstance(data, dict):
            payloads.append(data)
        result = body.get("result")
        if isinstance(result, dict):
            payloads.append(result)
    return payloads


def _string_indicates_disconnected(value: str) -> bool:
    from wapio_api_contract import SESSION_DISCONNECTED_HINTS

    v = (value or "").lower().strip()
    if not v:
        return False
    if any(h in v for h in SESSION_DISCONNECTED_HINTS):
        return True
    return v in {"false", "0", "no", "fail", "failed", "error"}


def _string_indicates_connected(value: str) -> bool:
    from wapio_api_contract import SESSION_CONNECTED_EXACT, SESSION_DISCONNECTED_HINTS

    v = (value or "").lower().strip()
    if not v or _string_indicates_disconnected(v):
        return False
    if v in SESSION_CONNECTED_EXACT:
        return True
    if any(h in v for h in SESSION_DISCONNECTED_HINTS):
        return False
    return v in SESSION_CONNECTED_EXACT or any(
        token in v for token in ("connected", "authenticated", "ready", "working", "online")
    )


def parse_session_state(body, raw_text: str = "") -> str | None:
    """CheckSessionStatus yanıtından oturum durumu: connected | disconnected | None."""
    from wapio_api_contract import SESSION_DISCONNECTED_HINTS

    text = (raw_text or "").lower()
    for hint in SESSION_DISCONNECTED_HINTS:
        if hint in text:
            if hint == "close" and "disclose" in text:
                continue
            return "disconnected"

    for payload in _iter_status_payloads(body):
        for key in ("connected", "isConnected", "is_connected"):
            val = payload.get(key)
            if val is False:
                return "disconnected"
            if val is True:
                return "connected"
        for key in ("status", "state", "session_status", "sessionState", "message"):
            val = payload.get(key)
            if isinstance(val, str):
                if _string_indicates_disconnected(val):
                    return "disconnected"
                if _string_indicates_connected(val):
                    return "connected"

    return None


def _response_indicates_error(body) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in ("status", "success", "ok"):
        val = body.get(key)
        if isinstance(val, str) and val.lower() in ("error", "fail", "failed"):
            msg = body.get("message") or body.get("error") or body.get("detail")
            return str(msg) if msg else "API hata yanıtı"
        if val is False:
            msg = body.get("message") or body.get("error") or body.get("detail")
            return str(msg) if msg else "API başarısız yanıt"
    return None


def probe_session_live(cfg: dict | None = None) -> dict:
    """CheckNumber ile oturumun telefon bağlantısını canlı doğrula."""
    cfg = cfg or get_wapio_config()
    probe_phone = _probe_phone_number(cfg)
    if not probe_phone:
        return {
            "probed": False,
            "ok": None,
            "detail": "Canlı doğrulama numarası tanımlı değil (WAPIO_PROBE_PHONE veya işletme telefonu)",
        }

    status, body, raw = check_number(probe_phone, cfg)
    api_error = _response_indicates_error(body)
    raw_lower = (raw or "").lower()

    if status in (401, 403, 404, 408) or status >= 500:
        return {
            "probed": True,
            "ok": False,
            "detail": f"WhatsApp oturumu yanıt vermiyor (CheckNumber HTTP {status})",
            "http_status": status,
        }

    if api_error:
        return {
            "probed": True,
            "ok": False,
            "detail": api_error,
            "http_status": status,
        }

    disconnected_markers = (
        "disconnected", "not connected", "session not found", "invalid session",
        "session expired", "closed", "offline", "waiting_qr", "scan_qr",
    )
    if any(marker in raw_lower for marker in disconnected_markers):
        return {
            "probed": True,
            "ok": False,
            "detail": "WhatsApp bağlantısı kopuk görünüyor (canlı doğrulama)",
            "http_status": status,
        }

    if 200 <= status < 300:
        return {
            "probed": True,
            "ok": True,
            "detail": "Canlı doğrulama başarılı",
            "http_status": status,
        }

    return {
        "probed": True,
        "ok": False,
        "detail": f"Canlı doğrulama başarısız (HTTP {status})",
        "http_status": status,
    }


def interpret_session_status(
    http_status: int,
    body,
    raw_text: str = "",
    *,
    cfg: dict | None = None,
    run_probe: bool = True,
) -> dict:
    """Wapio CheckSessionStatus yanıtını admin UI için yorumla."""
    if http_status == 0:
        return {
            "state": "unconfigured",
            "connected": False,
            "label": "Yapılandırma eksik",
            "detail": "API Key ve Session ID girin",
            "probe": None,
        }
    if http_status == 404:
        return {
            "state": "disconnected",
            "connected": False,
            "label": "Başarısız",
            "detail": "Oturum bulunamadı — QR ile yeniden bağlanın",
            "probe": None,
        }
    if http_status >= 400:
        return {
            "state": "error",
            "connected": False,
            "label": "Başarısız",
            "detail": f"API hatası (HTTP {http_status})",
            "probe": None,
        }

    session_state = parse_session_state(body, raw_text)
    api_error = _response_indicates_error(body)

    if session_state == "disconnected" or api_error:
        detail = api_error or "Bağlantı kopuk veya QR bekleniyor"
        return {
            "state": "disconnected",
            "connected": False,
            "label": "Başarısız",
            "detail": detail,
            "session_state": session_state,
            "probe": None,
        }

    probe_info = None
    should_probe = run_probe and cfg and _session_id(cfg)
    if should_probe and session_state in (None, "connected"):
        probe_info = probe_session_live(cfg)
        if probe_info.get("probed") and probe_info.get("ok") is False:
            return {
                "state": "disconnected",
                "connected": False,
                "label": "Başarısız",
                "detail": (
                    probe_info.get("detail")
                    or "Telefondan bağlantı kesilmiş olabilir — QR ile yeniden bağlanın"
                ),
                "session_state": session_state or "unknown",
                "probe": probe_info,
            }

    if session_state == "connected" or (probe_info and probe_info.get("ok") is True):
        detail = "WhatsApp bağlantısı aktif"
        if probe_info and probe_info.get("probed"):
            detail = "WhatsApp bağlantısı aktif (canlı doğrulandı)"
        return {
            "state": "connected",
            "connected": True,
            "label": "Başarılı",
            "detail": detail,
            "session_state": session_state or "connected",
            "probe": probe_info,
        }

    if 200 <= http_status < 300:
        return {
            "state": "pending",
            "connected": False,
            "label": "Beklemede",
            "detail": "QR kod okutulması bekleniyor",
            "session_state": session_state,
            "probe": probe_info,
        }

    return {
        "state": "unknown",
        "connected": False,
        "label": "Başarısız",
        "detail": "Bağlantı durumu belirlenemedi",
        "session_state": session_state,
        "probe": probe_info,
    }


def create_device(device_name: str, cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_wapio_config()
    key = _api_key(cfg)
    if not key:
        return 0, None, "api_key gerekli"
    url = f"{_base_url(cfg)}/CreateDevice"
    res = requests.post(
        url,
        data={"deviceName": device_name, "api_key": key},
        timeout=SEND_TIMEOUT,
    )
    try:
        body = res.json()
    except Exception:
        body = None
    return res.status_code, body, res.text


def get_qr(session_id: str, device_name: str, webhook: str = "", cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_wapio_config()
    key = _api_key(cfg)
    if not key or not session_id:
        return 0, None, "api_key ve session_id gerekli"
    url = f"{_base_url(cfg)}/GetQR/{session_id}"
    res = requests.post(
        url,
        params={"api_key": key},
        data={"deviceName": device_name, "webhook": webhook or ""},
        timeout=SEND_TIMEOUT,
    )
    try:
        body = res.json()
    except Exception:
        body = None
    return res.status_code, body, res.text


def update_webhook(session_id: str, webhook: str, device_name: str, cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_wapio_config()
    key = _api_key(cfg)
    if not key or not session_id:
        return 0, None, "api_key ve session_id gerekli"
    url = f"{_base_url(cfg)}/UpdateWebhook"
    res = requests.post(
        url,
        data={
            "api_key": key,
            "session_id": session_id,
            "webhook": webhook,
            "deviceName": device_name,
        },
        timeout=SEND_TIMEOUT,
    )
    try:
        body = res.json()
    except Exception:
        body = None
    return res.status_code, body, res.text


def send_text(phone: str, message: str, retry_count: int = 0, cfg: dict | None = None) -> bool:
    """POST /send-text — OpenAPI: yalnızca session_id header."""
    cfg = cfg or get_wapio_config()
    sid = _session_id(cfg)
    if not sid:
        logger.warning("Wapio session_id eksik — mesaj gönderilemedi")
        return False

    max_retries = 1
    phone = normalize_phone_for_send(phone)
    url = f"{_base_url(cfg)}/send-text"
    payload = {
        "phone": phone,
        "is_group": False,
        "is_channel": False,
        "data": {"message": message, "messageId": ""},
    }
    headers = _session_headers(cfg)

    try:
        logger.info(f"Wapio send-text: {phone} (deneme {retry_count + 1})")
        res = requests.post(url, json=payload, headers=headers, timeout=SEND_TIMEOUT)
        res.raise_for_status()
        logger.info(f"Wapio send-text OK: {phone} — {res.text[:200]}")
        return True
    except requests.exceptions.Timeout:
        if retry_count < max_retries:
            time.sleep(1)
            return send_text(phone, message, retry_count + 1, cfg)
        return False
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else None
        if status == 408 and retry_count < max_retries:
            time.sleep(5)
            return send_text(phone, message, retry_count + 1, cfg)
        logger.error(f"Wapio send-text HTTP {status}: {phone} — {e}")
        return False
    except Exception as e:
        logger.error(f"Wapio send-text hata: {phone} — {e}")
        return False


def send_otp_whatsapp(phone: str, otp_code: str, cfg: dict | None = None) -> bool:
    """POST /send-otp-whatsapp — domain_key header zorunlu."""
    cfg = cfg or get_wapio_config()
    domain_key = _domain_key(cfg)
    otp_phone = normalize_phone_for_otp(phone)
    if not domain_key:
        logger.warning("WAPIO_DOMAIN_KEY eksik — send-otp-whatsapp kullanılamaz")
        return False
    if not otp_phone:
        logger.warning(f"OTP için geçersiz numara formatı: {phone}")
        return False

    url = f"{_base_url(cfg)}/send-otp-whatsapp"
    headers = {"domain_key": domain_key, "Content-Type": "application/json"}
    payload = {"phone": otp_phone, "otp_code": str(otp_code)[:6]}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=SEND_TIMEOUT)
        res.raise_for_status()
        data = res.json() if res.content else {}
        if isinstance(data, dict) and str(data.get("status", "")).lower() == "error":
            logger.error(f"Wapio OTP error: {data.get('message')}")
            return False
        logger.info(f"Wapio OTP gönderildi: {otp_phone}")
        return True
    except Exception as e:
        logger.error(f"Wapio send-otp-whatsapp hata: {otp_phone} — {e}")
        return False


def extract_qr_image(body: dict | list | None, raw_text: str = "") -> str | None:
    """QR yanıtından base64/data URL çıkar."""
    if isinstance(body, dict):
        for key in ("qr", "qrcode", "qr_code", "qrCode", "image", "data"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("qr", "qrcode", "qr_code", "image"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        if isinstance(data, str) and data.strip():
            return data.strip()
    text = (raw_text or "").strip()
    if text.startswith("data:image") or (len(text) > 100 and "base64" in text.lower()):
        return text
    return None


def extract_session_id_from_response(body: dict | list | None) -> str | None:
    if not isinstance(body, dict):
        return None
    for key in ("session_id", "sessionId", "session"):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    data = body.get("data")
    if isinstance(data, dict):
        for key in ("session_id", "sessionId", "id"):
            val = data.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return None
