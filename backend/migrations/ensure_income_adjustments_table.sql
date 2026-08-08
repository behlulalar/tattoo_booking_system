-- Sunucuda income_adjustments yoksa oluşturur (Tamamlandı → 500 önleme)
BEGIN;

CREATE TABLE IF NOT EXISTS income_adjustments (
  id SERIAL PRIMARY KEY,
  amount DECIMAL(10, 2) NOT NULL,
  description TEXT NOT NULL,
  adjustment_date DATE NOT NULL,
  created_by INTEGER REFERENCES artists(id) ON DELETE SET NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  type VARCHAR(10) DEFAULT 'income'
);

ALTER TABLE income_adjustments
  ADD COLUMN IF NOT EXISTS type VARCHAR(10) DEFAULT 'income';

CREATE INDEX IF NOT EXISTS idx_adjustment_date ON income_adjustments(adjustment_date);
CREATE INDEX IF NOT EXISTS idx_created_by ON income_adjustments(created_by);

COMMIT;
