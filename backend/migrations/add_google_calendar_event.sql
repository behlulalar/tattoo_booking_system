-- Google Calendar sync (Phase 1): store event id per appointment
BEGIN;

ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS google_event_id VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_appointments_google_event_id
  ON appointments (google_event_id)
  WHERE google_event_id IS NOT NULL;

COMMIT;
