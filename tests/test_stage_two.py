import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from pictone.app import PicToneApplication
from pictone.model import PHOTO_SIZES, ProcessingSettings
from pictone.quality import QualityItem, QualityReport
from pictone.widgets import PhotoViewport


class ValueStub:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class StageTwoSpecificationTests(unittest.TestCase):
    def test_photo_sizes_include_print_dimensions(self):
        expected = {
            "one": (295, 413, 25, 35),
            "two": (413, 579, 35, 49),
            "small_one": (260, 378, 22, 32),
            "small_two": (390, 567, 33, 48),
        }
        actual = {
            key: (size.width, size.height, size.width_mm, size.height_mm)
            for key, size in PHOTO_SIZES.items()
        }
        self.assertEqual(actual, expected)

    def test_output_summary_contains_pixels_print_size_dpi_color_and_limit(self):
        app = PicToneApplication.__new__(PicToneApplication)
        app.size_label = ValueStub(PHOTO_SIZES["one"].label)
        app.max_bytes = ValueStub(200)
        app.dpi = ValueStub(300)
        app.background = ValueStub("#438edb")
        app.output_summary = ValueStub()

        app._refresh_output_summary()

        self.assertEqual(
            app.output_summary.get(),
            "一寸 · 295 × 413 px\n25 × 35 mm · 300 DPI\n#438EDB · JPEG ≤ 200 KB",
        )


class StageTwoInteractionTests(unittest.TestCase):
    def test_viewport_guide_switch_only_redraws_when_state_changes(self):
        viewport = PhotoViewport.__new__(PhotoViewport)
        viewport._guides_visible = False
        viewport._redraw = Mock()

        viewport.set_guides_visible(True)
        viewport.set_guides_visible(True)
        viewport.set_guides_visible(False)

        self.assertFalse(viewport._guides_visible)
        self.assertEqual(viewport._redraw.call_count, 2)

    def test_quality_refresh_updates_score_status_and_items(self):
        app = PicToneApplication.__new__(PicToneApplication)
        app._quality_job = 9
        app.state = SimpleNamespace(
            source=Image.new("RGB", (20, 20), "white"),
            matte=Image.new("RGBA", (20, 20), (0, 0, 0, 255)),
            processing=False,
            face_report=None,
        )
        app.settings = ProcessingSettings(size_key="one")
        app.quality_score = ValueStub("--")
        app.quality_status = ValueStub("")
        app._final_result = Mock(return_value=Image.new("RGB", (295, 413), "white"))
        app._render_quality_items = Mock()
        report = QualityReport(
            (
                QualityItem("人脸数量", "1", True, ""),
                QualityItem("眼线水平", "+7.0°", False, "请旋转修正"),
            ),
            50,
        )

        with patch("pictone.app.inspect_photo", return_value=report):
            app._refresh_quality_panel()

        self.assertIsNone(app._quality_job)
        self.assertIs(app.state.face_report, report)
        self.assertEqual(app.quality_score.get(), "50")
        self.assertEqual(app.quality_status.get(), "发现 1 项需要调整")
        app._render_quality_items.assert_called_once_with(report)


if __name__ == "__main__":
    unittest.main()
