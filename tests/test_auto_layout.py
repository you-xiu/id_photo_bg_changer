import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from pictone.engine import composition_crop_box, render_cutout, render_photo
from pictone.face import FaceDetection, suggest_layout
from pictone.model import ProcessingSettings


class CompositionCropTests(unittest.TestCase):
    def test_zoom_out_extends_top_and_sides_and_anchors_bottom(self):
        box = composition_crop_box((800, 1200), (295, 413), 95, 0, 0)
        self.assertLess(box[0], 0)
        self.assertLess(box[1], 40)
        self.assertGreater(box[2], 800)
        self.assertEqual(box[3], 1200)

    def test_regular_zoom_stays_inside_source(self):
        box = composition_crop_box((1600, 900), (295, 413), 120, 10, -5)
        self.assertGreaterEqual(box[0], 0)
        self.assertGreaterEqual(box[1], 0)
        self.assertLessEqual(box[2], 1600)
        self.assertLessEqual(box[3], 900)

    def test_original_preview_extends_edge_pixels_without_black_border(self):
        source = Image.new("RGB", (800, 1200), (214, 226, 235))
        settings = ProcessingSettings(zoom=95)
        output = render_photo(source, settings, original=True)
        pixels = np.asarray(output)
        self.assertEqual(output.size, (295, 413))
        self.assertTrue(np.all(pixels == (214, 226, 235)))

    def test_transparent_cutout_supports_extended_crop(self):
        source = Image.new("RGB", (800, 1200), "white")
        matte = Image.new("RGBA", source.size, (80, 90, 100, 255))
        settings = ProcessingSettings(zoom=95)
        output = render_cutout(source, settings, matte)
        alpha = np.asarray(output.getchannel("A"))
        self.assertEqual(output.size, (295, 413))
        self.assertTrue((alpha[0] == 0).any())
        self.assertGreater(float((alpha[-1] > 0).mean()), 0.9)


class AutoLayoutTests(unittest.TestCase):
    def _suggest(self, eye_tilt):
        face = FaceDetection(
            box=(250.0, 180.0, 300.0, 390.0),
            landmarks=((305.0, 320.0), (455.0, 320.0 + np.tan(np.radians(eye_tilt)) * 150.0),
                       (380.0, 390.0), (325.0, 480.0), (435.0, 480.0)),
            score=0.99,
        )
        rgb = np.zeros((1200, 800, 3), dtype=np.uint8)
        matte = Image.new("RGBA", (800, 1200), (0, 0, 0, 0))
        matte.paste((10, 10, 10, 255), (210, 110, 590, 1200))
        with patch("pictone.face.detect_faces", return_value=[face]):
            return suggest_layout(rgb, 295 / 413, matte)

    def test_tight_portrait_is_really_scaled_down(self):
        suggestion = self._suggest(0.0)
        self.assertGreaterEqual(suggestion["zoom"], 90)
        self.assertLess(suggestion["zoom"], 100)
        self.assertEqual(suggestion["offset_y"], 0)
        self.assertAlmostEqual(suggestion["face_ratio"], 0.35, delta=0.01)

    def test_small_detector_tilt_is_ignored(self):
        self.assertEqual(self._suggest(2.5)["rotation"], 0.0)

    def test_clear_detector_tilt_is_corrected(self):
        self.assertGreater(self._suggest(4.0)["rotation"], 0.0)


if __name__ == "__main__":
    unittest.main()
