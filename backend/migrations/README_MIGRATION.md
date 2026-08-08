# Database Migration - Webhook Cooldown Tablosu

## Problem
Gunicorn ile 4 worker kullanıldığında:
- Her worker'ın ayrı memory'si olduğu için cooldown kontrolü worker'lar arasında paylaşılmıyordu
- WhatsApp webhook mesajları birden fazla kez gönderiliyordu
- Randevu hatırlatma mesajları da birden fazla kez gönderiliyordu

## Çözüm
- Memory-based cooldown yerine database tabanlı cooldown sistemi
- Worker'lar arasında cooldown bilgisi database üzerinden paylaşılıyor
- Scheduler için PostgreSQL advisory lock kullanılıyor

## Migration Dosyaları
1. `add_webhook_cooldown_table.sql` - Webhook cooldown tablosunu oluşturur
2. `add_verification_codes_table.sql` - Verification codes tablosunu oluşturur (worker'lar arası paylaşım için)

## Adım Adım Uygulama

### 1. Kodları Sunucuya Yükle

**ÖNCE bu adımı yapmalısınız!** Local'deki değişiklikleri sunucuya yükleyin:

```bash
# Local'de proje klasöründe çalıştırın
cd /Users/muhammedbehlulalar/Desktop/randevu
./sync_to_server.sh
```

Bu script şunları yapar:
- ✅ Backend dosyalarını yükler (app.py, migrations/ dahil)
- ✅ Frontend dosyalarını yükler
- ⚠️ Backend servisini restart eder (AMA migration'dan önce olduğu için hata verebilir)

### 2. Migration'ı Uygula

**Kodları yükledikten SONRA** migration'ı uygulayın:

```bash
# Sunucuya bağlan
ssh root@88.209.248.141

# Veritabanına bağlan ve migration'ı çalıştır
cd /opt/randevu/backend

# .env dosyasını yorumları filtreleyerek yükle
set -a
source <(grep -v '^#' .env | grep -v '^$')
set +a

# Migration'ı çalıştır
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -f migrations/add_webhook_cooldown_table.sql
```

**Alternatif (Manuel Değişkenler):**
Eğer yukarıdaki yöntem çalışmazsa, değişkenleri manuel olarak ayarlayın:

```bash
cd /opt/randevu/backend

# .env dosyasından değerleri oku (yorumları atlayarak)
DATABASE_HOST=$(grep DATABASE_HOST .env | cut -d '=' -f2 | tr -d ' ')
DATABASE_PORT=$(grep DATABASE_PORT .env | cut -d '=' -f2 | tr -d ' ')
DATABASE_USER=$(grep DATABASE_USER .env | cut -d '=' -f2 | tr -d ' ')
DATABASE_NAME=$(grep DATABASE_NAME .env | cut -d '=' -f2 | tr -d ' ')
DATABASE_PASSWORD=$(grep DATABASE_PASSWORD .env | cut -d '=' -f2 | tr -d ' ')

# Şifreyi environment variable olarak ayarla
export PGPASSWORD=$DATABASE_PASSWORD

# Migration'ı çalıştır
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -f migrations/add_webhook_cooldown_table.sql
```

**Alternatif (interactive):**
```bash
cd /opt/randevu/backend
export $(cat .env | xargs)
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME

# psql içinde:
\i migrations/add_webhook_cooldown_table.sql
SELECT * FROM webhook_cooldown LIMIT 5;
\d webhook_cooldown
\q
```

### 3. Backend'i Yeniden Başlat

Migration uygulandıktan sonra backend'i restart edin:

```bash
systemctl restart randevu-backend
systemctl status randevu-backend
```

## Değişiklikler

### 1. Webhook Cooldown
- **Öncesi**: Memory-based dictionary (`webhook_sent_messages`)
- **Sonrası**: Database tablosu (`webhook_cooldown`)
- **Fayda**: Worker'lar arası cooldown paylaşımı

### 2. Scheduler Lock
- **Öncesi**: Sadece file lock (`fcntl`)
- **Sonrası**: File lock + PostgreSQL advisory lock
- **Fayda**: Daha güvenilir, worker'lar arası scheduler kontrolü

### 3. Verification Codes
- **Öncesi**: Memory-based dictionary (`verification_codes`)
- **Sonrası**: Database tablosu (`verification_codes`)
- **Fayda**: Worker'lar arası kod paylaşımı, doğrulama kodları her worker'da çalışır

### 4. Randevu Hatırlatmaları
- **Değişiklik yok**: Zaten `SELECT FOR UPDATE SKIP LOCKED` kullanılıyordu
- **Not**: Bu mekanizma worker'lar arası çalışıyor

## Test

Migration'dan sonra:

1. **Backend'i yeniden başlat**:
```bash
systemctl restart randevu-backend
```

2. **Log'ları kontrol et**:
```bash
tail -f /opt/randevu/backend/app.log
# "✅ Scheduler başlatıldı" mesajını kontrol et
```

3. **Test mesajı gönder**:
- WhatsApp'tan test numarasına mesaj gönder
- Sadece 1 kez karşılama mesajı gelmeli
- 24 saat içinde tekrar mesaj gönderilmemeli

4. **Randevu hatırlatması test et**:
- Randevu oluştur (1 saat sonrası için)
- 5 dakika içinde hatırlatma mesajı gelmeli
- Sadece 1 kez gelmeli

## Geri Alma (Rollback)

Gerekirse tabloları silebilirsiniz:

```sql
DROP TABLE IF EXISTS webhook_cooldown;
DROP TABLE IF EXISTS verification_codes;
```

Ancak bu durumda kod da eski haline döndürülmeli (önerilmez).

