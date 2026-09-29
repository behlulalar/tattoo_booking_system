-- =============================================
-- WORKING_HOURS TABLOSUNU KALDIR
-- Tarih: 2026-09-29
-- Aciklama: Randevular artik tamamen sanatcilar tarafindan veriliyor
-- (musteri saat secmiyor), "Saatlerim" mesai penceresi kullanilmiyor.
-- Off Day (time_off) etkilenmez.
-- =============================================

DROP VIEW IF EXISTS artist_working_hours;
DROP TABLE IF EXISTS working_hours;
