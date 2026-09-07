-- Off Day (time_off) Google Calendar çift yön senkronu
--
-- time_off satırları takvim etkinliğine bağlanır; kuyruk hem randevu hem
-- Off Day upsert/delete taşır.
--
-- Kullanim:
--   psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -f add_time_off_google_sync.sql
--
-- Not: google_calendar_sync.ensure_queue_table() acilista ayni DDL'i uygular.

BEGIN;

ALTER TABLE time_off
    ADD COLUMN IF NOT EXISTS google_event_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS google_etag VARCHAR(255),
    ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS google_updated_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS uq_time_off_google_event_id
    ON time_off (google_event_id)
    WHERE google_event_id IS NOT NULL;

ALTER TABLE google_calendar_queue
    ADD COLUMN IF NOT EXISTS time_off_id INTEGER;

ALTER TABLE google_calendar_queue DROP CONSTRAINT IF EXISTS gcq_payload_check;
ALTER TABLE google_calendar_queue DROP CONSTRAINT IF EXISTS google_calendar_queue_gcq_payload_check;

ALTER TABLE google_calendar_queue
    ADD CONSTRAINT gcq_payload_check CHECK (
        (
            operation = 'upsert'
            AND appointment_id IS NOT NULL
            AND time_off_id IS NULL
        )
        OR (
            operation = 'upsert'
            AND time_off_id IS NOT NULL
            AND appointment_id IS NULL
        )
        OR (
            operation = 'delete'
            AND google_event_id IS NOT NULL
        )
    );

CREATE INDEX IF NOT EXISTS idx_gcq_time_off
    ON google_calendar_queue (time_off_id)
    WHERE dead_at IS NULL AND operation = 'upsert';

COMMIT;
