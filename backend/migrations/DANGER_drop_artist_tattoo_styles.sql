-- ============================================================
-- ⚠️  TEHLİKELİ / GERİ ALINAMAZ — normal migration akışının PARÇASI DEĞİLDİR
-- Sadece elle, bilerek ve tek seferlik çalıştırılmak içindir.
-- ============================================================
-- Dövme tarzı seçimi randevu akışından kaldırıldı; katalog tablosu artık kullanılmıyor.
DROP TABLE IF EXISTS artist_tattoo_styles;
