-- =============================================
-- TATTOO BOOKING REVAMP v1
-- Converts service-based booking into tattoo-request + offer-token slot picking.
-- PostgreSQL
-- =============================================

BEGIN;

-- 1) Customers: name/surname optional for new flow (phone verification only)
ALTER TABLE customers ALTER COLUMN name DROP NOT NULL;
ALTER TABLE customers ALTER COLUMN surname DROP NOT NULL;

-- 2) New: tattoo_requests
CREATE TABLE IF NOT EXISTS tattoo_requests (
    id               SERIAL PRIMARY KEY,
    customer_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    staff_id         INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    size             VARCHAR(50),            -- e.g. small/medium/large or cm-based
    body_area        VARCHAR(100),           -- e.g. forearm, shoulder
    description      TEXT,
    reference_image  TEXT,                  -- URL or base64 (implementation choice)
    status           VARCHAR(30) NOT NULL DEFAULT 'new', -- new/offered/scheduled/cancelled
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tattoo_requests_staff ON tattoo_requests(staff_id);
CREATE INDEX IF NOT EXISTS idx_tattoo_requests_customer ON tattoo_requests(customer_id);
CREATE INDEX IF NOT EXISTS idx_tattoo_requests_status ON tattoo_requests(status);

-- 3) New: slot_offers (tokenized link for customer slot picking)
CREATE TABLE IF NOT EXISTS slot_offers (
    id                SERIAL PRIMARY KEY,
    tattoo_request_id  INTEGER NOT NULL REFERENCES tattoo_requests(id) ON DELETE CASCADE,
    token             VARCHAR(80) NOT NULL UNIQUE,
    duration_minutes  INTEGER NOT NULL CHECK (duration_minutes >= 30 AND duration_minutes % 30 = 0),
    price             NUMERIC(10,2) NOT NULL DEFAULT 0,
    expires_at        TIMESTAMP NOT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    used_at           TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_slot_offers_token ON slot_offers(token);
CREATE INDEX IF NOT EXISTS idx_slot_offers_request ON slot_offers(tattoo_request_id);

-- 4) Appointments: move from services -> tattoo_request
ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS tattoo_request_id INTEGER REFERENCES tattoo_requests(id) ON DELETE SET NULL;

-- Duration is required to block 30-minute slots correctly
ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS duration_minutes INTEGER NOT NULL DEFAULT 30
        CHECK (duration_minutes >= 30 AND duration_minutes % 30 = 0);

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS price NUMERIC(10,2) NOT NULL DEFAULT 0;

-- Keep payment_method column for now; not used in new flow.

-- Drop old service_id column if present (and related objects)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name='appointments' AND column_name='service_id'
    ) THEN
        ALTER TABLE appointments DROP COLUMN service_id;
    END IF;
END $$;

-- Ensure uniqueness for staff/date/time slot (prevents race conditions)
CREATE UNIQUE INDEX IF NOT EXISTS appointments_staff_date_time_uidx
ON appointments(staff_id, appointment_date, appointment_time);

-- 5) Decommission old tables (if you no longer need them)
DROP TABLE IF EXISTS staff_services;
DROP TABLE IF EXISTS services;
DROP TABLE IF EXISTS payment_methods;

COMMIT;

