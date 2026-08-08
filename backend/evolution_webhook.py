"""
Evolution API webhook payload ayrıştırma (messages.upsert / MESSAGES_UPSERT).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

SKIP_EVENTS = frozenset(
    {
        "connection.update",
        "connection_update",
        "qrcode.updated",
        "qrcode_updated",
        "messages.update",
        "messages_update",
        "send.message",
        "send_message",
        "presence.update",
        "presence_update",
    }
)


@dataclass
class EvolutionInbound:
    phone: str
    body: str
    cooldown_key: str
    is_whatsapp_id_format: bool
    message_id: str | None
    remote_jid: str | None = None
    remote_jid_alt: str | None = None


def _event_name(payload: dict) -> str:
    return str(payload.get("event") or payload.get("type") or "").strip().lower()


def is_evolution_webhook_payload(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    ev = _event_name(payload)
    if not ev:
        return False
    if "messages" in ev and "upsert" in ev:
        return True
    return ev in ("messages.upsert", "messages_upsert")


def _extract_message_text(msg: dict | None) -> str:
    if not isinstance(msg, dict):
        return ""
    if isinstance(msg.get("conversation"), str):
        return msg["conversation"].strip()
    ext = msg.get("extendedTextMessage")
    if isinstance(ext, dict) and isinstance(ext.get("text"), str):
        return ext["text"].strip()
    for media_key in ("imageMessage", "videoMessage", "documentMessage"):
        media = msg.get(media_key)
        if isinstance(media, dict) and isinstance(media.get("caption"), str):
            cap = media["caption"].strip()
            if cap:
                return cap
    buttons = msg.get("buttonsResponseMessage")
    if isinstance(buttons, dict) and isinstance(buttons.get("selectedDisplayText"), str):
        return buttons["selectedDisplayText"].strip()
    inner = msg.get("message")
    if isinstance(inner, dict):
        return _extract_message_text(inner)
    for key in ("text", "body"):
        if isinstance(msg.get(key), str):
            return msg[key].strip()
    return ""


def _should_skip_upsert_record(record: dict) -> bool:
    """Evolution bazen aynı mesaj için READ/DELIVERY_ACK tekrar gönderir — yalnızca bunları atla."""
    status = str(record.get("status") or "").strip().upper()
    if status in ("READ", "READ_SELF", "PLAYED", "SENT"):
        return True
    return False


def _normalize_remote_jid(jid: str) -> tuple[str, bool, bool]:
    """phone, is_group, is_whatsapp_id_format"""
    s = str(jid or "").strip()
    if not s:
        return "", False, False
    if "@g.us" in s:
        return s, True, True
    if "@s.whatsapp.net" in s:
        return s.split("@", 1)[0].strip(), False, False
    if "@" in s:
        return s, False, True
    return s, False, False


def _parse_message_record(record: dict) -> EvolutionInbound | None:
    if not isinstance(record, dict):
        return None
    if _should_skip_upsert_record(record):
        return None

    key = record.get("key") if isinstance(record.get("key"), dict) else {}
    from_me = key.get("fromMe", record.get("fromMe", False))
    if from_me:
        return None

    remote_jid = key.get("remoteJid") or record.get("remoteJid") or ""
    remote_jid_alt = key.get("remoteJidAlt") or record.get("remoteJidAlt") or ""
    phone, is_group, is_jid = _normalize_remote_jid(
        remote_jid or remote_jid_alt
    )
    if is_group or not phone:
        return None

    body = _extract_message_text(record.get("message"))
    if not body:
        body = _extract_message_text(record)

    msg_id_raw = key.get("id") or record.get("id")
    message_id = str(msg_id_raw).strip() if msg_id_raw else None

    if is_jid:
        cooldown_key = phone.strip()
    else:
        from evolution_client import normalize_phone_for_send

        cooldown_key = normalize_phone_for_send(phone)

    return EvolutionInbound(
        phone=phone,
        body=body.strip().lower(),
        cooldown_key=cooldown_key,
        is_whatsapp_id_format=is_jid,
        message_id=message_id,
        remote_jid=str(remote_jid).strip() if remote_jid else None,
        remote_jid_alt=str(remote_jid_alt).strip() if remote_jid_alt else None,
    )


def parse_evolution_inbound(payload: dict) -> EvolutionInbound | None:
    """Evolution webhook gövdesinden gelen müşteri mesajını çıkar; uygun değilse None."""
    if not isinstance(payload, dict):
        return None

    ev = _event_name(payload)
    if ev in SKIP_EVENTS:
        logger.info(f"Evolution webhook event atlandı: {ev}")
        return None
    if ev and not is_evolution_webhook_payload(payload):
        logger.info(f"Evolution webhook mesaj eventi değil: {ev}")
        return None

    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            parsed = _parse_message_record(item)
            if parsed and parsed.body:
                return parsed
        return None
    if isinstance(data, dict):
        parsed = _parse_message_record(data)
        if parsed:
            return parsed
    return _parse_message_record(payload)
