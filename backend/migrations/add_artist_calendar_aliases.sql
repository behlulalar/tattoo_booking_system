-- Takvim başlığı için isteğe bağlı takma adlar (personel formundan yönetilir).
BEGIN;

ALTER TABLE artists
  ADD COLUMN IF NOT EXISTS calendar_aliases TEXT[] NOT NULL DEFAULT '{}';

COMMIT;
