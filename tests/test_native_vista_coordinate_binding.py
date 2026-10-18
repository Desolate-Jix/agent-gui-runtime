"""根据本轮安装版真实失败独立建立的坐标绑定回归。"""
import unittest

from app.vision.model_workers.vista_openai_server import _point_payload


class NativeVistaCoordinateBindingTests(unittest.TestCase):
    def test_thousand_scale_never_matches_unit_scale_prefix(self):
        for instruction in (
            'coordinate_space=normalized_0_1000',
            'Output [x,y]. normalized_0_1000',
            'COORDINATE_SPACE=NORMALIZED_0_1000',
            '定位空白编辑区。coordinate_space=normalized_0_1000',
        ):
            with self.subTest(instruction=instruction):
                value = _point_payload('[499, 500]', instruction=instruction)
                self.assertEqual(value['status'], 'ready')
                self.assertEqual(value['point'], {
                    'x': 499.0, 'y': 500.0, 'coordinate_space': 'normalized_0_1000',
                })
                self.assertEqual(value['raw_text'], '[499, 500]')
                self.assertFalse(value['parse_repair']['applied'])

    def test_unit_scale_and_local_point_keep_distinct_units(self):
        cases = (
            ('coordinate_space=normalized_0_1', '[0.25, 0.5]', 0.25, 0.5, 'normalized_0_1'),
            ('使用normalized_0_1坐标', '[0.25, 0.5]', 0.25, 0.5, 'normalized_0_1'),
            ('coordinate_space=roi_local_point', '[320, 240]', 320.0, 240.0, 'roi_local_point'),
            ('ROI_LOCAL_POINT', '[320, 240]', 320.0, 240.0, 'roi_local_point'),
        )
        for instruction, raw, x, y, space in cases:
            with self.subTest(instruction=instruction):
                self.assertEqual(_point_payload(raw, instruction=instruction)['point'], {
                    'x': x, 'y': y, 'coordinate_space': space,
                })

    def test_embedded_non_identifier_is_not_a_coordinate_directive(self):
        for instruction in ('not_normalized_0_1', 'normalized_0_1_suffix', 'normalized_0_10', 'not_roi_local_point'):
            with self.subTest(instruction=instruction):
                point = _point_payload('[499, 500]', instruction=instruction)['point']
                self.assertEqual(point['coordinate_space'], 'normalized_0_1000')

    def test_missing_directive_keeps_default_and_bad_pair_stays_unparsed(self):
        self.assertEqual(_point_payload('[499, 500]')['point']['coordinate_space'], 'normalized_0_1000')
        value = _point_payload('no coordinates', instruction='coordinate_space=normalized_0_1000')
        self.assertEqual(value['status'], 'unparsed')
        self.assertIsNone(value['point'])


if __name__ == '__main__':
    unittest.main()
