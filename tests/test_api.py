"""
Integration Tests for FastAPI REST Routes.
"""

import io
import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.api.app import app

client = TestClient(app)


def test_api_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "device" in data
    assert "model" in data


def test_api_telemetry_endpoint():
    response = client.get("/api/v1/telemetry")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "fps" in data
    assert "latency_ms" in data


def test_api_zones_crud():
    # 1. Get initial zones
    res_get = client.get("/api/v1/zones")
    assert res_get.status_code == 200

    # 2. Add custom zone
    new_zone = {
        "zone_id": "test_turn_lane",
        "name": "Left Turn Pocket",
        "zone_type": "lane",
        "polygon": [[100.0, 100.0], [200.0, 100.0], [200.0, 300.0], [100.0, 300.0]],
        "expected_flow": {"dx": 1.0, "dy": 0.0},
        "speed_limit_px": 25.0,
    }
    res_post = client.post("/api/v1/zones", json=new_zone)
    assert res_post.status_code == 200

    # 3. Delete zone
    res_del = client.delete("/api/v1/zones/test_turn_lane")
    assert res_del.status_code == 200


def test_api_detect_upload():
    # Generate blank test image
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    _, img_bytes = cv2.imencode(".jpg", img)

    files = {"file": ("test.jpg", io.BytesIO(img_bytes.tobytes()), "image/jpeg")}
    response = client.post("/api/v1/detect", files=files)
    assert response.status_code == 200
    data = response.json()
    assert "detections" in data
    assert "incidents" in data
    assert "inference_time_ms" in data
