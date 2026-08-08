-- =============================================
-- CUSTOMER REVIEWS TABLE
-- =============================================

CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for better performance
CREATE INDEX idx_reviews_appointment ON reviews(appointment_id);
CREATE INDEX idx_reviews_customer ON reviews(customer_id);
CREATE INDEX idx_reviews_staff ON reviews(staff_id);
CREATE INDEX idx_reviews_rating ON reviews(rating);

-- Example query to get reviews for a staff member
-- SELECT r.*, c.name, c.surname, a.appointment_date 
-- FROM reviews r
-- JOIN customers c ON r.customer_id = c.id
-- JOIN appointments a ON r.appointment_id = a.id
-- WHERE r.staff_id = 1
-- ORDER BY r.created_at DESC;
