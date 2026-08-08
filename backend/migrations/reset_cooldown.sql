-- =============================================
-- RESET WEBHOOK COOLDOWN
-- Tarih: 2026-01-05
-- Açıklama: Sadece DB'deki bekleme kayıtlarını siler.
-- WEBHOOK_COOLDOWN_SECONDS (.env, varsayılan 86400 = 24 saat) DEĞİŞMEZ.
-- =============================================

-- Aktif süre sayan tüm kayıtları sıfırla (24 saat kuralı aynı kalır)
DELETE FROM webhook_cooldown;

-- Veya sadece belirli bir numara için:
-- DELETE FROM webhook_cooldown WHERE phone_key = '82863491944495@lid';

