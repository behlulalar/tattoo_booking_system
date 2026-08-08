# Wapio API — OpenAPI 3.0 v1.0.0

## Doğrulama kodu akışı

Randevu sisteminde doğrulama kodu **Wapio OTP API kullanılmaz**. Akış:

1. Kullanıcı telefon numarasını girer
2. Backend rastgele 6 haneli kod üretir ve DB'ye kaydeder
3. Kod **`POST /send-text`** ile normal WhatsApp mesajı olarak gönderilir
4. Kullanıcı kodu girer → DB'den doğrulanır

Gerekli: bağlı WhatsApp cihazı (`session_id`) + QR bağlantısı.

## Kimlik bilgileri

| Değişken | Nereden | Kullanım |
|----------|---------|----------|
| `WAPIO_API_KEY` | [my.wapio.com.tr/hesabim](https://my.wapio.com.tr/hesabim) | CreateDevice, CheckSessionStatus |
| `WAPIO_SESSION_ID` | CreateDevice yanıtı | `/send-text` header |

## Mesaj formatı (doğrulama kodu)

```
🔐 *Doğrulama Kodu*
✅ Kod: *123456*
⏳ Bu kod 120 saniye boyunca geçerlidir.
...
```

## Endpoint'ler (projede kullanılan)

| Endpoint | Kullanım |
|----------|----------|
| `POST /CreateDevice` | Cihaz + session_id |
| `POST /GetQR/{session_id}` | QR bağlantı |
| `GET /CheckSessionStatus/{session_id}` | Bağlantı kontrolü |
| `POST /UpdateWebhook` | Gelen mesaj webhook |
| `POST /send-text` | Doğrulama kodu, bildirimler, karşılama |

`/send-otp-whatsapp` bu projede **kullanılmıyor**.

## WhatsApp mesaj türleri

| Mesaj | Tetikleyici | Endpoint |
|-------|-------------|----------|
| Karşılama | Müşteri WhatsApp'tan yazar | Webhook → `/send-text` |
| Doğrulama kodu | Telefon doğrulama | `/send-text` |
| Randevu oluşturuldu | Slot seçimi / manuel randevu | `/send-text` |
| Randevu hatırlatma | Scheduler (varsayılan 1 saat önce) | `/send-text` |
| Bakım hatırlatması | Randevu tamamlandıktan sonra | `/send-text` |

Webhook URL: `{RANDEVU_URL}/api/whatsapp/webhook` veya `WAPIO_WEBHOOK_URL`.

`.env` ayarları:
- `REMINDER_HOURS_BEFORE=1` — randevudan kaç saat önce hatırlatma
- `WEBHOOK_COOLDOWN_SECONDS=86400` — aynı numaraya karşılama mesajı aralığı (24 saat)
- `AFTERCARE_REMINDER_HOURS=2` — bakım hatırlatması gecikmesi
