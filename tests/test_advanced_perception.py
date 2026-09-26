"""
=============================================================================
ArgusTraffic AI - Advanced Multi-Stage Perception Test Suite
=============================================================================
Tests all core components of the perception engine:
1. ModelRegistry and cryptographic integrity verification
2. SceneQualityEvaluator under normal, low-light, glare, and black-frame conditions
3. AdaptivePreprocessor (letterboxing and CLAHE low-light enhancement)
4. SmallObjectTilingEngine (slicing, offset reprojection, NMS merging)
5. TemporalDetectionFusionEngine (ghost suppression, consensus, tracking persistence)
6. PerceptionConfidenceEngine (multi-factor calibrated confidence)
7. PerceptionPipeline (full end-to-end inference lifecycle with Mock backend)
=============================================================================
"""

import hashlib
from pathlib import Path
from typing import List, Tuple
import numpy as np
import pytest

from src.core.interfaces import Detection
from src.perception import (
    ComputeBackend,
    IlluminationState,
    ModelFramework,
    ModelMetadata,
    SceneQuality,
    WeatherEstimate,
)
from src.perception.conditions.scene_quality import SceneQualityEvaluator
from src.perception.confidence import PerceptionConfidenceEngine, PerceptionConfidenceVector
from src.perception.detector.mock_adapter import MockDetectorAdapter
from src.perception.detector.registry import ModelRegistry, get_model_registry
from src.perception.fusion.temporal import TemporalDetectionFusionEngine
from src.perception.pipeline import PerceptionPipeline
from src.perception.preprocessing.pipeline import AdaptivePreprocessor
from src.perception.roi.small_object import SmallObjectTilingEngine


# =============================================================================
# 1. MODEL REGISTRY TESTS
# =============================================================================

class TestModelRegistry:
    def test_model_registration_and_retrieval(self):
        registry = ModelRegistry()
        meta = ModelMetadata(
            model_id="traffic-yolo-v8s",
            version="1.2.0",
            framework=ModelFramework.ULTRALYTICS_YOLO,
            input_size=640,
            precision="FP16",
            target_classes=["car", "bus", "truck", "motorcycle", "pedestrian"],
            sha256_checksum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            approved_for_production=True,
            expected_fps=45.0,
            expected_latency_ms=22.0,
        )
        registry.register_model(meta)

        retrieved = registry.get_model("traffic-yolo-v8s")
        assert retrieved is not None
        assert retrieved.model_id == "traffic-yolo-v8s"
        assert retrieved.version == "1.2.0"
        assert retrieved.approved_for_production is True
        assert "bus" in retrieved.target_classes

    def test_default_models_bootstrapped(self):
        registry = ModelRegistry()
        models = registry.list_models()
        assert len(models) >= 3
        model_ids = [m.model_id for m in models]
        assert "yolov8n_traffic" in model_ids
        assert "rtdetr_traffic" in model_ids
        assert "mock_test_detector" in model_ids

    def test_cryptographic_verification(self, tmp_path: Path):
        registry = ModelRegistry()
        test_file = tmp_path / "model.weights"
        content = b"ArgusTraffic verified neural network weights blob"
        test_file.write_bytes(content)
        expected_sha = hashlib.sha256(content).hexdigest()

        # Check positive verification
        assert registry.verify_checkpoint_integrity(test_file, expected_sha) is True

        # Tampered content
        tampered_file = tmp_path / "tampered.weights"
        tampered_file.write_bytes(b"Malicious poisoned payload")
        assert registry.verify_checkpoint_integrity(tampered_file, expected_sha) is False

        # Non-existent file
        missing_file = tmp_path / "missing.weights"
        assert registry.verify_checkpoint_integrity(missing_file, expected_sha) is False


# =============================================================================
# 2. SCENE QUALITY EVALUATOR TESTS
# =============================================================================

class TestSceneQualityEvaluator:
    def test_normal_scene_quality(self):
        evaluator = SceneQualityEvaluator()
        # Create a synthetic image with rich texture/contrast
        rng = np.random.default_rng(42)
        frame = rng.integers(50, 200, size=(480, 640, 3), dtype=np.uint8)

        quality = evaluator.evaluate(frame)
        assert quality.brightness > 50.0
        assert quality.contrast > 10.0
        assert quality.sharpness_score > 0.0
        assert quality.glare_ratio < 0.1
        assert not quality.is_low_light
        assert quality.overall_quality_score > 0.5

    def test_black_frame_detection(self):
        evaluator = SceneQualityEvaluator()
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        quality = evaluator.evaluate(black_frame)
        assert quality.brightness < 5.0
        assert quality.contrast < 2.0
        assert quality.sharpness_score == 0.0
        assert quality.is_blurry is True
        assert quality.is_low_light is True
        assert quality.illumination_state == IlluminationState.NIGHT

    def test_low_light_detection(self):
        evaluator = SceneQualityEvaluator(low_light_threshold=50.0)
        dim_frame = np.full((480, 640, 3), 35, dtype=np.uint8)

        quality = evaluator.evaluate(dim_frame)
        assert quality.is_low_light is True
        assert quality.illumination_state == IlluminationState.LOW_LIGHT

    def test_glare_detection(self):
        evaluator = SceneQualityEvaluator()
        # Create an image where 30% of pixels are overexposed/glare (>= 250)
        glare_frame = np.full((400, 400, 3), 120, dtype=np.uint8)
        glare_frame[:200, :] = 252

        quality = evaluator.evaluate(glare_frame)
        assert quality.glare_ratio >= 0.15
        assert quality.illumination_state == IlluminationState.GLARE


# =============================================================================
# 3. ADAPTIVE PREPROCESSOR TESTS
# =============================================================================

class TestAdaptivePreprocessor:
    def test_letterbox_dimensions(self):
        preprocessor = AdaptivePreprocessor(target_size=640)
        # 1920x1080 (16:9) frame
        original_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        dummy_quality = SceneQuality(
            brightness=100.0,
            contrast=30.0,
            sharpness_score=150.0,
            glare_ratio=0.01,
            is_low_light=False,
            is_blurry=False,
            illumination_state=IlluminationState.DAYLIGHT,
            weather_estimate=WeatherEstimate.CLEAR,
            overall_quality_score=0.9,
        )

        processed, scale, pads = preprocessor.preprocess(original_frame, dummy_quality)
        assert processed.shape == (640, 640, 3)
        assert scale == pytest.approx(640 / 1920, rel=1e-2)
        assert pads[0] == pytest.approx(0, abs=1)  # Horizontal padding 0
        assert pads[1] > 0  # Vertical padding present

    def test_clahe_low_light_enhancement(self):
        preprocessor = AdaptivePreprocessor(target_size=640)
        # Create dark frame with some subtle gradient
        dark_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dark_frame[:, :] = [20, 25, 20]
        dark_frame[100:200, 100:200] = [35, 40, 35]

        dark_quality = SceneQuality(
            brightness=25.0,
            contrast=5.0,
            sharpness_score=10.0,
            glare_ratio=0.0,
            is_low_light=True,
            is_blurry=False,
            illumination_state=IlluminationState.NIGHT,
            weather_estimate=WeatherEstimate.CLEAR,
            overall_quality_score=0.3,
        )

        enhanced, scale, pads = preprocessor.preprocess(dark_frame, dark_quality)
        assert enhanced.shape == (640, 640, 3)
        # Low light CLAHE expands local dynamic range
        assert np.max(enhanced) >= np.max(dark_frame)


# =============================================================================
# 4. SMALL-OBJECT TILING ENGINE TESTS
# =============================================================================

class TestSmallObjectTilingEngine:
    def test_tile_generation_coverage(self):
        tiler = SmallObjectTilingEngine(tile_size=640, overlap_ratio=0.20)
        # 1920x1080 image
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        tiles = tiler.generate_tiles(frame)

        assert len(tiles) >= 4
        for tile_img, off_x, off_y in tiles:
            assert tile_img.shape == (640, 640, 3)
            assert 0 <= off_x < 1920
            assert 0 <= off_y < 1080

    def test_tile_offset_reprojection_and_nms(self):
        tiler = SmallObjectTilingEngine(iou_nms_threshold=0.5)

        # Tile 1 at offset (100, 200) contains a car at local (50, 50, 150, 150)
        # Global position should become (150, 250, 250, 350)
        det_tile1 = Detection(bbox=(50.0, 50.0, 150.0, 150.0), confidence=0.88, class_id=2, class_name="car")

        # Tile 2 at offset (120, 220) contains duplicate of same car at local (30, 30, 130, 130)
        # Global position becomes (150, 250, 250, 350)
        det_tile2 = Detection(bbox=(30.0, 30.0, 130.0, 130.0), confidence=0.75, class_id=2, class_name="car")

        tile_results = [
            ([det_tile1], 100, 200),
            ([det_tile2], 120, 220),
        ]

        merged = tiler.merge_tile_detections(tile_results)
        # Overlapping duplicate detection should be suppressed via NMS, retaining the 0.88 detection
        assert len(merged) == 1
        assert merged[0].confidence == pytest.approx(0.88)
        assert merged[0].bbox == (150.0, 250.0, 250.0, 350.0)


# =============================================================================
# 5. TEMPORAL DETECTION FUSION TESTS
# =============================================================================

class TestTemporalDetectionFusionEngine:
    def test_single_frame_ghost_suppression(self):
        fusion = TemporalDetectionFusionEngine(min_hits_to_confirm=2, window_size=5)

        # Frame 1: transient single-frame false positive
        det_f1 = [Detection(bbox=(100.0, 100.0, 150.0, 150.0), confidence=0.45, class_id=0, class_name="debris")]
        fused_f1 = fusion.update(det_f1)
        # Should be suppressed because consecutive_hits (1) < min_hits_to_confirm (2)
        assert len(fused_f1) == 0

    def test_multi_frame_consensus_and_boost(self):
        fusion = TemporalDetectionFusionEngine(min_hits_to_confirm=2, window_size=5)

        # Frame 1
        det_f1 = [Detection(bbox=(100.0, 100.0, 200.0, 200.0), confidence=0.70, class_id=2, class_name="car")]
        fusion.update(det_f1)

        # Frame 2: Consistent observation in same location
        det_f2 = [Detection(bbox=(102.0, 101.0, 201.0, 202.0), confidence=0.72, class_id=2, class_name="car")]
        fused_f2 = fusion.update(det_f2)

        # Must now be confirmed and confidence boosted
        assert len(fused_f2) == 1
        assert fused_f2[0].confidence >= 0.72

    def test_temporary_dropout_cleanup(self):
        fusion = TemporalDetectionFusionEngine(min_hits_to_confirm=2, max_missed_frames=1)

        # Establish candidate over 2 frames
        d = Detection(bbox=(100.0, 100.0, 200.0, 200.0), confidence=0.85, class_id=2, class_name="truck")
        fusion.update([d])
        fusion.update([d])

        # Miss 2 consecutive frames (> max_missed_frames = 1)
        fusion.update([])
        fused_after_dropout = fusion.update([])

        assert len(fused_after_dropout) == 0
        assert len(fusion._candidates) == 0


# =============================================================================
# 6. PERCEPTION CONFIDENCE ENGINE TESTS
# =============================================================================

class TestPerceptionConfidenceEngine:
    def test_calibrated_confidence_calculation(self):
        engine = PerceptionConfidenceEngine()
        det = Detection(bbox=(100.0, 100.0, 250.0, 300.0), confidence=0.80, class_id=2, class_name="car")
        quality = SceneQuality(
            brightness=120.0,
            contrast=45.0,
            sharpness_score=85.0,
            glare_ratio=0.01,
            is_low_light=False,
            is_blurry=False,
            illumination_state=IlluminationState.DAYLIGHT,
            weather_estimate=WeatherEstimate.CLEAR,
            overall_quality_score=0.90,
        )

        conf_vector = engine.evaluate(
            detection=det,
            temporal_hits=3,
            track_age=8,
            scene_quality=quality,
        )

        assert isinstance(conf_vector, PerceptionConfidenceVector)
        assert 0.0 <= conf_vector.overall_confidence <= 1.0
        assert conf_vector.detection_confidence == 0.80
        assert conf_vector.scene_quality_confidence == 0.90
        assert conf_vector.geometry_confidence >= 0.70

    def test_geometric_sanity_penalty_on_abnormal_aspect_ratio(self):
        engine = PerceptionConfidenceEngine()
        # Degenerate pedestrian box with width 500 and height 20 (aspect ratio 25.0)
        abnormal_ped = Detection(
            bbox=(100.0, 100.0, 600.0, 120.0),
            confidence=0.90,
            class_id=0,
            class_name="pedestrian",
        )
        conf_vector = engine.evaluate(
            detection=abnormal_ped,
            temporal_hits=2,
            track_age=2,
            scene_quality=None,
        )
        # Pedestrian with aspect ratio > 1.0 must receive geometry penalty
        assert conf_vector.geometry_confidence <= 0.65


# =============================================================================
# 7. END-TO-END PERCEPTION PIPELINE INTEGRATION TESTS
# =============================================================================

class TestPerceptionPipeline:
    def test_full_pipeline_execution_with_mock_backend(self):
        # Configure pipeline using MOCK framework
        pipeline = PerceptionPipeline(
            framework=ModelFramework.MOCK,
            confidence_threshold=0.35,
            enable_tiling=False,
            enable_temporal_fusion=True,
        )

        # Synthetic test frame (720p) with realistic contrast and texture
        rng = np.random.default_rng(42)
        frame = rng.integers(60, 200, size=(720, 1280, 3), dtype=np.uint8)

        # Run 3 consecutive frames to satisfy temporal window (min_hits=2)
        res1, lat1, q1 = pipeline.process_frame(frame)
        res2, lat2, q2 = pipeline.process_frame(frame)
        res3, lat3, q3 = pipeline.process_frame(frame)

        assert q3 is not None
        assert not q3.is_blurry
        assert q3.overall_quality_score > 0.3
        assert len(res3) >= 1  # Confirmed detections
        assert lat3 > 0.0

        # Health check
        health = pipeline.get_health()
        assert health["perception_status"] == "ONLINE"
        assert health["detector_backend"] == "MOCK"
        assert health["total_frames_processed"] == 3
        assert health["temporal_fusion_active"] is True
