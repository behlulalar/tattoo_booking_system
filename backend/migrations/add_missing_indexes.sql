-- =============================================
-- Missing Index'leri Ekle
-- Tarih: 2026-01-04
-- Açıklama: Performans iyileştirmesi için eksik index'leri ekler
-- =============================================

-- 1. Status kolonu için index (sık kullanılan sorgular için)
CREATE INDEX IF NOT EXISTS idx_appointments_status 
  ON appointments(status);

-- 2. Composite index: staff_id + appointment_date + status
-- Bu index özellikle randevu listeleme sorgularında çok faydalı
CREATE INDEX IF NOT EXISTS idx_appointments_staff_date_status 
  ON appointments(staff_id, appointment_date, status);

-- 3. Composite index: appointment_date + status
-- Tarih bazlı sorgular için
CREATE INDEX IF NOT EXISTS idx_appointments_date_status 
  ON appointments(appointment_date, status);

-- Index'lerin oluşturulduğunu kontrol et
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'appointments'
  AND indexname IN (
    'idx_appointments_status',
    'idx_appointments_staff_date_status',
    'idx_appointments_date_status'
  )
ORDER BY indexname;

