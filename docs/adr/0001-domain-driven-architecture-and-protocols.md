# ADR 0001: Domain-Driven Architecture, Dependency Inversion, and Protocol Interfaces

## Status
**Accepted** (2026-09-26)

## Context
ArgusTraffic AI began as an edge-oriented computer vision prototype for detecting traffic incidents. As the system scales to support enterprise municipal deployments, distributed edge agents, and diverse deep-learning inference backends (YOLO, RT-DETR, TensorRT, ONNX), core domain algorithms (kinematics, risk equations, and incident rules) must not be tightly coupled to specific frameworks (e.g., PyTorch, OpenCV, FastAPI, or SQLite).

## Decision
1. **Domain Isolation**: We introduce formal `typing.Protocol` interfaces under `src/core/interfaces.py`:
   - `DetectionEngine`
   - `TrackingEngine`
   - `RiskEngineProtocol`
   - `IncidentEngineProtocol`
   - `StorageEngine`
   - `EventDispatcher`
2. **Mathematical Risk Engine**: We decouple risk scoring from binary incident heuristics by creating a dedicated `SpatialRiskEngine` calculating continuous Time-to-Collision (TTC), closing velocity ($\Delta v$), and proximity buffers.
3. **Strongly-Typed Configuration**: We replace scattered configuration constants with validated Pydantic models (`src/core/config_schema.py`) to eliminate magic numbers and ensure strict environment and schema validation.

## Consequences
### Positive
- Framework independence: Core traffic reasoning can be unit tested without requiring GPU hardware or OpenCV window systems.
- Pluggable backends: New model backends (e.g. TensorRT engine exports) can be added by simply implementing `DetectionEngine`.
- Auditability: Data contracts for incidents, tracks, and risks are deterministic and type-safe.

### Negative / Trade-offs
- Slight increase in initial abstraction overhead.
- Requires adapter layers when interfacing with external libraries.
