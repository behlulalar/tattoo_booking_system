-- Google Calendar: structural identity, soft delete, external busy, inbound sync state.
BEGIN;

ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS google_etag VARCHAR(255);

ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS google_updated_at TIMESTAMPTZ;

ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR(255);

ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP;

-- Cancelled rows must not block the same staff/date/time for a new booking.
DROP INDEX IF EXISTS appointments_staff_date_time_uidx;
CREATE UNIQUE INDEX appointments_staff_date_time_uidx
  ON appointments (staff_id, appointment_date, appointment_time)
  WHERE status IS DISTINCT FROM 'cancelled';

CREATE TABLE IF NOT EXISTS google_external_busy (
    id BIGSERIAL PRIMARY KEY,
    calendar_id VARCHAR(255) NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    google_event_id VARCHAR(255),
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gcal_external_busy_span
    ON google_external_busy (calendar_id, start_at, end_at);

CREATE TABLE IF NOT EXISTS google_calendar_sync_state (
    calendar_id VARCHAR(255) PRIMARY KEY,
    events_sync_token TEXT,
    last_busy_at TIMESTAMPTZ,
    last_events_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
