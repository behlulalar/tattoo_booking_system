-- Kısa talep referans numarası (örn. RN2323)
BEGIN;

ALTER TABLE tattoo_requests
  ADD COLUMN IF NOT EXISTS reference_number VARCHAR(12);

CREATE UNIQUE INDEX IF NOT EXISTS tattoo_requests_reference_number_uidx
  ON tattoo_requests(reference_number)
  WHERE reference_number IS NOT NULL;

COMMIT;
