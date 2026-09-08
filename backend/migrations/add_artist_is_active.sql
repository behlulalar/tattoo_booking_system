-- Personel "soft delete" bayrağı.
--
-- Neden gerekli:
--   delete_staff (DELETE /api/admin/staff/<id>) geçmiş randevusu (tamamlanmış
--   dahil) olan bir personeli hard-delete ederken TÜM randevu kayıtlarını da
--   siliyordu — bu, geçmiş gelir raporlarını geriye dönük bozuyordu. Artık
--   geçmişi olan personel is_active=FALSE ile deaktive ediliyor, randevu/gelir
--   kayıtları korunuyor.
--
-- NOT: Bu kolon backend/app.py içindeki ensure_artist_is_active_column() ile
-- uygulama her başladığında otomatik (varsa dokunmadan) eklenir — bu dosya
-- yalnızca dokümantasyon/manuel kurulum amaçlıdır.

ALTER TABLE artists ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
