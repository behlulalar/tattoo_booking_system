-- Immutable origin of each appointment row (who created it).
-- Distinct from google_event_id, which only means "copied to Google".
BEGIN;

ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'admin';

UPDATE appointments
SET source = 'customer'
WHERE tattoo_request_id IS NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'appointments_source_check'
  ) THEN
    ALTER TABLE appointments
      ADD CONSTRAINT appointments_source_check
      CHECK (source IN ('customer', 'admin', 'google'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_appointments_source
  ON appointments (source);

COMMIT;
