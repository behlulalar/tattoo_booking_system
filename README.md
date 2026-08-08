# Tattoo Booking System

Dövme stüdyoları için uçtan uca **talep → teklif → slot seçimi → randevu** platformu. Müşteri arayüzü, sanatçı/admin paneli, WhatsApp bildirimleri (Evolution API), sadakat puanları ve gelir raporları tek repoda.

**Örnek canlı kurulum:** [Roof Tattoo Gallery](https://tattoo.roof.behlulalar.online)

---

## Özellikler

### Müşteri

- Sanatçı seçimi, dövme talebi (bölge, tarz, boyut, referans görsel)
- Telefon doğrulama — **WhatsApp OTP** (klavye uyumlu mesaj formatı)
- Sadakat indirim kodu doğrulama
- Teklif linki ile **30 dk slot** seçimi (`slot-select.html`)
- Müşteri paneli: talepler, randevular, iptal, puan geçmişi

### Sanatçı & yönetim (admin panel)

- Dashboard, takvim, randevu durumları (onay / iptal / tamamlandı)
- **Süre belirle & link gönder** — teklif + WhatsApp
- Manuel randevu, mesai / izin günleri
- Sanatçıya özel dövme tarzları ve fiyat tahmini
- **Özel bölge** — hassas bölgeler için gün/saat kısıtı
- Gelir raporu, manuel gelir/gider (super admin)
- Personel yönetimi, site ayarları

### WhatsApp (Evolution API)

- OTP, talep alındı, teklif linki, randevu bildirimleri
- Randevu hatırlatması ve bakım kremi hatırlatması (zamanlayıcı)
- Gelen mesajda isteğe bağlı **karşılama mesajı** (panelden aç/kapa, 24 saat cooldown)

### Opsiyonel entegrasyonlar

- **Google Calendar** — randevu oluşunca/güncellenince senkron
- **PostgreSQL** yedekleme (gece cron)
- Health uçları (`/api/health`, WhatsApp bağlantı durumu)

> Wapio modülleri repoda durur; production varsayılanı **Evolution API**. Ayrıntı: [`backend/EVOLUTION_API.md`](backend/EVOLUTION_API.md)

---

## Teknoloji

| Katman | Stack |
|--------|--------|
| Backend | Python 3, Flask, Gunicorn, APScheduler |
| Veritabanı | PostgreSQL |
| Frontend | Statik HTML/CSS/JS |
| Mesajlaşma | Evolution API (Baileys) |
| Auth | JWT (admin + müşteri) |

---

## Proje yapısı

```
tattoo_booking_system/
├── backend/           # Flask API, migrations, Evolution client
├── frontend/          # Müşteri sitesi, admin, slot seçimi
├── deploy/            # rsync, nginx örnekleri, sunucu scriptleri
├── DEPLOY_SERVER_GUIDE.md
└── README.md
```

---

## Hızlı başlangıç (geliştirme)

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env içinde DATABASE_* ve isteğe bağlı EVOLUTION_* doldur
python3 app.py
```

Varsayılan API: `http://127.0.0.1:3000`

### 2. Veritabanı

```bash
createdb tattoo_db
psql -d tattoo_db -f backend/migrations/bootstrap_tattoo_db.sql
```

### 3. Frontend

```bash
cd frontend
python3 -m http.server 8000
```

| Sayfa | URL |
|-------|-----|
| Müşteri | http://127.0.0.1:8000/index.html |
| Slot seçimi | http://127.0.0.1:8000/slot-select.html?token=… |
| Admin | http://127.0.0.1:8000/sp-admin-x7k.html |

API adresini değiştirmek için tarayıcı konsolunda:

```js
localStorage.setItem('API_BASE_URL', 'http://127.0.0.1:3000');
```

### 4. Sağlık kontrolü

```bash
curl http://127.0.0.1:3000/api/health
curl http://127.0.0.1:3000/api/health/whatsapp
```

---

## Production

Sunucuya güvenli kurulum: [`DEPLOY_SERVER_GUIDE.md`](DEPLOY_SERVER_GUIDE.md)

Özet: kod `rsync` → `deploy/fix-roof-only-on-server.sh` → systemd (`roof-tattoo-backend`) + nginx.

**Asla repoya commit etmeyin:** `backend/.env`, `credentials/google-calendar.json`, `evolution_settings.json` (`.gitignore` ile hariç tutulur).

---

## Ortam değişkenleri (özet)

| Değişken | Açıklama |
|----------|----------|
| `DATABASE_*` | PostgreSQL bağlantısı |
| `RANDEVU_URL` | Site kök URL (linkler, webhook) |
| `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE_NAME` | WhatsApp |
| `GOOGLE_CALENDAR_ENABLED`, `GOOGLE_CALENDAR_ID` | Takvim (opsiyonel) |
| `WEBHOOK_COOLDOWN_SECONDS` | Karşılama mesajı tekrar süresi (varsayılan 86400) |

Tam liste: [`backend/.env.example`](backend/.env.example)

---

## Lisans

MIT — ayrıntılar için [`LICENSE`](LICENSE).

---

## Katkı

Issue ve pull request’ler GitHub üzerinden: [behlulalar/tattoo_booking_system](https://github.com/behlulalar/tattoo_booking_system)
