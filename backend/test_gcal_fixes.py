"""Google Takvim senkron duzeltmeleri icin davranis testleri.

Google API'ye ve veritabanina cikmadan calisir: servis ve cursor sahtelenir.
Calistirma:  python3 test_gcal_fixes.py
"""
import os
import sys
import threading
import time
import types
import unittest
import unittest.mock as mock
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_TARGET = os.path.join(_HERE, 'google_calendar_sync.py')


def _load_module():
    """Modulu gercek config/DB bagimliligi olmadan yukle."""
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        # Testler DB'ye cikmiyor; surucu kurulu degilse yer tutucu yeterli.
        sys.modules.setdefault('psycopg2', types.ModuleType('psycopg2'))
    for name in ('config', 'error_codes', 'logging_setup'):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules['config'].DATABASE_CONFIG = {}
    sys.modules['config'].SITE_CONFIG = {'business_name': 'Roof Tattoo'}
    sys.modules['config'].get_evolution_config = lambda: {}
    sys.modules['config'].get_google_calendar_config = lambda: {
        'enabled': True,
        'calendar_id': 'roof@group.calendar.google.com',
        'credentials_path': _TARGET,  # var olan herhangi bir dosya yeterli
        'timezone': 'Europe/Istanbul',
    }
    for code in ('E_GCAL_001', 'E_GCAL_002', 'E_GCAL_003', 'E_GCAL_004', 'E_GCAL_005'):
        setattr(sys.modules['error_codes'], code, code)
    sys.modules['logging_setup'].log_error = lambda *a, **k: None

    import importlib.util
    spec = importlib.util.spec_from_file_location('gcal_under_test', _TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gcs = _load_module()
TZ = ZoneInfo('Europe/Istanbul') if ZoneInfo else timezone.utc


class RecordingCursor:
    """execute() cagrilarini kaydeden, sirayla fetchone dondurenbir sahte cursor."""

    def __init__(self, fetchone_queue=None, fetchall_queue=None):
        self.executed = []
        self._fetchone = list(fetchone_queue or [])
        self._fetchall = list(fetchall_queue or [])

    def execute(self, sql, params=None):
        self.executed.append((' '.join(str(sql).split()), params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def fetchall(self):
        return self._fetchall.pop(0) if self._fetchall else []

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class OutboundSyncTest(unittest.TestCase):
    """GC-1: randevu -> Google yonu."""

    def test_fetch_appointment_row_is_defined(self):
        self.assertTrue(callable(getattr(gcs, '_fetch_appointment_row', None)))

    def test_appointment_sync_creates_event(self):
        appointment_row = (
            42, '2026-09-20', '14:00', 'confirmed', 120, 3500.0,
            'Ayse', 'Yilmaz', '5551112233', 2, 'Tuncer',
            'forearm', 'orta', 'blackwork', 'kol icin desen', 'REF-9', None,
        )
        cursor = RecordingCursor(fetchone_queue=[
            (True,),            # pg_try_advisory_xact_lock
            appointment_row,    # _fetch_appointment_row
            (42,),              # UPDATE ... RETURNING id
        ])
        conn = FakeConn(cursor)
        gcs.set_connection_provider(lambda: conn, lambda c: None)

        service = mock.MagicMock()
        service.events.return_value.insert.return_value.execute.return_value = {
            'id': 'evt_abc', 'etag': '"tag1"',
        }
        with mock.patch.object(gcs, '_get_calendar_service', return_value=service):
            status, event_id = gcs._perform_appointment_sync(42)

        self.assertEqual(status, 'ok')
        self.assertEqual(event_id, 'evt_abc')
        self.assertEqual(conn.commits, 1)

        body = service.events.return_value.insert.call_args.kwargs['body']
        self.assertIn('Ayse Yilmaz', body['summary'])
        self.assertEqual(body['id'], gcs._stable_appointment_event_id(42))
        self.assertEqual(body['start']['dateTime'], '2026-09-20T14:00:00')
        self.assertEqual(body['end']['dateTime'], '2026-09-20T16:00:00')
        self.assertEqual(body['start']['timeZone'], 'Europe/Istanbul')
        self.assertEqual(
            body['extendedProperties']['private']['appointment_id'], '42'
        )

    def test_appointment_sync_recreates_when_event_deleted_in_google(self):
        appointment_row = (
            7, '2026-09-21', '10:00', 'confirmed', 60, 0,
            'Can', 'Demir', '5559998877', 1, 'Berke',
            '', '', '', None, None, 'stale_event',
        )
        cursor = RecordingCursor(fetchone_queue=[(True,), appointment_row, (7,)])
        conn = FakeConn(cursor)
        gcs.set_connection_provider(lambda: conn, lambda c: None)

        missing = Exception('404 not found')
        service = mock.MagicMock()
        service.events.return_value.update.return_value.execute.side_effect = missing
        service.events.return_value.insert.return_value.execute.return_value = {
            'id': 'evt_new', 'etag': '"t"',
        }
        with mock.patch.object(gcs, '_get_calendar_service', return_value=service):
            status, event_id = gcs._perform_appointment_sync(7)

        self.assertEqual((status, event_id), ('ok', 'evt_new'))
        insert_body = service.events.return_value.insert.call_args.kwargs['body']
        self.assertEqual(insert_body['id'], gcs._stable_appointment_event_id(7))

    def test_stable_event_ids_match_google_alphabet(self):
        apt = gcs._stable_appointment_event_id(42)
        off = gcs._stable_time_off_event_id(9)
        self.assertRegex(apt, r'^[a-v0-9]{5,1024}$')
        self.assertRegex(off, r'^[a-v0-9]{5,1024}$')
        self.assertNotEqual(apt, off)

    def test_insert_conflict_updates_stable_id(self):
        appointment_row = (
            3, '2026-09-22', '11:00', 'confirmed', 60, 0,
            'Ece', 'Kaya', '5550001122', 1, 'Berke',
            '', '', '', None, None, None,
        )
        cursor = RecordingCursor(fetchone_queue=[(True,), appointment_row, (3,)])
        conn = FakeConn(cursor)
        gcs.set_connection_provider(lambda: conn, lambda c: None)

        conflict = Exception('409 already exists')
        service = mock.MagicMock()
        service.events.return_value.insert.return_value.execute.side_effect = conflict
        service.events.return_value.update.return_value.execute.return_value = {
            'id': gcs._stable_appointment_event_id(3), 'etag': '"e"',
        }
        with mock.patch.object(gcs, '_get_calendar_service', return_value=service):
            status, event_id = gcs._perform_appointment_sync(3)

        self.assertEqual(status, 'ok')
        self.assertEqual(event_id, gcs._stable_appointment_event_id(3))
        service.events.return_value.update.assert_called()

    def test_google_execute_retries_server_error(self):
        class Fake503(Exception):
            def __init__(self):
                super().__init__('503')
                self.resp = types.SimpleNamespace(status=503)

        calls = {'n': 0}

        def make_request():
            calls['n'] += 1
            req = mock.MagicMock()
            if calls['n'] < 3:
                req.execute.side_effect = Fake503()
            else:
                req.execute.return_value = {'ok': True}
            return req

        with mock.patch.object(gcs, 'reset_calendar_service'), \
             mock.patch.object(gcs.time, 'sleep'):
            self.assertEqual(gcs._google_execute(make_request), {'ok': True})
        self.assertEqual(calls['n'], 3)


class GoogleReachabilityTest(unittest.TestCase):
    """Bağlantı kontrolü yavaş ilk SYN'i (~3 sn) kopukluk sanmamalı."""

    def test_default_timeout_tolerates_slow_first_connect(self):
        self.assertGreaterEqual(gcs.GOOGLE_API_PROBE_TIMEOUT, 8)
        seen = {}

        class FakeSock:
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, *a):
                FakeSock.closed = True
                return False

        def fake_create(addr, timeout=None):
            seen['addr'], seen['timeout'] = addr, timeout
            return FakeSock()

        with mock.patch.object(gcs.socket, 'create_connection', side_effect=fake_create):
            self.assertTrue(gcs.google_api_reachable())
        self.assertEqual(seen['addr'], ('oauth2.googleapis.com', 443))
        self.assertEqual(seen['timeout'], gcs.GOOGLE_API_PROBE_TIMEOUT)
        self.assertTrue(FakeSock.closed, 'soket kapatilmali')

    def test_unreachable_returns_false(self):
        with mock.patch.object(gcs.socket, 'create_connection', side_effect=OSError('unreachable')):
            self.assertFalse(gcs.google_api_reachable())

    def test_explicit_timeout_is_respected(self):
        seen = {}

        def fake_create(addr, timeout=None):
            seen['timeout'] = timeout
            raise OSError('x')

        with mock.patch.object(gcs.socket, 'create_connection', side_effect=fake_create):
            gcs.google_api_reachable(timeout=2)
        self.assertEqual(seen['timeout'], 2)


class EventDurationTest(unittest.TestCase):
    """Sure ve baslangic dakikasi Google'daki haliyle kaydedilir (yuvarlama yok)."""

    def _window(self, minutes, start_minute=0):
        start = datetime(2026, 9, 20, 13, start_minute, tzinfo=TZ)
        return start, start + timedelta(minutes=minutes)

    def test_duration_is_not_rounded(self):
        for raw in (15, 30, 45, 60, 75, 90, 120, 150):
            start, end = self._window(raw)
            self.assertEqual(gcs._event_duration_minutes(start, end), raw, raw)

    def test_zero_length_event_is_at_least_one_minute(self):
        start = datetime(2026, 9, 20, 13, 0, tzinfo=TZ)
        self.assertEqual(gcs._event_duration_minutes(start, start), 1)

    def test_missing_times_give_zero(self):
        self.assertEqual(gcs._event_duration_minutes(None, None), 0)

    def test_any_start_minute_and_duration_is_valid(self):
        for minute, dur in ((0, 60), (7, 30), (20, 50), (45, 45), (59, 1)):
            start, _ = self._window(dur, minute)
            self.assertTrue(gcs._inbound_time_valid(start, dur), (minute, dur))

    def test_seconds_or_empty_duration_is_invalid(self):
        start = datetime(2026, 9, 20, 13, 0, 30, tzinfo=TZ)
        self.assertFalse(gcs._inbound_time_valid(start, 60))
        start = datetime(2026, 9, 20, 13, 0, tzinfo=TZ)
        self.assertFalse(gcs._inbound_time_valid(start, 0))
        self.assertFalse(gcs._inbound_time_valid(None, 60))


class EchoDetectionTest(unittest.TestCase):
    """Yanki (ayni randevu) ile gercek tasima ayirt edilir."""

    def test_matches_same_start_and_duration(self):
        start = datetime(2026, 9, 20, 14, 0, tzinfo=TZ)
        self.assertTrue(
            gcs._times_match_appointment(start, 120, '2026-09-20', '14:00', 120)
        )

    def test_odd_duration_and_start_are_echo(self):
        start = datetime(2026, 9, 20, 14, 20, tzinfo=TZ)
        self.assertTrue(
            gcs._times_match_appointment(start, 45, '2026-09-20', '14:20', 45)
        )

    def test_duration_change_is_a_move(self):
        start = datetime(2026, 9, 20, 14, 0, tzinfo=TZ)
        self.assertFalse(
            gcs._times_match_appointment(start, 90, '2026-09-20', '14:00', 120)
        )

    def test_real_move_is_still_detected(self):
        start = datetime(2026, 9, 20, 16, 0, tzinfo=TZ)
        self.assertFalse(
            gcs._times_match_appointment(start, 120, '2026-09-20', '14:00', 120)
        )


class BlockReasonTest(unittest.TestCase):
    """Reddedilen taşıma / içe alma için sanatçıya gösterilen neden."""

    def _reason(self, hour, minute, duration, fetchall_queue=None):
        cursor = RecordingCursor(fetchall_queue=fetchall_queue)
        start = datetime(2026, 9, 25, hour, minute, tzinfo=TZ)
        return gcs._inbound_block_reason(cursor, 7, start, duration)

    def test_crossing_midnight(self):
        self.assertEqual(self._reason(23, 30, 60), 'midnight')

    def test_full_day_off(self):
        self.assertEqual(self._reason(14, 0, 60, [[(None, None)]]), 'closed_day')

    def test_partial_time_off(self):
        from datetime import time as dtime
        rows = [[(dtime(14, 0), dtime(15, 0))]]
        self.assertEqual(self._reason(14, 30, 60, rows), 'time_off')

    def test_time_off_that_does_not_overlap_is_ignored(self):
        from datetime import time as dtime
        rows = [[(dtime(9, 0), dtime(10, 0))], []]  # izin, sonra harici etkinlik yok
        self.assertEqual(self._reason(14, 0, 60, rows), 'appointment')

    def test_external_event(self):
        start = datetime(2026, 9, 25, 18, 0, tzinfo=TZ)
        rows = [[], [(start, start + timedelta(hours=1))]]  # izin yok, harici etkinlik var
        self.assertEqual(self._reason(18, 30, 60, rows), 'external')

    def test_default_is_another_appointment(self):
        self.assertEqual(self._reason(14, 0, 60, [[], []]), 'appointment')

    def test_every_reason_has_text(self):
        for key in ('midnight', 'closed_day', 'time_off', 'external', 'appointment'):
            self.assertTrue(gcs._BLOCK_REASON_TEXT[key])
        self.assertNotIn('mesai', ' '.join(gcs._BLOCK_REASON_TEXT.values()).lower())


class ImportConflictNotificationTest(unittest.TestCase):
    """Cakisma nedeniyle alinamayan Google etkinligi icin sanatciya bildirim."""

    def _call(self, cursor, push_events):
        start = datetime(2026, 9, 25, 14, 20, tzinfo=TZ)
        return gcs._notify_import_conflict(
            cursor, 7, start, 50, 'Test Etkinlik', push_events,
        )

    def test_notifies_staff_and_pushes_when_new(self):
        cursor = RecordingCursor(fetchone_queue=[None])  # 24 saatte ayni bildirim yok
        push = []
        self.assertTrue(self._call(cursor, push))
        inserts = [(s, p) for s, p in cursor.executed if 'INSERT INTO notifications' in s]
        self.assertEqual(len(inserts), 1)
        params = inserts[0][1]
        self.assertEqual(params[0], 7)
        self.assertEqual(params[1], 'gcal_import_conflict')
        self.assertIn('25.09.2026 14:20–15:10', params[3])
        self.assertEqual(len(push), 1)
        self.assertEqual(push[0][0], 7)

    def test_reason_text_is_used_in_message(self):
        cursor = RecordingCursor(fetchone_queue=[None])
        start = datetime(2026, 9, 25, 14, 20, tzinfo=TZ)
        gcs._notify_import_conflict(cursor, 7, start, 50, 'Test', [], 'closed_day')
        params = [p for s_, p in cursor.executed if 'INSERT INTO notifications' in s_][0]
        self.assertIn('tam gün izinli', params[3])

    def test_same_notification_is_not_repeated_within_24h(self):
        cursor = RecordingCursor(fetchone_queue=[(1,)])  # zaten var
        push = []
        self.assertFalse(self._call(cursor, push))
        self.assertFalse(any('INSERT INTO notifications' in s for s, _ in cursor.executed))
        self.assertEqual(push, [])


    def test_unmatched_event_is_recorded_as_busy(self):
        cursor = RecordingCursor()
        start = datetime(2026, 9, 20, 14, 0, tzinfo=TZ)
        end = start + timedelta(hours=2)
        event = {
            'id': 'foreign_1',
            'status': 'confirmed',
            'start': {'dateTime': start.isoformat()},
            'end': {'dateTime': end.isoformat()},
            'summary': 'Dis etkinlik',
        }
        gcs._apply_inbound_busy_side_effect(cursor, 'cal', event, 'unmatched')
        sqls = [s for s, _ in cursor.executed]
        self.assertTrue(any('INSERT INTO google_external_busy' in s for s in sqls))

    def test_imported_event_is_removed_from_busy(self):
        cursor = RecordingCursor()
        event = {'id': 'ours_1', 'status': 'confirmed'}
        gcs._apply_inbound_busy_side_effect(cursor, 'cal', event, 'imported')
        sql, params = cursor.executed[0]
        self.assertIn('DELETE FROM google_external_busy', sql)
        self.assertEqual(params, ('ours_1',))
        self.assertEqual(len(cursor.executed), 1)


class QueueTest(unittest.TestCase):
    """GC-2 ve GC-9: kuyruk semantigi."""

    def test_finish_item_keeps_newer_enqueued_work(self):
        cursor = RecordingCursor()
        conn = FakeConn(cursor)
        gcs._finish_item(conn, item_id=100, operation='upsert', appointment_id=42)

        sql, params = cursor.executed[0]
        self.assertIn('id <= %s', sql)
        self.assertEqual(params, (42, 100))

    def test_finish_item_scopes_time_off_the_same_way(self):
        cursor = RecordingCursor()
        conn = FakeConn(cursor)
        gcs._finish_item(conn, item_id=55, operation='upsert',
                         appointment_id=None, time_off_id=9)
        sql, params = cursor.executed[0]
        self.assertIn('id <= %s', sql)
        self.assertEqual(params, (9, 55))

    def test_busy_deferral_below_cap_reschedules(self):
        cursor = RecordingCursor(fetchone_queue=[(3,)])
        conn = FakeConn(cursor)
        dead = gcs._reschedule_item(conn, item_id=1, attempts=2, error_text=None, soon=True)
        self.assertFalse(dead)

    def test_busy_deferral_at_cap_gives_up(self):
        cursor = RecordingCursor(fetchone_queue=[(gcs.GCAL_MAX_BUSY_DEFERRALS,)])
        conn = FakeConn(cursor)
        dead = gcs._reschedule_item(conn, item_id=1, attempts=2, error_text=None, soon=True)
        self.assertTrue(dead, 'kilit surekli mesgulse is sonsuza kadar donmemeli')
        self.assertTrue(any('dead_at = NOW()' in s for s, _ in cursor.executed))


class ArtistCacheTest(unittest.TestCase):
    """GC-3: her etkinlikte sanatci sorgusu (N+1) tekrarlanmamali."""

    def test_repeated_lookups_hit_cache(self):
        gcs.reset_artists_cache()
        rows = [(1, 'Berke', []), (2, 'Tuncer', [])]
        cursor = RecordingCursor(fetchall_queue=[rows, rows, rows])
        for _ in range(25):
            self.assertEqual(gcs._load_bookable_artists(cursor), rows)
        self.assertEqual(
            len(cursor.executed), 1,
            f'25 etkinlik icin 1 sorgu beklenir, {len(cursor.executed)} calisti',
        )

    def test_reset_forces_reload(self):
        gcs.reset_artists_cache()
        rows = [(1, 'Berke', [])]
        cursor = RecordingCursor(fetchall_queue=[rows, rows])
        gcs._load_bookable_artists(cursor)
        gcs.reset_artists_cache()
        gcs._load_bookable_artists(cursor)
        self.assertEqual(len(cursor.executed), 2)


class CancelNotificationTest(unittest.TestCase):
    """GC-7: Google'dan silinen randevuda musteri bilgilendirilmeli."""

    def setUp(self):
        # Gercekte iptal mesaji yanlis silme duzeltilebilsin diye bekletilir;
        # testlerde bekleme yok.
        patcher = mock.patch.object(gcs, '_cancel_notify_grace_seconds', return_value=0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        gcs.set_cancel_notifier(None)

    def _dispatch_and_wait(self, ids):
        seen = []
        done = threading.Event()

        def notifier(appointment_ids):
            seen.append(list(appointment_ids))
            done.set()

        gcs.set_cancel_notifier(notifier)
        gcs._dispatch_cancel_notifications(ids)
        done.wait(timeout=2)
        return seen

    def test_cancelled_ids_are_dispatched(self):
        self.assertEqual(self._dispatch_and_wait([11, 12]), [[11, 12]])

    def test_nothing_dispatched_when_no_cancellations(self):
        seen = []
        gcs.set_cancel_notifier(lambda ids: seen.append(ids))
        gcs._dispatch_cancel_notifications([])
        time.sleep(0.05)
        self.assertEqual(seen, [])

    def test_notifier_failure_does_not_propagate(self):
        boom = threading.Event()

        def notifier(_ids):
            boom.set()
            raise RuntimeError('WhatsApp down')

        gcs.set_cancel_notifier(notifier)
        gcs._dispatch_cancel_notifications([5])  # patlamamali
        self.assertTrue(boom.wait(timeout=2))

    def test_inbound_delete_queues_appointment_for_notification(self):
        cursor = RecordingCursor(fetchone_queue=[
            # _load_appointment_for_inbound
            (77, 2, 'confirmed', '2026-09-20', '14:00', 120,
             'evt_x', '"tag"', 'customer', 'forearm'),
            (77,),  # _soft_cancel_from_google ... RETURNING id
        ])
        cancelled = []
        event = {'id': 'evt_x', 'status': 'cancelled',
                 'extendedProperties': {'private': {
                     'origin': 'roof', 'appointment_id': '77'}}}
        action = gcs._handle_inbound_event(cursor, event, 'cal', cancelled)
        self.assertEqual(action, 'cancel')
        self.assertEqual(cancelled, [77])

    def test_synthetic_phone_is_not_a_real_customer(self):
        synthetic = gcs._synthetic_gcal_phone('evt_abc123')
        self.assertFalse(
            gcs.is_real_customer_phone(synthetic),
            'sentetik numaraya WhatsApp gonderilmemeli',
        )
        self.assertTrue(gcs.is_real_customer_phone('5551112233'))
        self.assertTrue(gcs.is_real_customer_phone('905551112233'))


class SourceHygieneTest(unittest.TestCase):
    """GC-4/GC-6/GC-8: kaynak seviyesinde regresyon korumasi."""

    def setUp(self):
        with open(_TARGET, encoding='utf-8') as handle:
            self.src = handle.read()

    def test_no_recursive_poll_inbound_changes(self):
        body = self.src.split('def poll_inbound_changes(')[1]
        self.assertNotIn(
            'return poll_inbound_changes()', body,
            'ozyineleme yerine sinirli dongu kullanilmali',
        )

    def test_pooled_connection_never_closed_directly(self):
        """conn.close() yalnizca _disconnect'in fallback'inde bulunmali.

        Yorum satirlari sayilmaz; aranan sey gercek cagri.
        """
        calls = [
            lineno
            for lineno, line in enumerate(self.src.splitlines(), start=1)
            if line.split('#', 1)[0].strip() == 'conn.close()'
        ]
        self.assertEqual(
            len(calls), 1,
            f'havuz baglantisi yalnizca _disconnect icinde kapatilmali, satirlar: {calls}',
        )

    def test_busy_table_refresh_is_batched(self):
        self.assertIn('if existing != desired:', self.src)

    def test_off_day_import_does_not_enqueue_outbound(self):
        body = self.src.split('def _import_off_day_event(')[1].split(
            'def _handle_inbound_time_off('
        )[0]
        self.assertNotIn(
            'enqueue_time_off_sync',
            body,
            'Google\'dan gelen Off Day tekrar kuyruga yazilirsa yanki/ustune yazma olur',
        )

    def test_inbound_tick_polls_before_full_busy_rebuild(self):
        body = self.src.split('def run_gcal_inbound_tick(')[1].split('def ')[0]
        poll_at = body.find('poll_inbound_changes()')
        busy_at = body.find('refresh_external_busy()')
        self.assertGreater(poll_at, 0)
        self.assertGreater(busy_at, poll_at)


if __name__ == '__main__':
    unittest.main(verbosity=2)
