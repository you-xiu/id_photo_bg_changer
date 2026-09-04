import unittest

from PIL import Image

from pictone.app import prepare_app_background


class AppBackgroundTests(unittest.TestCase):
    def test_background_covers_wide_and_tall_windows(self):
        source = Image.new("RGB", (600, 600), "#2C8CA1")

        wide = prepare_app_background(source, 1440, 900)
        tall = prepare_app_background(source, 700, 1100)

        self.assertEqual(wide.size, (1440, 900))
        self.assertEqual(tall.size, (700, 1100))
        self.assertEqual(wide.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
