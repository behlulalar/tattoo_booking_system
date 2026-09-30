"""error_notifier bildirim sikligi testleri (SMTP/DB'ye cikmadan).

Calistirma:  python3 -m unittest test_error_notifier
"""
import sys
import types
import unittest
import unittest.mock as mock

try:
    import pywebpush  # noqa: F401
except ImportError:
    # Testler gercek push gondermiyor; paket kurulu degilse yer tutucu yeterli.
    _stub = types.ModuleType('pywebpush')
    _stub.webpush = lambda *a, **k: None
    _stub.WebPushException = type('WebPushException', (Exception,), {})
    sys.modules['pywebpush'] = _stub

import error_notifier as en


class NotifyCadenceTest(unittest.TestCase):
    """Baglanti-koptu uyarisi: e-posta ve tech_support saatte bir, super_admin 2 saatte bir."""

    def setUp(self):
        self.now = 0.0
        self.last = {}

        def fake_claim(key, cooldown_seconds=None):
            cooldown = cooldown_seconds or en.ERROR_COOLDOWN_SECONDS
            if key in self.last and self.now - self.last[key] < cooldown:
                return False
            self.last[key] = self.now
            return True

        self.pushes = []
        self.urls = []
        patches = [
            mock.patch.object(en, '_claim_send_db', side_effect=fake_claim),
            mock.patch.object(en.push_notif, 'push_to_role',
                              side_effect=lambda role, title, body, url=None: (self.pushes.append(role), self.urls.append(url))),
            mock.patch.object(en, 'is_configured', return_value=True),
            mock.patch.object(en.smtplib, 'SMTP'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _alert(self, at_minutes, code='E-WA-005'):
        self.now = at_minutes * 60.0
        self.pushes.clear()
        self.urls.clear()
        sent = en.send_error_notification(code, 'Bağlantı kapalı')
        return sent, sorted(self.pushes)

    def test_first_alert_reaches_everyone(self):
        self.assertEqual(self._alert(0), (True, ['super_admin', 'tech_support']))

    def test_nothing_inside_the_first_hour(self):
        self._alert(0)
        self.assertEqual(self._alert(30), (False, []))
        self.assertEqual(self._alert(59), (False, []))

    def test_hourly_for_email_and_tech_support_two_hourly_for_super_admin(self):
        self.assertEqual(self._alert(0), (True, ['super_admin', 'tech_support']))
        self.assertEqual(self._alert(60), (True, ['tech_support']))      # e-posta var, super_admin yok
        self.assertEqual(self._alert(120), (True, ['super_admin', 'tech_support']))
        self.assertEqual(self._alert(180), (True, ['tech_support']))
        self.assertEqual(self._alert(240), (True, ['super_admin', 'tech_support']))

    def test_other_errors_do_not_push(self):
        sent, pushes = self._alert(0, code='DatabaseError')
        self.assertTrue(sent)
        self.assertEqual(pushes, [])

    def test_google_calendar_alert_uses_same_cadence(self):
        self.assertEqual(self._alert(0, 'E-GCAL-005'), (True, ['super_admin', 'tech_support']))
        self.assertEqual(self._alert(60, 'E-GCAL-005'), (True, ['tech_support']))

    def test_push_opens_the_relevant_panel_page(self):
        self._alert(0, 'E-WA-005')
        self.assertEqual(set(self.urls), {'/sp-admin-x7k.html?page=api-settings'})
        self._alert(10, 'E-GCAL-005')
        self.assertEqual(set(self.urls), {'/sp-admin-x7k.html?page=google-calendar'})

    def test_constants(self):
        self.assertEqual(en.ERROR_COOLDOWN_SECONDS, 3600)
        self.assertEqual(en.SUPER_ADMIN_PUSH_COOLDOWN_SECONDS, 7200)


if __name__ == '__main__':
    unittest.main()
