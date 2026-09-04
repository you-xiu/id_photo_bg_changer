import tempfile
import unittest
from pathlib import Path

from PIL import Image

from pictone.output import (
    BatchExportRecord,
    collision_safe_path,
    save_image,
    validate_export,
    write_batch_report,
)
from pictone.preferences import AppPreferences, add_recent_file, load_preferences, save_preferences


class ExportReliabilityTests(unittest.TestCase):
    def test_save_and_validate_png_size_dpi_and_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cutout.png"
            image = Image.new("RGBA", (295, 413), (20, 30, 40, 128))

            written = save_image(image, path, dpi=300)
            report = validate_export(path, (295, 413), 300, require_alpha=True)

            self.assertEqual(written, path.stat().st_size)
            self.assertTrue(report.valid, report.issues)
            self.assertFalse(any(path.parent.glob("*.tmp")))

    def test_collision_safe_path_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "photo.jpg"
            original.write_bytes(b"existing")

            candidate = collision_safe_path(original)

            self.assertEqual(candidate.name, "photo_2.jpg")
            self.assertEqual(original.read_bytes(), b"existing")

    def test_unreachable_jpeg_limit_raises_instead_of_silently_exceeding(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Image.effect_noise((600, 800), 100).convert("RGB")
            with self.assertRaises(ValueError):
                save_image(image, Path(folder) / "tiny.jpg", dpi=300, max_bytes=1024)

    def test_batch_report_is_excel_friendly_and_collision_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "批量处理报告.csv"
            records = [BatchExportRecord("1.jpg", "1_blue.jpg", "通过", 100, "检查通过")]

            first = write_batch_report(records, path)
            second = write_batch_report(records, path)

            self.assertEqual(first, path)
            self.assertEqual(second.name, "批量处理报告_2.csv")
            self.assertTrue(first.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertIn("质量评分", first.read_text(encoding="utf-8-sig"))


class PreferenceTests(unittest.TestCase):
    def test_preferences_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            expected = AppPreferences("#E94B4B", "two", 350, 120, folder, ["a.jpg"])

            save_preferences(expected, path)
            actual = load_preferences(path)

            self.assertEqual(actual, expected)

    def test_malformed_preferences_fall_back_to_safe_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"background":"bad","size_key":"huge","dpi":"x"}', encoding="utf-8")

            actual = load_preferences(path)

            self.assertEqual(actual.background, "#438EDB")
            self.assertEqual(actual.size_key, "one")
            self.assertEqual(actual.dpi, 300)

    def test_recent_files_are_deduplicated_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            preferences = AppPreferences()
            files = []
            for index in range(8):
                path = Path(folder) / f"{index}.jpg"
                path.touch()
                files.append(path)
                add_recent_file(preferences, path)
            add_recent_file(preferences, files[-2])

            self.assertEqual(len(preferences.recent_files), 6)
            self.assertEqual(Path(preferences.recent_files[0]), files[-2].resolve())
            self.assertEqual(len({item.lower() for item in preferences.recent_files}), 6)


if __name__ == "__main__":
    unittest.main()
