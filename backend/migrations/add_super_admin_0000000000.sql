-- Super admin: telefon 0000000000, şifre 123456 (bcrypt)
BEGIN;

INSERT INTO artists (name, phone, password, role, profile_photo, display_order)
VALUES (
  'Super Admin',
  '0000000000',
  '$2b$12$t1KR5gyrPYOkj/yv6VxXj.Gp1DkpASXgBoKyJ.igGacJpFVeQZGyS',
  'super_admin',
  NULL,
  0
)
ON CONFLICT (phone) DO UPDATE SET
  name = EXCLUDED.name,
  password = EXCLUDED.password,
  role = 'super_admin',
  display_order = EXCLUDED.display_order;

COMMIT;
