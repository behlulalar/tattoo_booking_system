-- =============================================
-- BOOTSTRAP (Fresh install) - tattoo_db
-- Creates the minimal schema required by backend/app.py (tattoo flow).
-- PostgreSQL
-- =============================================

BEGIN;

-- Enums (keep legacy values so existing code paths won't break)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'role_type') THEN
    CREATE TYPE role_type AS ENUM ('super_admin', 'staff', 'tech_support');
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'appointment_status') THEN
    CREATE TYPE appointment_status AS ENUM ('pending', 'confirmed', 'completed', 'cancelled', 'no_show');
  END IF;
END $$;

-- Customers (phone verified; name/surname optional)
CREATE TABLE IF NOT EXISTS customers (
  id          SERIAL PRIMARY KEY,
  phone       VARCHAR(10) NOT NULL UNIQUE,
  name        VARCHAR(50),
  surname     VARCHAR(50),
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Artists (was staff)
CREATE TABLE IF NOT EXISTS artists (
  id             SERIAL PRIMARY KEY,
  name           VARCHAR(50) NOT NULL,
  phone          VARCHAR(10) NOT NULL UNIQUE,
  password       VARCHAR(255) NOT NULL,
  role           role_type DEFAULT 'staff',
  profile_photo  TEXT,
  instagram_url  VARCHAR(255),
  display_order  INTEGER DEFAULT 0,
  created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tattoo requests
CREATE TABLE IF NOT EXISTS tattoo_requests (
  id               SERIAL PRIMARY KEY,
  customer_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  staff_id         INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
  size             VARCHAR(50),
  body_area        VARCHAR(100),
  tattoo_style     VARCHAR(80),
  estimated_price  NUMERIC(10,2),
  reference_number VARCHAR(12) UNIQUE,
  description      TEXT,
  reference_image  TEXT,
  status           VARCHAR(30) NOT NULL DEFAULT 'new',
  created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tattoo_requests_staff ON tattoo_requests(staff_id);
CREATE INDEX IF NOT EXISTS idx_tattoo_requests_customer ON tattoo_requests(customer_id);
CREATE INDEX IF NOT EXISTS idx_tattoo_requests_status ON tattoo_requests(status);

-- Slot offers (tokenized link)
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

-- Appointments
CREATE TABLE IF NOT EXISTS appointments (
  id                SERIAL PRIMARY KEY,
  customer_id       INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  staff_id          INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
  tattoo_request_id INTEGER REFERENCES tattoo_requests(id) ON DELETE SET NULL,
  appointment_date  DATE NOT NULL,
  appointment_time  TIME NOT NULL,
  status            appointment_status DEFAULT 'pending',
  payment_method    VARCHAR(50),
  duration_minutes  INTEGER NOT NULL DEFAULT 30 CHECK (duration_minutes >= 30 AND duration_minutes % 30 = 0),
  price             NUMERIC(10,2) NOT NULL DEFAULT 0,
  reminder_sent     BOOLEAN DEFAULT FALSE,
  completed_at      TIMESTAMP,
  aftercare_reminder_sent BOOLEAN DEFAULT FALSE,
  google_event_id   VARCHAR(255),
  source            VARCHAR(20) NOT NULL DEFAULT 'admin'
                    CHECK (source IN ('customer', 'admin', 'google')),
  created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS appointments_staff_date_time_uidx
ON appointments(staff_id, appointment_date, appointment_time);

CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(appointment_date);
CREATE INDEX IF NOT EXISTS idx_appointments_staff ON appointments(staff_id);
CREATE INDEX IF NOT EXISTS idx_appointments_customer ON appointments(customer_id);
CREATE INDEX IF NOT EXISTS idx_appointments_source ON appointments(source);

-- Working hours
CREATE TABLE IF NOT EXISTS working_hours (
  id           SERIAL PRIMARY KEY,
  staff_id     INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
  day_of_week  INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
  start_time   TIME NOT NULL,
  end_time     TIME NOT NULL,
  is_available BOOLEAN DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_working_hours_staff ON working_hours(staff_id);

-- Time off
CREATE TABLE IF NOT EXISTS time_off (
  id           SERIAL PRIMARY KEY,
  staff_id     INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
  off_date     DATE NOT NULL,
  start_time   TIME,
  end_time     TIME,
  reason       VARCHAR(100),
  created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(staff_id, off_date, start_time)
);
CREATE INDEX IF NOT EXISTS idx_time_off_staff ON time_off(staff_id);
CREATE INDEX IF NOT EXISTS idx_time_off_date ON time_off(off_date);

-- Webhook cooldown (multi-worker safety)
CREATE TABLE IF NOT EXISTS webhook_cooldown (
  id SERIAL PRIMARY KEY,
  phone_key VARCHAR(64) UNIQUE NOT NULL,
  last_sent_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Verification codes (multi-worker safety)
CREATE TABLE IF NOT EXISTS verification_codes (
  id SERIAL PRIMARY KEY,
  phone VARCHAR(20) NOT NULL,
  code VARCHAR(10) NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_verification_codes_phone ON verification_codes(phone);
CREATE INDEX IF NOT EXISTS idx_verification_codes_expires ON verification_codes(expires_at);

-- Manual income adjustments (admin)
CREATE TABLE IF NOT EXISTS income_adjustments (
  id SERIAL PRIMARY KEY,
  amount DECIMAL(10, 2) NOT NULL,
  description TEXT NOT NULL,
  adjustment_date DATE NOT NULL,
  created_by INTEGER REFERENCES artists(id),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  type VARCHAR(10) DEFAULT 'income'
);
CREATE INDEX IF NOT EXISTS idx_adjustment_date ON income_adjustments(adjustment_date);
CREATE INDEX IF NOT EXISTS idx_created_by ON income_adjustments(created_by);

COMMIT;

