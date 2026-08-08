-- income_adjustments.type (gelir/gider) — tamamlandı randevu kaydı için
BEGIN;

ALTER TABLE income_adjustments
  ADD COLUMN IF NOT EXISTS type VARCHAR(10) DEFAULT 'income';

UPDATE income_adjustments SET type = 'income' WHERE type IS NULL;

COMMIT;
