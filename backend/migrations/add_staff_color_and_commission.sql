-- =============================================
-- PERSONEL TAKVİM RENGİ VE KAZANÇ YÜZDESİ
-- Tarih: 2026-09-30
-- Açıklama:
--   artists.calendar_color_id   : Google Takvim etkinlik rengi (colorId 1-11). Grafit (8) Off Day
--                                 etkinliklerine ayrılıdır, personele atanmaz. Panelden seçilir.
--   artists.commission_percent  : Personel kazanç yüzdesi (30 / 50 / 70, varsayılan 50).
--                                 Stüdyo sahibi (super_admin) için uygulanmaz.
--   appointments.staff_share_percent : Randevu "tamamlandı" yapıldığı andaki yüzde. Yüzde sonradan
--                                 değişse de geçmiş aylar eski yüzdeyle hesaplanır.
--
-- NOT: Bu değişiklikler backend/app.py içindeki ensure_staff_color_and_commission_columns() ile
-- uygulama her başladığında otomatik (idempotent) yapılır; bu dosya manuel kurulum/dokümantasyon içindir.
-- =============================================

BEGIN;

ALTER TABLE artists ADD COLUMN IF NOT EXISTS calendar_color_id VARCHAR(2);
ALTER TABLE artists ADD COLUMN IF NOT EXISTS commission_percent SMALLINT NOT NULL DEFAULT 50;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS staff_share_percent SMALLINT;

ALTER TABLE artists DROP CONSTRAINT IF EXISTS artists_calendar_color_id_check;
ALTER TABLE artists ADD CONSTRAINT artists_calendar_color_id_check
  CHECK (calendar_color_id IS NULL OR calendar_color_id IN ('1','2','3','4','5','6','7','9','10','11'));

ALTER TABLE artists DROP CONSTRAINT IF EXISTS artists_commission_percent_check;
ALTER TABLE artists ADD CONSTRAINT artists_commission_percent_check
  CHECK (commission_percent IN (30, 50, 70));

-- Roof production: eski (koda gömülü) renkler aynen aktarılır.
UPDATE artists
   SET calendar_color_id = CASE id WHEN 1 THEN '6' WHEN 2 THEN '11' WHEN 3 THEN '5' WHEN 4 THEN '2' END
 WHERE calendar_color_id IS NULL AND id IN (1, 2, 3, 4);

COMMIT;
