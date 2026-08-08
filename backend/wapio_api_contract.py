"""
Wapio OpenAPI 3.0 v1.0.0 — my.wapio.com.tr
Kaynak: resmi OpenAPI export (2026-06)
"""

from __future__ import annotations

CONTRACT_VERSION = "2026-06-12-openapi-1.0.0"
CONTRACT_SOURCE = "Wapio REST API Integration OpenAPI 3.0.0"
OPENAPI_INFO_VERSION = "1.0.0"
DEFAULT_BASE_URL = "https://my.wapio.com.tr"
API_KEY_SOURCE_URL = "https://my.wapio.com.tr/hesabim"

ENDPOINTS = {
    "create_device": {
        "label": "Cihaz oluştur",
        "path": "/CreateDevice",
        "method": "POST",
        "auth": "form_api_key",
        "content_type": "application/x-www-form-urlencoded",
        "required_fields": ["deviceName", "api_key"],
    },
    "get_qr": {
        "label": "QR kod al",
        "path": "/GetQR/{session_id}",
        "method": "POST",
        "auth": "query_api_key_form_body",
        "required_query": ["api_key"],
        "required_fields": ["deviceName"],
    },
    "check_session_status": {
        "label": "Oturum durumu",
        "path": "/CheckSessionStatus/{session_id}",
        "method": "GET",
        "auth": "query_api_key",
        "required_query": ["api_key"],
        "expect_status_any_of": [200, 401, 403],
    },
    "update_webhook": {
        "label": "Webhook güncelle",
        "path": "/UpdateWebhook",
        "method": "POST",
        "auth": "form_api_key",
        "required_fields": ["api_key", "session_id", "webhook", "deviceName"],
    },
    "send_text": {
        "label": "Metin mesajı",
        "path": "/send-text",
        "method": "POST",
        "auth": "header_session_id",
        "required_headers": ["session_id"],
        "body_example": {
            "phone": "905551234567",
            "is_group": False,
            "is_channel": False,
            "data": {"message": "...", "messageId": ""},
        },
        "expect_status_any_of": [200, 400, 422],
    },
    "send_otp_whatsapp": {
        "label": "WhatsApp OTP",
        "path": "/send-otp-whatsapp",
        "method": "POST",
        "auth": "header_domain_key",
        "required_headers": ["domain_key"],
        "body_example": {"phone": "905551234567", "otp_code": "123456"},
        "expect_status_any_of": [200, 400, 401, 408],
    },
    "check_number": {
        "label": "Numara WhatsApp'ta mı",
        "path": "/CheckNumber",
        "method": "GET",
        "auth": "header_session_id",
        "required_headers": ["session_id"],
        "required_query": ["number"],
        "probe": "optional",
    },
}

# OpenAPI'de yok — eski entegrasyon, kullanılmamalı
DEPRECATED_ENDPOINTS = ["GetContact", "/status", "/instance/status"]

WEBHOOK_INBOUND_EVENTS = ["onmessage", "new_message", ""]
WEBHOOK_IGNORE_EVENTS = ["onack", "onpresencechanged", "onstatuschanged"]

SESSION_CONNECTED_HINTS = ["connected", "open", "authenticated", "ready", "working", "online"]
SESSION_DISCONNECTED_HINTS = [
    "disconnected", "not connected", "session not found", "session expired",
    "connection lost", "no session", "invalid session", "waiting_qr", "scan_qr",
    "qr", "pairing", "unpaired", "logged out", "logout", "close", "closed",
    "offline", "not authenticated", "unlink", "device removed",
]
# API yanıtındaki genel "success" oturum bağlı demek değildir — connected ipuçlarına dahil edilmez.
SESSION_CONNECTED_EXACT = frozenset(SESSION_CONNECTED_HINTS)
