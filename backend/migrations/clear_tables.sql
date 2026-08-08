-- Çoklu tablo temizleme scripti
-- DİKKAT: Bu işlem geri alınamaz!
-- Temizlenecek tablolar: appointments, income_adjustments, customers, reviews

-- Sıralama önemli: Önce bağımlı tablolar (reviews, income_adjustments), sonra customers

-- 1. Reviews tablosunu temizle (appointments zaten temizlendi ama yine de)
TRUNCATE TABLE reviews CASCADE;

-- 2. Income adjustments tablosunu temizle
TRUNCATE TABLE income_adjustments CASCADE;

-- 3. Customers tablosunu temizle (appointments zaten temizlendi)
TRUNCATE TABLE customers CASCADE;

-- 4. Sonuçları göster
SELECT 
    (SELECT COUNT(*) FROM appointments) as appointments_count,
    (SELECT COUNT(*) FROM income_adjustments) as income_adjustments_count,
    (SELECT COUNT(*) FROM customers) as customers_count,
    (SELECT COUNT(*) FROM reviews) as reviews_count;
