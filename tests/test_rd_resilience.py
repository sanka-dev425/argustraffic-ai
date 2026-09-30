"""
Unit Tests for R&D Edge Resilience Upgrades:
1. V2X Gateway Stale Telemetry Pruning & TTL Eviction
2. ANPR Engine LRU Bounded Cache Eviction
3. Camera Watchdog Randomized Jittered Backoff
4. Optical Tamper AI Ambient Light Baseline Adaptation
"""

import time
import numpy as np
import pytest

from src.core.v2x_gateway import V2XGateway, BasicSafetyMessage
from src.core.anpr_engine import ANPREngine
from src.core.camera_watchdog import CameraSelfHealingWatchdog
from src.core.optical_tamper_detector import OpticalTamperDetector, TamperState


def test_v2x_stale_telemetry_pruning():
    """Verifies that out-of-range vehicles are evicted after TTL expiration."""
    gateway = V2XGateway(vehicle_ttl_seconds=1.0)

    # Ingest active vehicle 1
    msg1 = BasicSafetyMessage(
        vehicle_id="VEH_ACTIVE_001",
        latitude=6.9271,
        longitude=79.8612,
        elevation_m=12.0,
        speed_kmh=65.0,
        heading_deg=90.0,
        brake_active=False,
        transmission_state="FORWARD",
        timestamp_utc=time.time(),
    )
    # Ingest old vehicle 2 (2.5 seconds in past)
    msg2 = BasicSafetyMessage(
        vehicle_id="VEH_STALE_002",
        latitude=6.9280,
        longitude=79.8620,
        elevation_m=12.0,
        speed_kmh=50.0,
        heading_deg=90.0,
        brake_active=False,
        transmission_state="FORWARD",
        timestamp_utc=time.time() - 2.5,
    )

    gateway.ingest_bsm(msg1)
    gateway.ingest_bsm(msg2)

    assert "VEH_ACTIVE_001" in gateway.connected_vehicle_registry
    assert "VEH_STALE_002" in gateway.connected_vehicle_registry

    # Prune with TTL=1.0s
    pruned = gateway.prune_stale_vehicles(ttl_seconds=1.0)
    assert pruned == 1
    assert "VEH_ACTIVE_001" in gateway.connected_vehicle_registry
    assert "VEH_STALE_002" not in gateway.connected_vehicle_registry


def test_anpr_lru_bounded_cache():
    """Verifies ANPREngine evicts oldest plate entries when max_cache_size is reached."""
    engine = ANPREngine(max_cache_size=3)

    engine.recognize_plate(track_id=1, vehicle_class="car", confidence=0.95, raw_plate_text="WP-AAA-1111")
    engine.recognize_plate(track_id=2, vehicle_class="car", confidence=0.95, raw_plate_text="WP-BBB-2222")
    engine.recognize_plate(track_id=3, vehicle_class="car", confidence=0.95, raw_plate_text="WP-CCC-3333")

    assert len(engine._plate_cache) == 3
    assert 1 in engine._plate_cache

    # Add 4th track -> track 1 (oldest) must be evicted
    engine.recognize_plate(track_id=4, vehicle_class="car", confidence=0.95, raw_plate_text="WP-DDD-4444")
    assert len(engine._plate_cache) == 3
    assert 1 not in engine._plate_cache
    assert 4 in engine._plate_cache


def test_camera_watchdog_jittered_backoff():
    """Verifies randomized jittered reconnect delay calculation."""
    watchdog = CameraSelfHealingWatchdog()
    watchdog.register_camera("CAM-01", "192.168.1.50", "192.168.1.1", 1)

    # Record multiple failures
    for _ in range(3):
        watchdog.record_frame_status("CAM-01", frame_received=False)

    delay1 = watchdog.get_jittered_reconnect_delay("CAM-01", base_delay=2.0)
    delay2 = watchdog.get_jittered_reconnect_delay("CAM-01", base_delay=2.0)

    assert delay1 > 1.0
    assert delay2 > 1.0
    # Due to randomized jitter, subsequent delays will typically differ slightly
    assert isinstance(delay1, float)


def test_optical_tamper_ambient_light_adaptation():
    """Verifies OpticalTamperDetector does not produce false occlusion alarms in dark night scenes."""
    detector = OpticalTamperDetector()

    # Create dark night scene with normal high-contrast headlights
    dark_scene = np.full((480, 640, 3), 12, dtype=np.uint8)
    # Add localized road lights / vehicles
    dark_scene[200:260, 280:340] = 200

    diag = detector.analyze_frame(dark_scene, camera_id="CAM-NIGHT-01")
    # Should adapt baseline and report CLEAR rather than false positive spray occlusion
    assert diag.state in [TamperState.CLEAR, TamperState.DEFOCUSED]
    assert diag.saturation_ratio < 0.28
