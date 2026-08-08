-- =============================================
-- VERIFICATION CODES TABLE
-- Tarih: 2026-01-05
-- Açıklama: Doğrulama kodlarını worker'lar arasında paylaşmak için database tablosu
-- =============================================

-- Verification codes tablosu
CREATE TABLE IF NOT EXISTS verification_codes (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(255) NOT NULL,
    code VARCHAR(10) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_verification_codes_phone ON verification_codes(phone);
CREATE INDEX IF NOT EXISTS idx_verification_codes_expires ON verification_codes(expires_at);

-- Cleanup job'ı tarafından süresi dolan kayıtlar silinecek

