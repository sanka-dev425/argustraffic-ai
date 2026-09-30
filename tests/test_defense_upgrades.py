"""
Unit Tests for Defense-Grade Production Upgrades:
1. AES-256-GCM Evidence Vault Encryption at Rest & Tamper Detection
2. Sub-millimeter Planar Homography Speed Calibration
3. Visual Appearance Re-ID Feature Embeddings in SpatialTracker
"""

import os
from pathlib import Path
import tempfile
import numpy as np
import pytest

from src.core.evidence_vault_crypto import VaultCryptoEngine, derive_vault_key
from src.core.edge_recorder import EdgeStorageVault, EdgeRingBuffer
from src.core.speed_engine import PerspectiveHomographyCalibrator
from src.core.tracker import SpatialTracker, Track, extract_appearance_embedding
from src.core.detector import Detection


def test_vault_crypto_encryption_and_tamper_detection():
    """Verifies AES-256 / AEAD encryption, decryption, and cryptographic tamper detection."""
    engine = VaultCryptoEngine(master_passphrase="TopSecretNationalSecurity2026!")
    sample_data = b"FORENSIC_INCIDENT_VIDEO_CHUNK_FRAME_DATA_12345"

    encrypted = engine.encrypt_bytes(sample_data, associated_data=b"EVIDENCE_INC_001")
    assert len(encrypted) > len(sample_data)
    assert encrypted != sample_data

    # Valid decryption
    decrypted = engine.decrypt_bytes(encrypted, associated_data=b"EVIDENCE_INC_001")
    assert decrypted == sample_data

    # Tamper detection: modifying a single byte in ciphertext must raise ValueError
    tampered = bytearray(encrypted)
    tampered[15] ^= 0xFF
    with pytest.raises(ValueError):
        engine.decrypt_bytes(bytes(tampered), associated_data=b"EVIDENCE_INC_001")

    # AAD mismatch: passing wrong associated data must raise ValueError
    with pytest.raises(ValueError):
        engine.decrypt_bytes(encrypted, associated_data=b"WRONG_AAD")


def test_vault_crypto_file_encryption():
    """Verifies file-level encryption and decryption on disk."""
    engine = VaultCryptoEngine()
    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = Path(tmpdir) / "incident.mp4"
        src_file.write_bytes(b"MOCK_H264_STREAM_CONTENT_HEADER_101010")

        enc_file = engine.encrypt_file(src_file)
        assert enc_file.exists()
        assert enc_file.name.endswith(".enc")

        dec_file = engine.decrypt_file(enc_file, target_path=Path(tmpdir) / "restored.mp4")
        assert dec_file.exists()
        assert dec_file.read_bytes() == b"MOCK_H264_STREAM_CONTENT_HEADER_101010"


def test_edge_storage_vault_with_encryption():
    """Verifies EdgeStorageVault locks clips with AES-256 encryption."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = EdgeStorageVault(storage_root=Path(tmpdir) / "vault")
        # Create dummy frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frames = [(0.0, frame), (0.033, frame)]

        clip_path = vault.lock_incident_clip(
            incident_id="INC_AES_001",
            frames=frames,
            metadata={"type": "WRONG_WAY", "speed_kmh": 82.5},
            encrypt_at_rest=True,
        )

        assert clip_path is not None
        assert clip_path.exists()
        assert clip_path.name.endswith(".enc")

        manifests = vault.get_pending_sync_queue()
        assert len(manifests) == 1
        assert manifests[0]["incident_id"] == "INC_AES_001"
        assert manifests[0]["encrypted"] is True
        assert manifests[0]["cipher_suite"] == "AES-256-GCM-AUTH"

        vault.shutdown(wait=True)


def test_perspective_homography_calibrator():
    """Verifies planar homography metric calculation for speed estimation."""
    calibrator = PerspectiveHomographyCalibrator(
        src_points=[
            (480.0, 300.0),
            (800.0, 300.0),
            (1150.0, 700.0),
            (130.0, 700.0),
        ],
        real_width_meters=3.65,
        real_length_meters=25.0,
    )

    # Far point to near point displacement in 1.0 second
    p_start = (640.0, 300.0)  # Near the top edge of calibration box
    p_end = (640.0, 700.0)    # Near the bottom edge of calibration box

    speed_kmh = calibrator.calculate_speed_kmh(p_start, p_end, dt_seconds=1.0)
    assert speed_kmh > 0.0
    # Over 25 meters in 1 second is ~90 km/h
    assert 60.0 <= speed_kmh <= 120.0

    d = calibrator.to_dict()
    assert d["real_width_meters"] == 3.65
    assert d["real_length_meters"] == 25.0


def test_tracker_appearance_reid():
    """Verifies SpatialTracker visual appearance feature extraction and matching."""
    tracker = SpatialTracker()
    
    # Create synthetic frame with a colored patch (vehicle)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[100:200, 100:200] = [255, 0, 0]  # Blue vehicle

    det1 = Detection(
        class_id=2,
        class_name="car",
        confidence=0.92,
        bbox=(100.0, 100.0, 200.0, 200.0),
    )

    tracked = tracker.update([det1], frame=frame)
    assert len(tracked) == 1
    t_id = tracked[0].track_id
    assert t_id is not None
    assert tracker.tracks[t_id].appearance_embedding is not None

    # Next frame: vehicle moves slightly
    det2 = Detection(
        class_id=2,
        class_name="car",
        confidence=0.90,
        bbox=(105.0, 105.0, 205.0, 205.0),
    )
    frame[105:205, 105:205] = [255, 0, 0]

    tracked2 = tracker.update([det2], frame=frame)
    assert len(tracked2) == 1
    assert tracked2[0].track_id == t_id  # Track ID persists cleanly
