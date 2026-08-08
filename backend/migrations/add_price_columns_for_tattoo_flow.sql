BEGIN;

-- Backfill compatibility for older tattoo-flow deployments.
-- New code expects both slot_offers.price and appointments.price.

ALTER TABLE slot_offers
    ADD COLUMN IF NOT EXISTS price NUMERIC(10,2) NOT NULL DEFAULT 0;

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS price NUMERIC(10,2) NOT NULL DEFAULT 0;

COMMIT;
