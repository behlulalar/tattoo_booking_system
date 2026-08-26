-- Nihal Karagöz (şimdi Berke Uzun, staff_id=1) demo randevu/talep temizliği.
-- Sanatçı kaydı silinmez.

BEGIN;

DELETE FROM loyalty_transactions
WHERE appointment_id IN (SELECT id FROM appointments WHERE staff_id = 1);

DELETE FROM income_adjustments
WHERE created_by = 1
   OR description IN (
     SELECT 'Randevu #' || id FROM appointments WHERE staff_id = 1
   )
   OR description LIKE ANY (
     ARRAY(SELECT 'Randevu #' || id || ' ·%' FROM appointments WHERE staff_id = 1)
   );

DELETE FROM appointments WHERE staff_id = 1;
DELETE FROM tattoo_requests WHERE staff_id = 1;
DELETE FROM time_off WHERE staff_id = 1;

COMMIT;
