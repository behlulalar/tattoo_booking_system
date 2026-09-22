-- =============================================
-- PUSH_SUBSCRIPTIONS TABLE (PWA push bildirimleri)
-- Tarih: 2026-09-22
-- Aciklama: Personelin admin panelini PWA olarak ana ekrana ekleyip
-- bildirimlere izin verdiginde tarayicidan alinan Web Push aboneligini
-- (endpoint + sifreleme anahtarlari) tutar. Bir personelin birden fazla
-- cihazi ayri ayri abone olabilir. Tablo app.py acilisinda kendiliginden
-- de olusturulur (CREATE TABLE IF NOT EXISTS), bu dosya sifirdan
-- kurulum/dokumantasyon icindir.
-- =============================================

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id SERIAL PRIMARY KEY,
    staff_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMP,
    UNIQUE (endpoint)
);

CREATE INDEX IF NOT EXISTS idx_push_subscriptions_staff_id
    ON push_subscriptions(staff_id);
