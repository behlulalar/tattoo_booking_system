-- Vücut bölgesi ID'si
ALTER TABLE tattoo_requests ADD COLUMN IF NOT EXISTS body_region VARCHAR(32);

CREATE INDEX IF NOT EXISTS idx_tattoo_requests_body_region ON tattoo_requests(body_region);
