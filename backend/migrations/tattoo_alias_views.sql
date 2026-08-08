-- Optional: domain-friendly aliases without renaming base tables
-- This keeps the code stable while providing "tattoo" naming in the DB.

BEGIN;

-- After hard rename (staff -> artists), this view is unnecessary.
-- Keeping here as a no-op placeholder for older installs.
DROP VIEW IF EXISTS artists;
CREATE OR REPLACE VIEW artist_working_hours AS SELECT * FROM working_hours;
CREATE OR REPLACE VIEW artist_time_off AS SELECT * FROM time_off;
CREATE OR REPLACE VIEW tattoo_appointments AS SELECT * FROM appointments;

COMMIT;

