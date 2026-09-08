-- Mevcut çakışan randevuları listeler.
-- add_appointment_overlap_guard.sql çalıştırılmadan ÖNCE bunu çalıştırın:
-- boş sonuç dönerse kısıt sorunsuz eklenir.

SELECT
    a.staff_id,
    s.name                                   AS sanatci,
    a.appointment_date                       AS tarih,
    a.id                                     AS randevu_a,
    a.appointment_time                       AS baslangic_a,
    a.duration_minutes                       AS sure_a,
    b.id                                     AS randevu_b,
    b.appointment_time                       AS baslangic_b,
    b.duration_minutes                       AS sure_b
FROM appointments a
JOIN appointments b
  ON a.staff_id         = b.staff_id
 AND a.appointment_date = b.appointment_date
 AND a.id               < b.id
JOIN artists s ON s.id = a.staff_id
WHERE a.status IS DISTINCT FROM 'cancelled'
  AND b.status IS DISTINCT FROM 'cancelled'
  AND (a.appointment_date + a.appointment_time)
        + make_interval(mins => a.duration_minutes)
      > (b.appointment_date + b.appointment_time)
  AND (b.appointment_date + b.appointment_time)
        + make_interval(mins => b.duration_minutes)
      > (a.appointment_date + a.appointment_time)
ORDER BY a.appointment_date, a.staff_id, a.appointment_time;
