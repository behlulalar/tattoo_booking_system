-- Tattoo style + estimated price (customer config step)
BEGIN;

ALTER TABLE tattoo_requests
  ADD COLUMN IF NOT EXISTS tattoo_style VARCHAR(80),
  ADD COLUMN IF NOT EXISTS estimated_price NUMERIC(10,2);

COMMIT;
