import os
import unittest
from unittest.mock import patch

from model_service import runtime
from model_service.runtime import detect_device


class DeviceDetectionTests(unittest.TestCase):
    def test_detected_device_is_supported(self):
        device, label = detect_device()

        self.assertIn(device, {"cuda", "mps", "cpu"})
        self.assertTrue(label)

    def test_apple_silicon_enables_mps_optimizations_before_torch(self):
        with (
            patch("model_service.runtime.sys.platform", "darwin"),
            patch("model_service.runtime.platform.machine", return_value="arm64"),
            patch.dict(os.environ, {}, clear=True),
        ):
            runtime._configure_mps_environment()
            self.assertEqual(os.environ["PYTORCH_MPS_FAST_MATH"], "1")
            self.assertEqual(os.environ["PYTORCH_MPS_PREFER_METAL"], "1")

    def test_other_devices_do_not_receive_mps_settings(self):
        with (
            patch("model_service.runtime.sys.platform", "win32"),
            patch.dict(os.environ, {}, clear=True),
        ):
            runtime._configure_mps_environment()
            self.assertNotIn("PYTORCH_MPS_FAST_MATH", os.environ)
            self.assertNotIn("PYTORCH_MPS_PREFER_METAL", os.environ)


if __name__ == "__main__":
    unittest.main()
