import unittest

import app


class DeviceDetectionTests(unittest.TestCase):
    def test_detected_device_is_supported(self):
        device, label = app.detect_device()

        self.assertIn(device, {"cuda", "mps", "cpu"})
        self.assertTrue(label)


if __name__ == "__main__":
    unittest.main()
