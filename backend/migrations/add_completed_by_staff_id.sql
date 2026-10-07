-- Randevuyu "tamamlandı" yapan personel (bakım hatırlatmasında sanatçı adı için)
ALTER TABLE appointments
  ADD COLUMN IF NOT EXISTS completed_by_staff_id INTEGER REFERENCES artists(id) ON DELETE SET NULL;
