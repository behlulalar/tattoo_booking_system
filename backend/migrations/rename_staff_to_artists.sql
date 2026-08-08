-- Hard rename: staff -> artists
-- Run this AFTER tattoo_revamp_v1.sql (or at least after your DB is ready).

BEGIN;

ALTER TABLE staff RENAME TO artists;

-- Index/sequence names usually don't matter, but sequence is commonly renamed for clarity.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'staff_id_seq') THEN
    ALTER SEQUENCE staff_id_seq RENAME TO artists_id_seq;
  END IF;
EXCEPTION WHEN undefined_table OR undefined_object THEN
  -- ignore
END $$;

COMMIT;

