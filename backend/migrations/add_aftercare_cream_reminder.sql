-- Tamamlanan randevularda 2 saat sonra krem bakım hatırlatması (WhatsApp)
BEGIN;

ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP,
  ADD COLUMN IF NOT EXISTS aftercare_reminder_sent BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_appointments_aftercare_pending
  ON appointments (completed_at)
  WHERE status = 'completed'
    AND completed_at IS NOT NULL
    AND (aftercare_reminder_sent IS NULL OR aftercare_reminder_sent = FALSE);

COMMIT;
