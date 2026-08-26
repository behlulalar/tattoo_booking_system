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
| E-GCAL-001 | Google Takvim | credentials, calendar_id |
| E-BOOK-001 | Randevu oluşmadı | slot, DB |
| E-REQ-001 | Talep / teklif | tattoo_requests |
| E-BKP-001 | Yedekleme | pg_dump, rclone |
| E-SCH-001 | Scheduler | process kilidi |
| E-UNK-001 | Kodlanmamış hata | `dosya:satır` sütunu |
| W-CFG-001 | Eksik yapılandırma | ilgili ayar |

Dosyalar: `backend/logs/app.log` (canlı), gece gzip arşiv (`app.log.YYYY-MM-DD.gz`), 90 gün.
