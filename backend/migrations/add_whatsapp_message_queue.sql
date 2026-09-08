-- Kalıcı WhatsApp retry kuyruğu.
--
-- Neden gerekli:
--   send_wapio_message tek seferlik deneme yapıyordu; Evolution API anlık
--   kapalıysa/hata dönüyorsa teklif linki, randevu onayı, iptal bildirimi
--   gibi tekrar denenmeyen mesajlar kalıcı olarak kayboluyordu.
--
-- NOT: Bu tablo backend/app.py içindeki ensure_whatsapp_queue_table() ile
-- uygulama her başladığında otomatik (varsa dokunmadan) oluşturulur — bu
-- dosya yalnızca dokümantasyon/manuel kurulum amaçlıdır.

CREATE TABLE IF NOT EXISTS whatsapp_message_queue (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(40) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 6,
    next_attempt_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_queue_pending
ON whatsapp_message_queue (next_attempt_at)
WHERE status = 'pending';
