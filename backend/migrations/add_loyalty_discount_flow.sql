-- Sadakat indirim kodu: talep + teklif akışı
ALTER TABLE tattoo_requests
  ADD COLUMN IF NOT EXISTS loyalty_redemption_id INTEGER REFERENCES loyalty_redemptions(id) ON DELETE SET NULL;

ALTER TABLE tattoo_requests
  ADD COLUMN IF NOT EXISTS loyalty_discount_code VARCHAR(24),
  ADD COLUMN IF NOT EXISTS loyalty_discount_percent INTEGER;

ALTER TABLE loyalty_redemptions
  ADD COLUMN IF NOT EXISTS tattoo_request_id INTEGER REFERENCES tattoo_requests(id) ON DELETE SET NULL;

ALTER TABLE slot_offers
  ADD COLUMN IF NOT EXISTS original_price NUMERIC(10,2),
  ADD COLUMN IF NOT EXISTS discount_percent INTEGER;

CREATE INDEX IF NOT EXISTS idx_tattoo_requests_loyalty_redemption
  ON tattoo_requests (loyalty_redemption_id)
  WHERE loyalty_redemption_id IS NOT NULL;
