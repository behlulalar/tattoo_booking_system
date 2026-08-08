-- appointments tablosunu tamamen temizle
-- DİKKAT: Bu işlem geri alınamaz!

TRUNCATE TABLE appointments CASCADE;

-- Sonucu görmek için
SELECT COUNT(*) as remaining_appointments FROM appointments;
