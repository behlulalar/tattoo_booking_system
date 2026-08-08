-- Geçmişte tamamlanıp gelir tablosuna düşmemiş randevuları income_adjustments'a ekler
BEGIN;

INSERT INTO income_adjustments (amount, description, adjustment_date, created_by)
SELECT
  a.price,
  'Randevu #' || a.id,
  a.appointment_date,
  a.staff_id
FROM appointments a
WHERE a.status = 'completed'
  AND COALESCE(a.price, 0) > 0
  AND NOT EXISTS (
    SELECT 1 FROM income_adjustments ia
    WHERE ia.description LIKE 'Randevu #' || a.id || '%'
  );

COMMIT;
