-- =============================================
-- NOTIFICATIONS TABLE (panel ici bildirim merkezi)
-- Tarih: 2026-09-21
-- Aciklama: Sistemin kendi kendine yaptigi ama admin/sanatcinin fark
-- etmeyebilecegi degisiklikleri (ör. Google Calendar'da mesai/cakisma
-- nedeniyle geri alinan bir surukleme) panelde gorunur kilan bildirim
-- kayitlari. Tablo app.py acilisinda kendiliginden de olusturulur
-- (CREATE TABLE IF NOT EXISTS), bu dosya sifirdan kurulum/dokumantasyon
-- icindir.
-- =============================================

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    staff_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    type VARCHAR(40) NOT NULL,
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    appointment_id INTEGER REFERENCES appointments(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    read_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_staff_unread
    ON notifications(staff_id, read_at)
    WHERE read_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_notifications_staff_created
    ON notifications(staff_id, created_at DESC);
