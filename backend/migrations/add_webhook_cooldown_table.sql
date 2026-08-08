-- =============================================
-- WEBHOOK COOLDOWN TABLE
-- Tarih: 2026-01-05
-- Açıklama: WhatsApp webhook cooldown kontrolü için database tablosu
-- Bu tablo worker'lar arasında cooldown kontrolünü sağlar
-- =============================================

-- Webhook cooldown tablosu (spam önleme için)
CREATE TABLE IF NOT EXISTS webhook_cooldown (
    id SERIAL PRIMARY KEY,
    phone_key VARCHAR(255) NOT NULL UNIQUE,  -- Telefon numarası veya WhatsApp ID
    last_sent_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_webhook_cooldown_phone_key ON webhook_cooldown(phone_key);
CREATE INDEX IF NOT EXISTS idx_webhook_cooldown_last_sent ON webhook_cooldown(last_sent_at);

-- Eski kayıtları temizlemek için (24 saatten eski kayıtları otomatik sil)
-- Bu işlem cleanup job'ı tarafından yapılacak

