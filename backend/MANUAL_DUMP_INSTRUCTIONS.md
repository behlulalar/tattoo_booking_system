# Manuel Veritabanı Dump ve Restore Komutları

## 1. Yerel Veritabanından Dump Alma

Yerel veritabanınızdan dump almak için:

```bash
# .env dosyasındaki bilgileri kullanarak
pg_dump -h localhost -p 5432 -U postgres -d randevu_db -F c -f local_dump.dump

# Veya SQL formatında (daha okunabilir)
pg_dump -h localhost -p 5432 -U postgres -d randevu_db -f local_dump.sql --no-owner --no-acl
```

Parametreler:
- `-h`: Host (localhost)
- `-p`: Port (5432)
- `-U`: Kullanıcı adı
- `-d`: Veritabanı adı
- `-f`: Çıktı dosya yolu
- `--no-owner`: Owner bilgilerini ekleme (sunucuda farklı user olabilir)
- `--no-acl`: ACL bilgilerini ekleme
- `-F c`: Custom format (binary, daha küçük dosya)

Şifre sorarsa, .env dosyasındaki `DATABASE_PASSWORD` değerini kullanabilir veya:
```bash
export PGPASSWORD='şifreniz'
pg_dump -h localhost -p 5432 -U postgres -d randevu_db -f local_dump.sql --no-owner --no-acl
```

## 2. Sunucuya Dump Yükleme

### Önce sunucuda veritabanını oluşturun (yoksa):

```bash
psql -h sunucu_host -p 5432 -U kullanici_adi -d postgres -c "CREATE DATABASE randevu_db;"
```

### Custom format (binary) dump'ı restore etme:

```bash
pg_restore -h sunucu_host -p 5432 -U kullanici_adi -d randevu_db -v local_dump.dump
```

### SQL format dump'ı restore etme:

```bash
psql -h sunucu_host -p 5432 -U kullanici_adi -d randevu_db -f local_dump.sql
```

## 3. Tek Komutla Dump Alıp Sunucuya Yükleme (SSH ile)

Eğer sunucuya SSH erişiminiz varsa:

```bash
# Yerel'den dump alıp direkt sunucuya aktar
pg_dump -h localhost -U postgres -d randevu_db --no-owner --no-acl | \
  ssh kullanici@sunucu_host "psql -h localhost -U kullanici_adi -d randevu_db"
```

## Örnek Komutlar (.env'den bilgileri kullanarak)

```bash
# Terminal'de .env dosyasını yükle
export $(cat backend/.env | xargs)

# Dump al
pg_dump -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME \
  -f local_dump.sql --no-owner --no-acl

# Sunucuya yükle (sunucu bilgilerini manuel girin)
pg_restore -h SUNUCU_HOST -p 5432 -U SUNUCU_USER -d SUNUCU_DB_NAME -v local_dump.sql
```

## Notlar

- Büyük veritabanları için `-F c` (custom format) kullanın, daha hızlıdır
- `--no-owner --no-acl` parametreleri sunucuda farklı kullanıcılar olduğunda gereklidir
- Şifre sorarsa `PGPASSWORD` environment variable'ını kullanabilirsiniz
- Dump dosyası büyükse, sıkıştırarak aktarabilirsiniz:
  ```bash
  pg_dump ... | gzip > dump.sql.gz
  gunzip < dump.sql.gz | psql ...
  ```

