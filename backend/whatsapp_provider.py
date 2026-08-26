"""
WhatsApp mesaj sağlayıcısı — production: yalnızca Evolution API.

Wapio modülleri (wapio_client.py vb.) repoda durur; bu dosyada devre dışı bırakıldı.
"""

from __future__ import annotations

import logging
import os

from config import get_evolution_config
from error_codes import E_WA_001, E_WA_003
from logging_setup import log_error, log_warning

# Legacy Wapio — tekrar açmak için True yapın ve aşağıdaki blokları geri yükleyin
# from config import get_wapio_config
WAPIO_INTEGRATION_ENABLED = False

logger = logging.getLogger(__name__)

PROVIDER_WAPIO = "wapio"
PROVIDER_EVOLUTION = "evolution"

# Şimdilik tüm giden WhatsApp mesajları kapalı. Tekrar açmak için True yapın.
WHATSAPP_SENDING_ENABLED = False


def get_whatsapp_provider() -> str:
    if WAPIO_INTEGRATION_ENABLED:
        raw = (os.getenv("WHATSAPP_PROVIDER") or PROVIDER_EVOLUTION).strip().lower()
        if raw in (PROVIDER_WAPIO, "wapio"):
            return PROVIDER_WAPIO
    return PROVIDER_EVOLUTION


def is_wapio_provider_active() -> bool:
    return WAPIO_INTEGRATION_ENABLED and get_whatsapp_provider() == PROVIDER_WAPIO


def welcome_message_enabled() -> bool:
    cfg = get_evolution_config()
    return bool(cfg.get("welcome_message_enabled", True))


def is_whatsapp_demo_mode() -> bool:
    if os.getenv("WHATSAPP_DEMO_MODE", "").strip().lower() in ("1", "true", "yes"):
        return True
    cfg = get_evolution_config()
    return not bool((cfg.get("instance_name") or "").strip() and (cfg.get("api_key") or "").strip())


def send_whatsapp_message(
    phone,
    message,
    retry_count=0,
    *,
    remote_jid: str | None = None,
    remote_jid_alt: str | None = None,
) -> bool:
    """Tüm giden WhatsApp mesajları — Evolution sendText."""
    if not WHATSAPP_SENDING_ENABLED:
        logger.info("WhatsApp gönderimi şimdilik kapalı — mesaj atlandı: %s", phone)
        return True

    from evolution_client import normalize_phone_for_send, send_text as evolution_send_text

    evolution_config = get_evolution_config()
    instance = (evolution_config.get("instance_name") or "").strip()
    api_key = (evolution_config.get("api_key") or "").strip()
    recipient = normalize_phone_for_send(phone)
    if not instance or not api_key:
        separator = "=" * 60
        print(f"\n{separator}")
        print("WHATSAPP MESAJI (TEST MODU — Evolution yapilandirmasi eksik)")
        print(f"Alici : {recipient}")
        print(f"{'─' * 60}")
        print(message)
        print(f"{separator}\n")
        log_warning(
            logger,
            E_WA_003,
            "Evolution api_key/instance_name eksik, mesaj terminale yazildi",
            recipient=recipient,
        )
        return False

    ok = evolution_send_text(
        recipient,
        message,
        retry_count,
        evolution_config,
        remote_jid=remote_jid,
        remote_jid_alt=remote_jid_alt,
    )
    if not ok:
        log_error(
            logger,
            E_WA_001,
            "WhatsApp mesaji gonderilemedi",
            recipient=recipient,
            jid=remote_jid or remote_jid_alt or "-",
        )
    return ok


def check_whatsapp_health() -> dict:
    from evolution_client import resolve_evolution_connection

    provider = PROVIDER_EVOLUTION
    cfg = get_evolution_config()
    api_key = (cfg.get("api_key") or "").strip()
    instance = (cfg.get("instance_name") or "").strip()
    if not api_key or not instance:
        return {
            "provider": provider,
            "healthy": False,
            "reason": "Evolution api_key veya instance_name eksik",
        }
    info = resolve_evolution_connection(cfg, instance)
    healthy = bool(info.get("connected"))
    return {
        "provider": provider,
        "healthy": healthy,
        "connection": info,
        "http_status": 200 if healthy else 503,
        "reason": None if healthy else (info.get("detail") or "WhatsApp bağlantısı yok"),
    }
