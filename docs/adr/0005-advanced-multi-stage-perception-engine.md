# ADR 0005: Advanced Multi-Stage Model-Agnostic Perception Architecture

## Status
**Accepted** (2026-09-26)

## Context
Standard traffic surveillance applications suffer from high false-positive rates due to environmental flicker, shadows, headlights, and low resolution. Moreover, hardcoding systems tightly to a single detector framework (e.g. YOLO) precludes utilizing modern transformer detectors (RT-DETR) or edge-compiled engines (TensorRT, ONNX Runtime).

## Decision
We decouple and upgrade the vision subsystem into a multi-stage perception pipeline (`src/perception/`):

1. **Model-Agnostic Detector Protocol (`src/perception/detector/base.py`)**:
   - `DetectorBackend` interface with `load`, `infer`, `warmup`, `health`, and `capabilities`.
   - Supported adapters: `YOLODetectorAdapter`, `MockDetectorAdapter`, and future ONNX/TensorRT backends.
2. **Model Registry (`src/perception/detector/registry.py`)**:
   - Metadata tracking, cryptographic SHA-256 verification, and approval gates.
3. **Scene Quality & Environmental Analysis (`src/perception/conditions/scene_quality.py`)**:
   - Evaluates frame sharpness ($\sigma^2(\nabla^2 I)$), luminosity, contrast, glare, and low-light states.
4. **Adaptive Preprocessing (`src/perception/preprocessing/pipeline.py`)**:
   - Dynamic CLAHE contrast enhancement for night scenes and aspect-preserving letterbox scaling.
5. **Small Object Slicing & Tiling (`src/perception/roi/small_object.py`)**:
   - High-resolution grid tiling with global coordinate reprojection and class-aware NMS.
6. **Temporal Detection Fusion (`src/perception/fusion/temporal.py`)**:
   - Sliding-window multi-frame consensus suppressing 1-frame transient false positives.
7. **Multi-Factor Confidence Architecture (`src/perception/confidence.py`)**:
   - Calibrates detection scores with temporal hits, tracking age, spatial geometry sanity, and scene quality.

## Consequences
### Positive
- Zero vendor or model lock-in.
- Significant reduction in night-time and transient false alarms.
- High recall on distant, small objects across wide intersections.

### Negative / Trade-offs
- Slight latency overhead (1.2–2.5 ms) for Laplacian blur and histogram computation.
