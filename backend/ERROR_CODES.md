# Hata kodları

Log satırı:

`tarih | seviye | KOD | dosya:satır fonksiyon | ne oldu | ayrıntı`

Örnek:

`grep E-WA-001 /opt/roof_tattoo/backend/logs/app.log`

| Kod | Anlam | İlk bakılacak yer |
|---|---|---|
| E-DB-001 | DB havuzu açılamadı | `.env` DATABASE_*, SSL |
| E-DB-002 | Bağlantı alınamadı / havuz doldu | PostgreSQL, yoğunluk |
| E-DB-003 | Bağlantı havuza dönmedi | pool / kopuk socket |
| E-DB-004 | SQL / transaction | satırdaki fonksiyon |
| E-AUTH-001 | Giriş / oturum | telefon, şifre, token |
| E-WA-001 | WhatsApp gönderilemedi | Evolution instance, API key |
| E-WA-002 | Webhook hatası | gelen event, traceback |
| E-WA-003 | Evolution ayarı eksik | admin WhatsApp sayfası |
| E-WA-004 | OTP / hatırlatma gönderilemedi | Evolution bağlantısı |
| E-GCAL-001 | Google Takvim yazma/silme (tekrar denenecek) | credentials, calendar_id |
| E-GCAL-002 | Senkron kuyruğu okunamadı/yazılamadı | `google_calendar_queue` tablosu |
| E-GCAL-003 | Takvim işi bırakıldı (kalıcı) | kuyrukta `dead_at` dolu satır |
| E-BOOK-001 | Randevu oluşmadı | slot, DB |
| E-REQ-001 | Talep / teklif | tattoo_requests |
| E-BKP-001 | Yedekleme | pg_dump, rclone |
| E-SCH-001 | Scheduler | process kilidi |
| E-UNK-001 | Kodlanmamış hata | `dosya:satır` sütunu |
| W-CFG-001 | Eksik yapılandırma | ilgili ayar |

Dosyalar: `backend/logs/app.log` (canlı), gece gzip arşiv (`app.log.YYYY-MM-DD.gz`), 90 gün.

## Takvim senkronu bekleyen/bırakılan işler

Takvim işleri `google_calendar_queue` tablosunda tutulur; başarısız olanlar artan
aralıklarla tekrar denenir, hakkı bitenler `dead_at` ile işaretlenir.

```sql
-- bekleyen ve bırakılan işler
SELECT id, operation, appointment_id, google_event_id, attempts, next_attempt_at, dead_at, last_error
  FROM google_calendar_queue ORDER BY dead_at NULLS FIRST, id;

-- bırakılmış bir işi tekrar denemeye almak
UPDATE google_calendar_queue
   SET dead_at = NULL, attempts = 0, next_attempt_at = NOW()
 WHERE id = <id>;
```

Elle Google etkinlikleri başlıkta sanatçı adı eşleşirse `source=google` randevu olur
(WhatsApp yok; saat o sanatçıda dolu). Eşleşmeyen saatli etkinlik herkesi kilitlemez.
Tüm-gün / yinelenen etkinlikler `google_external_busy` tablosuna yazılır.
Bizim etkinlikler `extendedProperties.private.origin=roof` ile tanınır.
