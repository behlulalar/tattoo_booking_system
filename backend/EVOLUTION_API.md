# Evolution API entegrasyonu

WhatsApp sağlayıcısı varsayılan olarak **Evolution API** ([evolution-foundation/evolution-api](https://github.com/evolution-foundation/evolution-api)). Wapio kodu repoda durur; `WHATSAPP_PROVIDER=wapio` ile tekrar açılabilir.

## Ortam değişkenleri

| Değişken | Açıklama |
|----------|----------|
| `WHATSAPP_PROVIDER` | `evolution` (varsayılan) veya `wapio` |
| `EVOLUTION_API_URL` | Evolution sunucusu (ör. `http://127.0.0.1:8080`) |
| `EVOLUTION_API_KEY` | Evolution `.env` içindeki global `AUTHENTICATION_API_KEY` |
| `EVOLUTION_INSTANCE_NAME` | Baileys instance adı (ör. `roof-tattoo`) |
| `WHATSAPP_WEBHOOK_URL` | Opsiyonel tam webhook URL (Wapio/Evolution ortak) |
| `WHATSAPP_DEMO_MODE` | `true` → OTP `123456`, mesaj gönderilmez |

Admin panel ayarları `backend/evolution_settings.json` dosyasına da yazılır.

## Akış (Wapio ile aynı işlevler)

| İşlev | Evolution endpoint |
|--------|---------------------|
| Instance oluştur | `POST /instance/create` |
| QR / bağlan | `GET /instance/connect/{instance}` |
| Bağlantı durumu | `GET /instance/connectionState/{instance}` |
| Metin mesajı (OTP, bildirimler) | `POST /message/sendText/{instance}` |
| Webhook | `POST /webhook/set/{instance}` |

Kimlik doğrulama: HTTP header **`apikey`**.

Webhook URL (randevu backend): `{RANDEVU_URL}/api/whatsapp/webhook`  
Evolution event: `MESSAGES_UPSERT` (gelen mesaj → karşılama).

## Health check

```bash
curl http://127.0.0.1:3000/api/health/whatsapp
```

Wapio health yalnızca `WHATSAPP_PROVIDER=wapio` iken anlamlıdır.

## Evolution sunucusunu çalıştırma (özet)

Docker:

```bash
docker pull evoapicloud/evolution-api:latest
docker run -p 8080:8080 --env-file .env evoapicloud/evolution-api:latest
```

Detaylar: [Evolution API README](https://github.com/evolution-foundation/evolution-api).
