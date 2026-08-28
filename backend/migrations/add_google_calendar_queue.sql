-- Google Takvim senkron kuyrugu (outbox) + mukerrer etkinlik korumasi
--
-- Neden: senkron istek yolunda dogrudan cagriliyordu. Google hata verdiginde
-- (veya randevu satiri silindikten sonra) is kayboluyor ve telafi edilemiyordu.
-- Artik her takvim isi randevu transaction'i ile ayni commit icinde kuyruga
-- yazilir; arka plan isi kuyrugu tekrar denemeli olarak bosaltir.
--
-- Kullanim:
--   psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -f add_google_calendar_queue.sql
--
-- Not: app.py acilista ensure_google_calendar_queue_table() ile ayni tabloyu
-- olusturur, bu dosya migration kaydi ve elle kurulum icindir.

BEGIN;

CREATE TABLE IF NOT EXISTS google_calendar_queue (
    id BIGSERIAL PRIMARY KEY,
    operation VARCHAR(16) NOT NULL,
    appointment_id INTEGER,
    google_event_id VARCHAR(255),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dead_at TIMESTAMPTZ,
    CONSTRAINT gcq_operation_check CHECK (operation IN ('upsert', 'delete')),
    CONSTRAINT gcq_payload_check CHECK (
        (operation = 'upsert' AND appointment_id IS NOT NULL)
        OR (operation = 'delete' AND google_event_id IS NOT NULL)
    )
);

-- Bekleyen isi sirayla cekmek icin (FOR UPDATE SKIP LOCKED sorgusu)
CREATE INDEX IF NOT EXISTS idx_gcq_pending
    ON google_calendar_queue (next_attempt_at, id)
    WHERE dead_at IS NULL;

-- Ayni randevu icin biriken upsert islerini tek seferde birlestirmek icin
CREATE INDEX IF NOT EXISTS idx_gcq_appointment
    ON google_calendar_queue (appointment_id)
    WHERE dead_at IS NULL AND operation = 'upsert';

-- Kalici basarisiz isleri operatorun gormesi icin
CREATE INDEX IF NOT EXISTS idx_gcq_dead
    ON google_calendar_queue (dead_at)
    WHERE dead_at IS NOT NULL;

-- Ayni Google etkinliginin iki randevuya baglanmasini engelle.
-- Eski yaris durumlarindan mukerrer kayit varsa eskisinin baglantisini kopar;
-- boylece sonraki senkronda kendisine yeni etkinlik olusturulur.
UPDATE appointments a
   SET google_event_id = NULL
 WHERE a.google_event_id IS NOT NULL
   AND EXISTS (
       SELECT 1
         FROM appointments b
        WHERE b.google_event_id = a.google_event_id
          AND b.id > a.id
   );

CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_google_event_id
    ON appointments (google_event_id)
    WHERE google_event_id IS NOT NULL;

COMMIT;
