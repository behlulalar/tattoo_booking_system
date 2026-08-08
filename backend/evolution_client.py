"""
Evolution API istemcisi (evolution-foundation/evolution-api v2).
Baileys tabanlı instance: oluşturma, QR, mesaj, webhook, bağlantı durumu.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import requests

from config import get_evolution_config

logger = logging.getLogger(__name__)

SEND_TIMEOUT = int(os.getenv("EVOLUTION_SEND_TIMEOUT", os.getenv("WAPIO_SEND_TIMEOUT", "25")))
DEFAULT_INTEGRATION = "WHATSAPP-BAILEYS"
INBOUND_WEBHOOK_EVENTS = ["MESSAGES_UPSERT"]


def _base_url(cfg: dict | None = None) -> str:
    cfg = cfg or get_evolution_config()
    return (cfg.get("api_url") or "http://127.0.0.1:8080").rstrip("/")


def _api_key(cfg: dict | None = None) -> str:
    cfg = cfg or get_evolution_config()
    return (cfg.get("api_key") or "").strip()


def _instance_name(cfg: dict | None = None) -> str:
    cfg = cfg or get_evolution_config()
    return (cfg.get("instance_name") or "").strip()


def _headers(cfg: dict | None = None) -> dict[str, str]:
    key = _api_key(cfg)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["apikey"] = key
    return headers


def is_evolution_configured(for_messages: bool = True) -> bool:
    cfg = get_evolution_config()
    if for_messages:
        return bool(_api_key(cfg) and _instance_name(cfg))
    return bool(_api_key(cfg))


def normalize_phone_for_send(phone: str) -> str:
    """Evolution sendText: uluslararası numara (90…) — yalnızca rakam."""
    phone = str(phone or "").strip()
    if "@s.whatsapp.net" in phone:
        phone = phone.split("@", 1)[0].strip()
    if "@" in phone:
        return phone
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("0") and len(digits) == 11:
        digits = "90" + digits[1:]
    elif len(digits) == 10 and not digits.startswith("90"):
        digits = f"90{digits}"
    return digits


def resolve_evolution_send_target(
    phone: str,
    *,
    remote_jid: str | None = None,
    remote_jid_alt: str | None = None,
) -> str:
    """Tek gönderim hedefi — aynı mesajın JID + numara ile iki kez gitmesini önler."""
    for candidate in (remote_jid_alt, remote_jid):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    digits = normalize_phone_for_send(phone)
    if "@" in digits:
        return digits
    return f"{digits}@s.whatsapp.net"


def _send_text_response_ok(body: dict | list | None, raw: str = "") -> bool:
    """Evolution HTTP 2xx yanıtı — key.id varsa kabul (PENDING dahil)."""
    if not isinstance(body, dict):
        return True
    status = str(body.get("status") or "").upper()
    if status in ("ERROR", "FAILED"):
        return False
    key = body.get("key")
    if isinstance(key, dict) and key.get("id"):
        return True
    msg = body.get("message")
    if isinstance(msg, dict):
        mk = msg.get("key")
        if isinstance(mk, dict) and mk.get("id"):
            return True
    err = body.get("error")
    if err:
        return False
    if "exists" in (raw or "").lower() and "false" in (raw or "").lower():
        return False
    if status == "PENDING":
        logger.warning("Evolution sendText PENDING ve keysiz")
        return False
    return True


def _request(
    method: str,
    path: str,
    *,
    cfg: dict | None = None,
    json_body: dict | None = None,
    params: dict | None = None,
    timeout: int | None = None,
) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_evolution_config()
    url = f"{_base_url(cfg)}{path}"
    try:
        res = requests.request(
            method,
            url,
            headers=_headers(cfg),
            json=json_body,
            params=params,
            timeout=timeout or SEND_TIMEOUT,
        )
        raw = res.text or ""
        try:
            body = res.json()
        except Exception:
            body = None
        return res.status_code, body, raw
    except Exception as e:
        logger.error(f"Evolution API isteği başarısız {method} {path}: {e}")
        return 0, None, str(e)


def create_instance(instance_name: str, cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_evolution_config()
    name = (instance_name or _instance_name(cfg) or "").strip()
    if not name:
        return 0, None, "instance_name gerekli"
    if not _api_key(cfg):
        return 0, None, "api_key gerekli"
    payload: dict[str, Any] = {
        "instanceName": name,
        "qrcode": True,
        "integration": DEFAULT_INTEGRATION,
    }
    return _request("POST", "/instance/create", cfg=cfg, json_body=payload)


def connect_instance(instance_name: str | None = None, cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_evolution_config()
    name = (instance_name or _instance_name(cfg) or "").strip()
    if not name:
        return 0, None, "instance_name gerekli"
    return _request("GET", f"/instance/connect/{name}", cfg=cfg)


def connection_state(instance_name: str | None = None, cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_evolution_config()
    name = (instance_name or _instance_name(cfg) or "").strip()
    if not name:
        return 0, None, "instance_name gerekli"
    return _request("GET", f"/instance/connectionState/{name}", cfg=cfg, timeout=10)


def fetch_instances(cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_evolution_config()
    return _request("GET", "/instance/fetchInstances", cfg=cfg, timeout=12)


def _connection_status_from_fetch(body, instance_name: str) -> str | None:
    if not isinstance(body, list):
        return None
    for item in body:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or item.get("instanceName") or "").strip()
        if name == instance_name:
            raw = item.get("connectionStatus") or item.get("connection_status") or item.get("status")
            return str(raw).strip().lower() if raw else None
    return None


def resolve_evolution_connection(cfg: dict | None = None, instance_name: str | None = None) -> dict:
    """
    Kararlı bağlantı durumu — önce fetchInstances (connectionStatus),
    gerekirse connectionState örneklemesi (open/connecting titremesini yumuşatır).
    """
    cfg = cfg or get_evolution_config()
    name = (instance_name or _instance_name(cfg) or "").strip()
    if not _api_key(cfg) or not name:
        return interpret_connection_status(0, None, "")

    status, body, raw = fetch_instances(cfg)
    fetch_state = _connection_status_from_fetch(body, name) if status == 200 else None

    if fetch_state == "open":
        info = interpret_connection_status(
            200, {"instance": {"state": "open", "connectionStatus": "open"}}, raw
        )
        info["source"] = "fetchInstances"
        return info

    if fetch_state == "connecting":
        return {
            "state": "pending",
            "connected": False,
            "label": "Bağlanıyor",
            "detail": "Oturum yenileniyor — birkaç saniye bekleyin",
            "raw_state": "connecting",
            "source": "fetchInstances",
        }

    if fetch_state in ("close", "closed"):
        info = interpret_connection_status(200, {"instance": {"state": "close"}}, raw)
        info["source"] = "fetchInstances"
        return info

    seen_open = False
    last_body = None
    last_status = 0
    last_raw = ""
    for _ in range(5):
        last_status, last_body, last_raw = connection_state(name, cfg)
        if last_status == 200 and isinstance(last_body, dict):
            inst = last_body.get("instance") if isinstance(last_body.get("instance"), dict) else {}
            st = (inst.get("state") or inst.get("status") or "").lower()
            if st == "open":
                seen_open = True
            if st in ("close", "closed"):
                seen_open = False
                break
        time.sleep(0.3)

    if seen_open:
        info = interpret_connection_status(
            200, {"instance": {"state": "open"}}, last_raw
        )
        info["source"] = "connectionState_samples"
        info["detail"] = "WhatsApp bağlantısı aktif (Evolution)"
        return info

    info = interpret_connection_status(last_status, last_body, last_raw)
    info["source"] = "connectionState"
    return info


def set_webhook(instance_name: str, webhook_url: str, cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_evolution_config()
    name = (instance_name or _instance_name(cfg) or "").strip()
    url = (webhook_url or "").strip()
    if not name or not url:
        return 0, None, "instance_name ve webhook url gerekli"
    payload = {
        "webhook": {
            "enabled": True,
            "url": url,
            "byEvents": False,
            "base64": False,
            "events": INBOUND_WEBHOOK_EVENTS,
        }
    }
    return _request("POST", f"/webhook/set/{name}", cfg=cfg, json_body=payload)


def restart_instance(instance_name: str | None = None, cfg: dict | None = None) -> tuple[int, dict | list | None, str]:
    cfg = cfg or get_evolution_config()
    name = (instance_name or _instance_name(cfg) or "").strip()
    if not name:
        return 0, None, "instance_name gerekli"
    return _request("POST", f"/instance/restart/{name}", cfg=cfg, timeout=45)


def _response_indicates_connection_closed(status: int, raw: str, body) -> bool:
    text = (raw or "").lower()
    if "connection closed" in text or "connection_closed" in text:
        return True
    if isinstance(body, dict):
        for key in ("message", "error"):
            val = body.get(key)
            if isinstance(val, str) and "connection closed" in val.lower():
                return True
        resp = body.get("response")
        if isinstance(resp, dict):
            inner = resp.get("message")
            if isinstance(inner, list):
                blob = " ".join(str(x) for x in inner).lower()
                if "connection closed" in blob:
                    return True
            elif isinstance(inner, str) and "connection closed" in inner.lower():
                return True
    return status in (400, 500) and "closed" in text


def _recover_whatsapp_session(instance_name: str, cfg: dict) -> None:
    """Baileys oturumu koptuğunda restart + connect."""
    restart_instance(instance_name, cfg)
    time.sleep(2)
    connect_instance(instance_name, cfg)
    time.sleep(4)


def ensure_instance_ready_for_send(cfg: dict | None = None, max_wait_sec: float = 12.0) -> bool:
    """Gönderim öncesi bağlantının open olduğundan emin ol; gerekirse restart."""
    cfg = cfg or get_evolution_config()
    name = _instance_name(cfg)
    if not name or not _api_key(cfg):
        return False

    info = resolve_evolution_connection(cfg, name)
    if info.get("connected"):
        return True

    raw_state = (info.get("raw_state") or "").lower()
    if raw_state in ("connecting", "pairing"):
        deadline = time.time() + max_wait_sec
        while time.time() < deadline:
            time.sleep(1.5)
            info = resolve_evolution_connection(cfg, name)
            if info.get("connected"):
                return True
        return False

    logger.warning("Evolution bağlantısı kapalı — instance restart deneniyor")
    r_status, _, r_raw = restart_instance(name, cfg)
    if r_status and not (200 <= r_status < 300):
        logger.error(f"Evolution restart HTTP {r_status}: {r_raw[:200]}")
        return False
    time.sleep(3)
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        info = resolve_evolution_connection(cfg, name)
        if info.get("connected"):
            return True
        time.sleep(1.5)
    return False


def send_text(
    phone: str,
    message: str,
    retry_count: int = 0,
    cfg: dict | None = None,
    *,
    remote_jid: str | None = None,
    remote_jid_alt: str | None = None,
) -> bool:
    cfg = cfg or get_evolution_config()
    name = _instance_name(cfg)
    if not name or not _api_key(cfg):
        logger.warning("Evolution api_key veya instance_name eksik — mesaj gönderilemedi")
        return False

    target = resolve_evolution_send_target(
        phone, remote_jid=remote_jid, remote_jid_alt=remote_jid_alt
    )
    url_path = f"/message/sendText/{name}"
    payload = {"number": target, "text": message}

    try:
        logger.info(f"Evolution sendText → {target} (deneme {retry_count + 1})")
        status, body, raw = _request("POST", url_path, cfg=cfg, json_body=payload)
        if 200 <= status < 300 and _send_text_response_ok(body, raw):
            logger.info(f"Evolution sendText OK: {target}")
            return True
        if 200 <= status < 300:
            logger.warning(f"Evolution sendText geçersiz yanıt ({target}): {raw[:200]}")
            return False

        if _response_indicates_connection_closed(status, raw, body) and retry_count < 3:
            logger.warning(f"Evolution Connection Closed — oturum yenileme ({target})")
            _recover_whatsapp_session(name, cfg)
            return send_text(
                phone,
                message,
                retry_count + 1,
                cfg,
                remote_jid=remote_jid,
                remote_jid_alt=remote_jid_alt,
            )

        if status in (408, 429, 502, 503, 504) and retry_count < 3:
            time.sleep(2)
            return send_text(
                phone,
                message,
                retry_count + 1,
                cfg,
                remote_jid=remote_jid,
                remote_jid_alt=remote_jid_alt,
            )

        logger.error(f"Evolution sendText HTTP {status}: {target} — {raw[:300]}")
        return False
    except Exception as e:
        logger.error(f"Evolution sendText hata ({target}): {e}")
        return False


def extract_qr_image(body: dict | list | None, raw_text: str = "") -> str | None:
    """QR yanıtından base64/data URL çıkar."""
    candidates: list[Any] = []
    if isinstance(body, dict):
        candidates.append(body.get("base64"))
        qrcode = body.get("qrcode") or body.get("qrCode")
        if isinstance(qrcode, dict):
            candidates.extend([qrcode.get("base64"), qrcode.get("code")])
        elif isinstance(qrcode, str):
            candidates.append(qrcode)
        inst = body.get("instance")
        if isinstance(inst, dict):
            inner = inst.get("qrcode") or inst.get("qrCode")
            if isinstance(inner, dict):
                candidates.extend([inner.get("base64"), inner.get("code")])
    text = (raw_text or "").strip()
    if text.startswith("data:image"):
        return text
    for val in candidates:
        if isinstance(val, str) and val.strip():
            s = val.strip()
            if s.startswith("data:image"):
                return s
            if len(s) > 50:
                return s
    return None


def extract_instance_name_from_response(body: dict | list | None) -> str | None:
    if not isinstance(body, dict):
        return None
    inst = body.get("instance")
    if isinstance(inst, dict):
        name = inst.get("instanceName") or inst.get("instance_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    for key in ("instanceName", "instance_name"):
        val = body.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _map_state(raw_state: str | None) -> str | None:
    if not raw_state:
        return None
    s = str(raw_state).lower().strip()
    if s == "open":
        return "connected"
    if s in ("connecting", "pairing"):
        return "pending"
    if s in ("close", "closed", "disconnected", "logout"):
        return "disconnected"
    return None


def interpret_connection_status(http_status: int, body, raw_text: str = "") -> dict:
    """Evolution connectionState / connect yanıtını admin UI ile uyumlu yorumla."""
    if http_status == 0:
        return {
            "state": "unconfigured",
            "connected": False,
            "label": "Yapılandırma eksik",
            "detail": "API Key ve Instance Name girin",
        }
    if http_status == 404:
        return {
            "state": "disconnected",
            "connected": False,
            "label": "Başarısız",
            "detail": "Instance bulunamadı — önce instance oluşturun",
        }
    if http_status >= 400:
        return {
            "state": "error",
            "connected": False,
            "label": "Başarısız",
            "detail": f"API hatası (HTTP {http_status})",
        }

    raw_state = None
    if isinstance(body, dict):
        inst = body.get("instance")
        if isinstance(inst, dict):
            raw_state = inst.get("state") or inst.get("status")
        raw_state = raw_state or body.get("state") or body.get("status")

    mapped = _map_state(raw_state)
    if mapped == "connected":
        return {
            "state": "connected",
            "connected": True,
            "label": "Başarılı",
            "detail": "WhatsApp bağlantısı aktif (Evolution)",
            "raw_state": raw_state,
        }
    if mapped == "pending":
        detail = "QR kod okutulması bekleniyor"
        if raw_state == "connecting":
            detail = "Bağlantı kuruluyor veya yenileniyor"
        return {
            "state": "pending",
            "connected": False,
            "label": "Bağlanıyor" if raw_state == "connecting" else "Beklemede",
            "detail": detail,
            "raw_state": raw_state,
        }
    if mapped == "disconnected":
        return {
            "state": "disconnected",
            "connected": False,
            "label": "Başarısız",
            "detail": "Bağlantı kapalı — QR ile yeniden bağlanın",
            "raw_state": raw_state,
        }

    if 200 <= http_status < 300:
        return {
            "state": "pending",
            "connected": False,
            "label": "Beklemede",
            "detail": "Bağlantı durumu: QR gerekebilir",
            "raw_state": raw_state,
        }
    return {
        "state": "unknown",
        "connected": False,
        "label": "Başarısız",
        "detail": "Bağlantı durumu belirlenemedi",
        "raw_state": raw_state,
    }
