-- Local demo seed: 1 artist + 1 super admin
-- Password for both: 123456

BEGIN;

-- Berk Atik (artist)
INSERT INTO artists (name, phone, password, role, profile_photo, display_order)
VALUES (
  'Berk Atik',
  '2222222222',
  '$2b$12$vGmrooO6GzdYFjCqf9CCw.77zxPBl4oXE3ujoYBN3Z/zLnFpxZJkW',
  'staff',
  NULL,
  1
)
ON CONFLICT (phone) DO UPDATE SET
  name = EXCLUDED.name,
  password = EXCLUDED.password,
  role = EXCLUDED.role,
  display_order = EXCLUDED.display_order;

-- Admin (super_admin)
INSERT INTO artists (name, phone, password, role, profile_photo, display_order)
VALUES (
  'Admin',
  '1111111111',
  '$2b$12$vGmrooO6GzdYFjCqf9CCw.77zxPBl4oXE3ujoYBN3Z/zLnFpxZJkW',
  'super_admin',
  NULL,
  0
)
ON CONFLICT (phone) DO UPDATE SET
  name = EXCLUDED.name,
  password = EXCLUDED.password,
  role = EXCLUDED.role,
  display_order = EXCLUDED.display_order;

COMMIT;

