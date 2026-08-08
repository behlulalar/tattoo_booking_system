-- =============================================
-- SEFA RANDEVU SİSTEMİ - VERİTABANI ŞEMASI
-- PostgreSQL
-- =============================================

-- Role tipi için ENUM oluştur
CREATE TYPE role_type AS ENUM ('super_admin', 'staff');

-- Randevu durumu için ENUM oluştur
CREATE TYPE appointment_status AS ENUM ('pending', 'confirmed', 'completed', 'cancelled', 'no_show');

-- =============================================
-- 1. CUSTOMERS (Müşteriler) Tablosu
-- =============================================
CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    phone       VARCHAR(10) NOT NULL UNIQUE,  -- Başında 0 olmadan: 5551234567
    name        VARCHAR(50) NOT NULL,
    surname     VARCHAR(50) NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 2. ARTISTS (Personel) Tablosu
-- =============================================
CREATE TABLE artists (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(50) NOT NULL,
    phone          VARCHAR(10) NOT NULL UNIQUE,
    password       VARCHAR(255) NOT NULL,  -- Hashed password
    role           role_type DEFAULT 'staff',
    profile_photo  TEXT,                   -- Base64 encoded image
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 3. SERVICES (Hizmetler) Tablosu
-- =============================================
CREATE TABLE services (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    price         INTEGER NOT NULL,        -- TL cinsinden (kuruşsuz)
    duration_min  INTEGER NOT NULL,        -- Dakika cinsinden
    is_active     BOOLEAN DEFAULT TRUE
);

-- =============================================
-- 4. APPOINTMENTS (Randevular) Tablosu
-- =============================================
CREATE TABLE appointments (
    id                SERIAL PRIMARY KEY,
    customer_id       INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    staff_id          INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    tattoo_request_id INTEGER REFERENCES tattoo_requests(id) ON DELETE SET NULL,
    appointment_date  DATE NOT NULL,
    appointment_time  TIME NOT NULL,
    status            appointment_status DEFAULT 'pending',
    payment_method    VARCHAR(50),
    duration_minutes  INTEGER NOT NULL DEFAULT 30,
    reminder_sent     BOOLEAN DEFAULT FALSE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================
-- 5. WORKING_HOURS (Çalışma Saatleri) Tablosu
-- =============================================
CREATE TABLE working_hours (
    id           SERIAL PRIMARY KEY,
    staff_id     INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    day_of_week  INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),  -- 0=Pazar, 1=Pazartesi...
    start_time   TIME NOT NULL,
    end_time     TIME NOT NULL,
    is_available BOOLEAN DEFAULT TRUE
);

-- =============================================
-- 6. STAFF_SERVICES (Personel-Hizmet İlişkisi) Tablosu
-- =============================================
CREATE TABLE staff_services (
    id         SERIAL PRIMARY KEY,
    staff_id   INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    price      INTEGER NOT NULL,  -- Personele özel fiyat
    UNIQUE(staff_id, service_id)  -- Aynı personel-hizmet çifti 1 kez olabilir
);

CREATE INDEX idx_staff_services_staff ON staff_services(staff_id);
CREATE INDEX idx_staff_services_service ON staff_services(service_id);

-- =============================================
-- INDEXLER (Performans için)
-- =============================================
CREATE INDEX idx_appointments_date ON appointments(appointment_date);
CREATE INDEX idx_appointments_staff ON appointments(staff_id);
CREATE INDEX idx_appointments_customer ON appointments(customer_id);
CREATE INDEX idx_working_hours_staff ON working_hours(staff_id);

-- =============================================
-- 7. TIME_OFF (İzin/Kapalı Saatler) Tablosu
-- =============================================
CREATE TABLE time_off (
    id           SERIAL PRIMARY KEY,
    staff_id     INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    off_date     DATE NOT NULL,                -- İzin tarihi
    start_time   TIME,                         -- NULL=Tüm gün izin
    end_time     TIME,                         -- NULL=Tüm gün izin
    reason       VARCHAR(100),                 -- Açıklama (opsiyonel)
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, off_date, start_time)
);

CREATE INDEX idx_time_off_staff ON time_off(staff_id);
CREATE INDEX idx_time_off_date ON time_off(off_date);

-- =============================================
-- ÖRNEK VERİLER (Opsiyonel - Test için)
-- =============================================

-- Süper Admin (Sefa Abi) ekle - Şifre: 123456 (hash'lenmiş hali girilmeli!)
-- INSERT INTO artists (name, phone, password, role) 
-- VALUES ('Sefa', '5551234567', 'HASHED_PASSWORD_HERE', 'super_admin');

-- Hizmetler ekle
-- INSERT INTO services (name, price, duration_min) VALUES
-- ('Saç Kesimi', 150, 30),
-- ('Sakal Kesimi', 100, 20),
-- ('Saç + Sakal', 200, 45),
-- ('Perma', 300, 60),
-- ('Keratin', 500, 90);

-- =============================================
-- 8. PAYMENT_METHODS (Ödeme Yöntemleri) Tablosu
-- =============================================
CREATE TABLE payment_methods (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,     -- "Nakit", "Havale / EFT"
    code        VARCHAR(50) NOT NULL UNIQUE, -- "nakit", "havale" (internal use)
    icon        VARCHAR(10),               -- "💵", "🏦"
    description VARCHAR(255),              -- "Randevu sonrası ödeyin"
    details     TEXT,                      -- JSON: banka bilgileri, açıklamalar
    is_active   BOOLEAN DEFAULT TRUE,
    sort_order  INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_payment_methods_active ON payment_methods(is_active);

-- Varsayılan ödeme yöntemleri
INSERT INTO payment_methods (name, code, icon, description, details, sort_order) VALUES
('Nakit', 'nakit', '💵', 'Randevu sonrası ödeyin', NULL, 1),
('Havale / EFT', 'havale', '🏦', 'Banka transferi ile ödeyin', 
 '{"banka": "Ziraat Bankası", "hesap_adi": "Sefa Pertev", "iban": "TR00 0000 0000 0000 0000 0000 00", "not": "Açıklama kısmına telefon numaranızı yazınız."}', 2);
