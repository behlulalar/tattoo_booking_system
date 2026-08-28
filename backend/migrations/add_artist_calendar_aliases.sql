-- Takvim başlığı eşlemesi: personel adı değişince eski yazım (ör. Nihal) çalışmaya devam etsin.
BEGIN;

ALTER TABLE artists
  ADD COLUMN IF NOT EXISTS calendar_aliases TEXT[] NOT NULL DEFAULT '{}';

UPDATE artists
   SET calendar_aliases = (
        SELECT ARRAY(
            SELECT DISTINCT x
              FROM unnest(
                  COALESCE(calendar_aliases, '{}'::text[])
                  || ARRAY['Nihal', 'Nihal Karagöz']
              ) AS x
             WHERE NULLIF(BTRIM(x), '') IS NOT NULL
        )
   )
 WHERE name ILIKE 'Berke Uzun'
   AND NOT ('Nihal' = ANY (COALESCE(calendar_aliases, '{}'::text[])));

COMMIT;
