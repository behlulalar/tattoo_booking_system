-- =============================================
-- MUSTERI ONAY KAYITLARI (KVKK + Ticari Elektronik Ileti)
-- Tarih: 2026-09-22
-- Aciklama: Randevu alma akisinin ilk adimindaki KVKK aydinlatma metni
-- onayi (zorunlu) ve elektronik ileti (pazarlama) onayi (istege bagli)
-- icin musterinin ne zaman ve ne onayladigini ispatlanabilir sekilde
-- saklar (KVKK m.11 kapsaminda ispat yukumlulugu).
-- =============================================

ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS kvkk_accepted_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS marketing_consent BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS marketing_consent_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS age_confirmed_at TIMESTAMP;
