-- Nihal Karagöz → Berke Uzun
-- Kayıt silinmez: mevcut talepler ve randevular aynı staff_id'de kalır.

UPDATE artists
SET name = 'Berke Uzun'
WHERE name ILIKE '%nihal%'
   OR name ILIKE '%karagöz%'
   OR name ILIKE '%karagoz%';
