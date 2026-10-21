# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf", "topo-map-processor[parse]>=0.1.25", "shapely"]
# ///

"""Regression tests using small generated PDFs; run with `uv run test_parse.py`."""

import unittest

import pymupdf

from parse import has_blue_lines, locate_other_layer_name


def add_grid(doc, layer, segments=70, count=12, color=(0, 0, 1), disconnected=False,
             winding=False):
    page = doc[0]
    shape = page.new_shape()
    for i in range(count):
        points = []
        for j in range(segments + 1):
            along = 100 + 800 * j / segments
            across = 100 + i * 50
            # A little curvature resembles the projected SOI grid.
            across += (100 if winding else 1) * (1 if j % 2 else 0)
            points.append((along, across) if i % 2 else (across, along))
        if disconnected:
            for j in range(0, segments, 2):
                shape.draw_line(points[j], points[j + 1])
        else:
            shape.draw_polyline(points)
    shape.finish(color=color, closePath=False, oc=layer)
    shape.commit()


class GridDetectionTests(unittest.TestCase):
    def setUp(self):
        self.doc = pymupdf.open()
        self.doc.new_page(width=1000, height=1000)
        self.layer = self.doc.add_ocg('Other 5')

    def tearDown(self):
        self.doc.close()

    def reopen(self):
        # MuPDF caches the UI configuration before later OCGs are added.
        data = self.doc.tobytes()
        self.doc.close()
        self.doc = pymupdf.open(stream=data, filetype='pdf')

    def test_connected_short_segments_are_grid_lines(self):
        add_grid(self.doc, self.layer)
        self.assertTrue(has_blue_lines(self.doc, 'Other 5', 0.1))

    def test_single_segment_lines_still_work(self):
        add_grid(self.doc, self.layer, segments=1)
        self.assertTrue(has_blue_lines(self.doc, 'Other 5', 0.1))

    def test_disconnected_short_segments_do_not_form_long_lines(self):
        add_grid(self.doc, self.layer, disconnected=True)
        self.assertFalse(has_blue_lines(self.doc, 'Other 5', 0.1))

    def test_winding_blue_paths_are_not_grid_lines(self):
        add_grid(self.doc, self.layer, winding=True)
        self.assertFalse(has_blue_lines(self.doc, 'Other 5', 0.1))

    def test_other_colors_are_not_blue_grid_lines(self):
        add_grid(self.doc, self.layer, color=(0, 0, 0))
        self.assertFalse(has_blue_lines(self.doc, 'Other 5', 0.1))

    def test_lines_in_another_layer_do_not_count(self):
        add_grid(self.doc, self.layer)
        self.assertFalse(has_blue_lines(self.doc, 'Other 4', 0.1))

    def test_requires_more_than_ten_lines(self):
        add_grid(self.doc, self.layer, count=10)
        self.assertFalse(has_blue_lines(self.doc, 'Other 5', 0.1))

    def test_copyright_must_belong_to_the_grid_layer(self):
        add_grid(self.doc, self.layer)
        copyright_layer = self.doc.add_ocg('Other 4')
        self.doc[0].insert_text((30, 30), 'COPYRIGHT', oc=copyright_layer)
        self.reopen()
        # Page-wide text would incorrectly select Other 5 here.
        self.assertIsNone(locate_other_layer_name(self.doc, True, 0.1))
        add_grid(self.doc, copyright_layer)
        self.assertEqual(locate_other_layer_name(self.doc, True, 0.1), 'Other 4')

    def test_detection_preserves_layer_visibility(self):
        add_grid(self.doc, self.layer)
        self.doc[0].insert_text((30, 30), 'COPYRIGHT', oc=self.layer)
        self.doc.set_layer_ui_config(0, action=2)
        before = self.doc.layer_ui_configs()
        self.assertEqual(locate_other_layer_name(self.doc, True, 0.1), 'Other 5')
        self.assertEqual(self.doc.layer_ui_configs(), before)

    def test_flattened_pdf_uses_fallback(self):
        with pymupdf.open() as doc:
            doc.new_page()
            doc[0].insert_text((30, 30), 'COPYRIGHT')
            self.assertIsNone(locate_other_layer_name(doc, True, 0.1))


if __name__ == '__main__':
    unittest.main()
