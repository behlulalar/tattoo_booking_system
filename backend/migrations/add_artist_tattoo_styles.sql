-- Sanatçıya özel dövme tarzları (admin panelden yönetilir)
CREATE TABLE IF NOT EXISTS artist_tattoo_styles (
    id             SERIAL PRIMARY KEY,
    staff_id       INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    style_key      VARCHAR(80) NOT NULL,
    label          VARCHAR(255) NOT NULL,
    display_order  INTEGER NOT NULL DEFAULT 0,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (staff_id, style_key)
);

CREATE INDEX IF NOT EXISTS idx_artist_tattoo_styles_staff
    ON artist_tattoo_styles (staff_id);

CREATE INDEX IF NOT EXISTS idx_artist_tattoo_styles_staff_order
    ON artist_tattoo_styles (staff_id, display_order);
