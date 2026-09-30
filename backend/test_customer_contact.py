import unittest

import customer_contact as cc


class CustomerContactTest(unittest.TestCase):
    def test_placeholder_detection(self):
        self.assertTrue(cc.is_placeholder_phone('1234567890'))
        self.assertTrue(cc.is_placeholder_phone(cc.make_placeholder_phone()))
        self.assertFalse(cc.is_placeholder_phone('5359708001'))
        self.assertFalse(cc.is_placeholder_phone('905359708001'))
        self.assertFalse(cc.is_placeholder_phone('123456789012@lid'))
        self.assertFalse(cc.is_placeholder_phone(''))

    def test_placeholder_is_deterministic_per_seed_and_unique_otherwise(self):
        self.assertEqual(cc.make_placeholder_phone('a'), cc.make_placeholder_phone('a'))
        self.assertNotEqual(cc.make_placeholder_phone(), cc.make_placeholder_phone())

    def test_normalize_instagram(self):
        self.assertEqual(cc.normalize_instagram('@Ali.Veli_1'), 'ali.veli_1')
        self.assertEqual(cc.normalize_instagram('https://www.instagram.com/aliveli/?hl=tr'), 'aliveli')
        self.assertIsNone(cc.normalize_instagram('  '))
        with self.assertRaises(ValueError):
            cc.normalize_instagram('ali veli')

    def test_extract_instagram_from_title(self):
        self.assertEqual(cc.extract_instagram('Tuncer Ali Veli @AliVeli'), ('aliveli', 'Tuncer Ali Veli'))
        self.assertEqual(cc.extract_instagram('Tuncer @ali.v Veli'), ('ali.v', 'Tuncer Veli'))
        self.assertEqual(cc.extract_instagram('Tuncer Ali'), (None, 'Tuncer Ali'))
        self.assertEqual(cc.extract_instagram('mail a@b.com'), (None, 'mail a@b.com'))

    def test_contact_label(self):
        self.assertEqual(cc.contact_label('5359708001', None, lambda p: '0' + p), '05359708001')
        self.assertEqual(cc.contact_label('1234567890', 'aliveli'), '@aliveli')
        self.assertEqual(cc.contact_label('1234567890', None), 'Tel no yok')


class GcalCustomerInstagramTest(unittest.TestCase):
    def test_instagram_without_phone_creates_placeholder_customer(self):
        import google_calendar_sync as gcs
        from unittest import mock
        cursor = mock.MagicMock()
        cursor.fetchone.side_effect = [None, (77,)]
        cid = gcs._resolve_or_create_gcal_customer(cursor, 'Ali', 'Veli', None, 'evt1', instagram='aliveli')
        self.assertEqual(cid, 77)
        insert_params = cursor.execute.call_args_list[-1].args[1]
        self.assertTrue(cc.is_placeholder_phone(insert_params[0]))
        self.assertEqual(insert_params[3], 'aliveli')

    def test_instagram_reuses_existing_customer(self):
        import google_calendar_sync as gcs
        from unittest import mock
        cursor = mock.MagicMock()
        cursor.fetchone.side_effect = [(5,)]
        self.assertEqual(gcs._resolve_or_create_gcal_customer(cursor, 'Ali', 'Veli', None, 'evt2', instagram='aliveli'), 5)


class ImportSafetyTest(unittest.TestCase):
    def _delete(self, existing):
        import google_calendar_sync as gcs
        from unittest import mock
        service = mock.MagicMock()
        if isinstance(existing, Exception):
            service.events.return_value.get.return_value.execute.side_effect = existing
        else:
            service.events.return_value.get.return_value.execute.return_value = existing
        with mock.patch.object(gcs, 'is_google_calendar_enabled', return_value=True), \
             mock.patch.object(gcs, 'get_google_calendar_config', return_value={'calendar_id': 'cal'}), \
             mock.patch.object(gcs, '_get_calendar_service', return_value=service):
            result = gcs._perform_event_delete('evt')
        return result, service

    def test_imported_event_is_never_deleted(self):
        result, service = self._delete({'id': 'evt', 'extendedProperties': {'private': {'imported': '1', 'origin': 'roof'}}})
        self.assertEqual(result, 'ok')
        service.events.return_value.delete.assert_not_called()

    def test_system_created_event_is_deleted(self):
        result, service = self._delete({'id': 'evt', 'extendedProperties': {'private': {'origin': 'roof'}}})
        self.assertEqual(result, 'ok')
        service.events.return_value.delete.assert_called_once()

    def test_already_missing_event_is_ok(self):
        result, service = self._delete(Exception('404 not found'))
        self.assertEqual(result, 'ok')
        service.events.return_value.delete.assert_not_called()

    def test_initial_import_window_is_october_then_expires(self):
        import google_calendar_sync as gcs
        from datetime import datetime, timezone
        tz = timezone.utc
        lo, hi = gcs._initial_import_window(datetime(2026, 10, 1, 12, tzinfo=tz), tz)
        self.assertEqual((lo.date().isoformat(), hi.date().isoformat()), ('2026-10-01', '2026-11-01'))
        self.assertIsNone(gcs._initial_import_window(datetime(2026, 11, 1, 9, tzinfo=tz), tz))

    def test_import_stamp_marks_event_imported(self):
        import google_calendar_sync as gcs
        self.assertEqual(gcs._extended_properties(5, 'h', imported=True)['private']['imported'], '1')
        self.assertNotIn('imported', gcs._extended_properties(5, 'h')['private'])
        self.assertEqual(gcs._off_day_extended_properties(5, imported=True)['private']['imported'], '1')


class ImportFloorTest(unittest.TestCase):
    def test_import_floor_is_october(self):
        import google_calendar_sync as gcs
        from datetime import date
        self.assertEqual(gcs._import_floor_date(), date(2026, 10, 1))


if __name__ == '__main__':
    unittest.main()
