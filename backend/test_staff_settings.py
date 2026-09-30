"""Personel takvim rengi / kazanç yüzdesi yardımcılarının testleri (DB'ye çıkmadan).

Calistirma:  python3 -m unittest test_staff_settings
"""
import re
import unittest
from decimal import Decimal

import staff_settings as ss


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((' '.join(str(sql).split()), params))

    def fetchall(self):
        return self._rows


class ColorTableTest(unittest.TestCase):
    def test_eleven_colors_with_unique_ids_names_and_valid_hex(self):
        self.assertEqual([c['id'] for c in ss.CALENDAR_COLORS], [str(i) for i in range(1, 12)])
        self.assertEqual(len({c['name_en'] for c in ss.CALENDAR_COLORS}), 11)
        self.assertEqual(len({c['name_tr'] for c in ss.CALENDAR_COLORS}), 11)
        for c in ss.CALENDAR_COLORS:
            self.assertRegex(c['hex'], r'^#[0-9A-F]{6}$')

    def test_graphite_is_reserved_and_not_selectable(self):
        self.assertEqual(ss.COLOR_BY_ID['8']['name_en'], 'Graphite')
        self.assertNotIn('8', ss.SELECTABLE_COLOR_IDS)
        self.assertEqual(len(ss.SELECTABLE_COLORS), 10)

    def test_existing_studio_colors_keep_their_names(self):
        # Mevcut personel renkleri (Tuncer/Mert/Berke/Ibrahim) adlariyla eslesir.
        self.assertEqual(ss.COLOR_BY_ID['11']['name_tr'], 'Domates')
        self.assertEqual(ss.COLOR_BY_ID['2']['name_tr'], 'Adaçayı')
        self.assertEqual(ss.COLOR_BY_ID['6']['name_tr'], 'Mandalina')
        self.assertEqual(ss.COLOR_BY_ID['5']['name_tr'], 'Muz')

    def test_label_shows_turkish_and_english_name(self):
        self.assertEqual(ss.color_label('11'), 'Domates (Tomato)')
        self.assertEqual(ss.color_label('999'), '999')


class NormalizeColorTest(unittest.TestCase):
    def test_valid_and_empty(self):
        self.assertEqual(ss.normalize_color_id('11'), '11')
        self.assertEqual(ss.normalize_color_id(2), '2')
        self.assertEqual(ss.normalize_color_id(' 10 '), '10')
        self.assertIsNone(ss.normalize_color_id(None))
        self.assertIsNone(ss.normalize_color_id(''))

    def test_invalid_reserved_or_unknown(self):
        for bad in ('8', 8, '0', '12', 'domates', '1.0', '-1'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ss.normalize_color_id(bad)


class NormalizeCommissionTest(unittest.TestCase):
    def test_only_30_50_70(self):
        for ok in (30, 50, 70, '30', '50', ' 70 '):
            self.assertIn(ss.normalize_commission_percent(ok), (30, 50, 70))

    def test_everything_else_rejected(self):
        for bad in (0, 10, 40, 49, 51, 100, -30, '', None, 'abc', '50.5', 50.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ss.normalize_commission_percent(bad)


class ShareAmountTest(unittest.TestCase):
    def test_percentages(self):
        self.assertEqual(ss.staff_share_amount(1000, 30), Decimal('300.00'))
        self.assertEqual(ss.staff_share_amount(1000, 50), Decimal('500.00'))
        self.assertEqual(ss.staff_share_amount(1000, 70), Decimal('700.00'))

    def test_default_is_50(self):
        self.assertEqual(ss.staff_share_amount(1234.50), Decimal('617.25'))

    def test_rounding_to_kurus_and_empty_price(self):
        self.assertEqual(ss.staff_share_amount('100.05', 70), Decimal('70.04'))  # 70.035 -> 70.04 (yarıya yukarı)
        self.assertEqual(ss.staff_share_amount(None, 50), Decimal('0.00'))
        self.assertEqual(ss.staff_share_amount(0, 30), Decimal('0.00'))

    def test_item_shares_add_up_to_total(self):
        items = ['1000', '2500.50', '333.33']
        total = sum((ss.staff_share_amount(i, 70) for i in items), Decimal('0.00'))
        self.assertEqual(total, Decimal('700.00') + Decimal('1750.35') + Decimal('233.33'))


class FallbackColorTest(unittest.TestCase):
    def test_no_staff_uses_reserved_graphite(self):
        self.assertEqual(ss.fallback_color_id(None), '8')
        self.assertEqual(ss.fallback_color_id(0), '8')
        self.assertEqual(ss.fallback_color_id('abc'), '8')

    def test_rotation_is_stable_distinct_and_never_reserved(self):
        first_ten = [ss.fallback_color_id(i) for i in range(1, 11)]
        self.assertEqual(len(set(first_ten)), 10)
        self.assertNotIn('8', first_ten)
        self.assertEqual(first_ten, [ss.fallback_color_id(i) for i in range(1, 11)])
        self.assertEqual(ss.fallback_color_id(11), ss.fallback_color_id(1))  # 10 renkten sonra basa doner


class ColorsInUseTest(unittest.TestCase):
    def test_groups_names_by_color_and_passes_exclusion(self):
        cur = FakeCursor([('11', 'Tuncer'), ('2', 'Mert'), ('11', 'Yeni')])
        used = ss.colors_in_use(cur, exclude_staff_id=5)
        self.assertEqual(used, {'11': ['Tuncer', 'Yeni'], '2': ['Mert']})
        sql, params = cur.executed[0]
        self.assertIn('is_active', sql.lower())
        self.assertEqual(params, (5, 5))

    def test_first_free_color_skips_used_ones(self):
        cur = FakeCursor([('1', 'A'), ('2', 'B'), ('3', 'C')])
        self.assertEqual(ss.first_free_color_id(cur), '4')

    def test_first_free_color_none_when_all_taken(self):
        cur = FakeCursor([(cid, f'P{cid}') for cid in ss.SELECTABLE_COLOR_IDS])
        self.assertIsNone(ss.first_free_color_id(cur))


if __name__ == '__main__':
    unittest.main()
