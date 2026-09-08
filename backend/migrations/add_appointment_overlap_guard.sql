-- Çakışan randevuları veritabanı seviyesinde imkânsız kılar.
--
-- Neden gerekli:
--   Mevcut appointments_staff_date_time_uidx yalnızca birebir aynı
--   (staff_id, appointment_date, appointment_time) üçlüsünü engelliyor.
--   120 dakikalık bir randevunun ikinci saati korumasız kalıyordu:
--     A: 14:00 + 120 dk  (14:00-16:00)
--     B: 15:00 +  60 dk  (15:00-16:00)   <-- unique index bunu kabul ediyor
--
--   Uygulama tarafında lock_staff_day() ile de sıraya alınıyor, ama bu kısıt
--   son savunma hattı: admin paneli, müşteri teklif linki ve Google Takvim
--   içe aktarımı dahil BÜTÜN yollar için geçerli.
--
-- ÖNEMLİ: Bu dosyayı çalıştırmadan ÖNCE mevcut çakışmaları temizleyin.
--         Çakışan kayıt varsa ALTER TABLE hata verir (bu istenen davranıştır;
--         veri sessizce bozulmasın). Tespit için:
--         psql -f migrations/check_appointment_overlaps.sql

BEGIN;

-- gist içinde staff_id gibi skaler kolonları kullanabilmek için gerekli.
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE appointments
  DROP CONSTRAINT IF EXISTS appointments_no_overlap;

-- make_interval kullanılıyor: IMMUTABLE olmayan bir ifade EXCLUDE içinde
-- kabul edilmez ('X minutes'::interval cast'i bu garantiyi vermez).
ALTER TABLE appointments
  ADD CONSTRAINT appointments_no_overlap
  EXCLUDE USING gist (
    staff_id WITH =,
    tsrange(
      (appointment_date + appointment_time)::timestamp,
      (appointment_date + appointment_time)::timestamp
        + make_interval(mins => duration_minutes),
      '[)'
    ) WITH &&
  )
  WHERE (status IS DISTINCT FROM 'cancelled');

COMMIT;
