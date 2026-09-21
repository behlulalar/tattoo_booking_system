-- =============================================
-- ERROR NOTIFICATION COOLDOWN TABLE
-- Tarih: 2026-09-21
-- Açıklama: Kritik hata e-postaları için worker'lar arası paylaşımlı
-- rate-limit tablosu. error_notifier.py artık bu tabloyu kullanarak
-- aynı hata için saatte en fazla 1 e-posta gönderilmesini garanti eder
-- (önceden her gunicorn worker'ının kendi bellek içi kaydı vardı,
-- bu da aynı hata için worker sayısı kadar mail gidebilmesine yol
-- açıyordu).
-- =============================================

CREATE TABLE IF NOT EXISTS error_notification_cooldown (
    error_key VARCHAR(255) PRIMARY KEY,
    last_sent_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_error_notification_cooldown_last_sent
    ON error_notification_cooldown(last_sent_at);
