-- Sadakat puanı sistemi
-- Çalıştır: psql -h localhost -U tattoo_user -d tattoo_db -f add_loyalty_points.sql

ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS loyalty_points INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS loyalty_transactions (
  id              SERIAL PRIMARY KEY,
  customer_id     INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  appointment_id  INTEGER REFERENCES appointments(id) ON DELETE SET NULL,
  points_delta    INTEGER NOT NULL,
  balance_after   INTEGER NOT NULL,
  transaction_type VARCHAR(20) NOT NULL,
  description     TEXT,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_loyalty_earn_per_appointment
  ON loyalty_transactions (appointment_id, transaction_type)
  WHERE appointment_id IS NOT NULL AND transaction_type = 'earn';

CREATE INDEX IF NOT EXISTS idx_loyalty_transactions_customer
  ON loyalty_transactions (customer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS loyalty_redemptions (
  id               SERIAL PRIMARY KEY,
  customer_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  redemption_code  VARCHAR(24) NOT NULL UNIQUE,
  discount_percent INTEGER NOT NULL DEFAULT 10,
  points_spent     INTEGER NOT NULL,
  used_at          TIMESTAMP,
  expires_at       TIMESTAMP NOT NULL,
  created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_loyalty_redemptions_customer
  ON loyalty_redemptions (customer_id, created_at DESC);
