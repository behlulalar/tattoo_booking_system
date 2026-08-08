-- Sanatçı Instagram portfolyo linki (müşteri sanatçı seçim ekranı + admin profil)
ALTER TABLE artists
    ADD COLUMN IF NOT EXISTS instagram_url VARCHAR(255);
