-- Manuel Gelir Ayarlama Tablosu
-- Bu tablo admin panelde manuel olarak eklenen/çıkarılan gelirleri saklar

CREATE TABLE IF NOT EXISTS income_adjustments (
    id SERIAL PRIMARY KEY,
    amount DECIMAL(10, 2) NOT NULL,  -- Pozitif: gelir ekle, Negatif: gider çıkar
    description TEXT NOT NULL,
    adjustment_date DATE NOT NULL,    -- Hangi ay/yıla ait
    created_by INTEGER REFERENCES staff(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index oluştur (performans için)
CREATE INDEX IF NOT EXISTS idx_adjustment_date ON income_adjustments(adjustment_date);
CREATE INDEX IF NOT EXISTS idx_created_by ON income_adjustments(created_by);

-- Örnek kayıtlar (test için)
-- INSERT INTO income_adjustments (amount, description, adjustment_date, created_by) 
-- VALUES (500.00, 'Ek hizmet geliri', '2025-12-15', 1);
-- INSERT INTO income_adjustments (amount, description, adjustment_date, created_by) 
-- VALUES (-200.00, 'Malzeme masrafı', '2025-12-18', 1);
