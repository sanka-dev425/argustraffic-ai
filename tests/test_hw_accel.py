"""
ArgusTraffic AI - Hardware-Accelerated Video Decoding Unit Tests
Validates NVDEC, VAAPI, D3D11, and CPU fallback decoder management and telemetry.
Author: Saptha Sanka (ArgusTraffic Autonomous Systems)
"""

import unittest
from fastapi.testclient import TestClient

from src.api.app import app
from src.utils.video_stream import (
    HardwareDecodeManager,
    HardwareAccelerationBackend,
    HardwareAcceleratedCapture,
    VideoStream,
)


class TestHardwareAcceleration(unittest.TestCase):
    """Test suite for Hardware-Accelerated Video Decoding subsystem."""

    def setUp(self):
        self.client = TestClient(app)
        self.mgr = HardwareDecodeManager()

    def test_hardware_silicon_detection(self):
        """Validates detection of hardware video decoders."""
        caps = self.mgr.detected_capabilities
        self.assertIn("nvdec", caps)
        self.assertIn("vaapi", caps)
        self.assertIn("d3d11va", caps)
        self.assertIn("gpu_name", caps)

    def test_hardware_telemetry_payload(self):
        """Validates telemetry format and 16 4K stream limits."""
        telem = self.mgr.get_telemetry()
        self.assertEqual(telem["status"], "OPERATIONAL")
        self.assertEqual(telem["max_concurrent_4k_streams"], 16)
        self.assertGreaterEqual(telem["active_stream_channels"], 1)
        self.assertIn("asic_decode_load_pct", telem)
        self.assertIn("zero_copy_vram_mb", telem)

    def test_hardware_capture_synthetic_fallback(self):
        """Validates zero-copy frame retrieval from hardware capture."""
        cap = self.mgr.create_hw_capture(source="synthetic", channel_id="TEST-CH-01")
        ret, frame = cap.read_frame()
        self.assertTrue(ret)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[0], 720)
        self.assertEqual(frame.shape[1], 1280)
        cap.release()

    def test_video_stream_with_hw_accel(self):
        """Validates unified VideoStream handler using hardware manager."""
        stream = VideoStream(source="synthetic")
        ret, frame = stream.read_frame()
        self.assertTrue(ret)
        self.assertIsNotNone(frame)
        stream.release()

    def test_api_hwaccel_endpoint(self):
        """Validates GET /api/v1/edge/hwaccel endpoint."""
        resp = self.client.get("/api/v1/edge/hwaccel")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "OPERATIONAL")
        self.assertIn("active_backend", data)
        self.assertEqual(data["max_concurrent_4k_streams"], 16)

    def test_api_streams_endpoint(self):
        """Validates GET /api/v1/edge/streams multi-channel endpoint."""
        resp = self.client.get("/api/v1/edge/streams")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_streams"], 16)
        self.assertEqual(len(data["streams"]), 16)
        self.assertEqual(data["streams"][0]["channel_id"], "CAM-01")
        self.assertEqual(data["streams"][0]["resolution"], "3840x2160 (4K UHD)")


if __name__ == "__main__":
    unittest.main()
