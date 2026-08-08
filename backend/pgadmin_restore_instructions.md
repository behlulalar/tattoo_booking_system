# pgAdmin ile SQL Dump Yükleme

## Yöntem 1: Query Tool ile (Önerilen - Basit)

1. **pgAdmin'i açın** ve sunucuya bağlanın

2. **Veritabanınızı seçin:**
   - Sol tarafta Servers > PostgreSQL > Databases altında
   - Yeni oluşturduğunuz veritabanına sağ tıklayın
   - **"Query Tool"** seçin

3. **SQL dosyasını açın:**
   - Query Tool açıldıktan sonra, üst menüden:
     - **File > Open** (veya Ctrl+O / Cmd+O)
   - `dump_2025-12-31_19-05-57.sql` dosyasını seçin

4. **Çalıştırın:**
   - Tüm SQL komutları Query Tool'da görünecek
   - **Execute** butonuna tıklayın (veya F5 tuşuna basın)
   - İşlem tamamlanana kadar bekleyin

5. **Sonuç:**
   - Alt kısımda "Successfully completed" mesajını göreceksiniz
   - Hata varsa kırmızı mesajlar görünecek

## Yöntem 2: psql Komut Satırı (Alternatif)

Eğer pgAdmin'de sorun yaşarsanız, terminal'den:

```bash
# Mac/Linux için
psql -h localhost -p 5432 -U kullanici_adi -d veritabani_adi -f backend/dump_2025-12-31_19-05-57.sql

# Veya pgAdmin'in psql'i varsa
psql -h SUNUCU_IP -p 5432 -U kullanici_adi -d veritabani_adi -f /path/to/dump_2025-12-31_19-05-57.sql
```

## Notlar

- **Veritabanı boş olmalı:** Dump dosyası `--clean` parametresiyle oluşturulduysa, mevcut tabloları silebilir. Boş bir veritabanına yükleyin.
  
- **Hata alırsanız:** 
  - Veritabanının boş olduğundan emin olun
  - Kullanıcının gerekli yetkilere sahip olduğunu kontrol edin
  - Hata mesajlarını okuyun - genellikle hangi satırda sorun olduğunu gösterir

- **Büyük dosyalar için:**
  - Query Tool bazen timeout verebilir
  - Bu durumda terminal'den `psql` komutunu kullanmak daha güvenilirdir

