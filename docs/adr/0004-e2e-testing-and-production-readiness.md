# ADR 0004: End-to-End Testing Pyramid, Chaos Validation, and Production Readiness Gates

## Status
**Accepted** (2026-09-26)

## Context
Mission-critical Intelligent Transportation Systems (ITS) require exhaustive, deterministic verification from sensor ingestion to court-admissible evidence and operator dispatch. Automated tests must not merely confirm that components boot, but verify safety boundaries, resilience to sensor corruption, Zero-Trust access control, and seamless failover.

## Decision
1. **Canonical Golden E2E Test Suite (`tests/test_golden_e2e_pipeline.py`)**:
   - Executes and verifies the complete 9-stage sequence:
     `Frame Ingestion -> YOLOv8 Detection -> Spatial Tracking -> Geofencing -> Spatial Risk Engine -> Incident Decision -> Persistent SQLite -> SHA-256 Evidence Manifest -> FastAPI REST/WebSocket Query`.
2. **Chaos & Resilience Engineering (`tests/test_chaos_and_resilience.py`)**:
   - Injects pure black, white saturation, Gaussian noise, and atypical resolution frames.
   - Tests extreme load bursts (100 simultaneous detections) and rapid occlusion track recovery.
3. **Zero-Trust Security & RBAC Verification (`tests/test_security_and_rbac.py`)**:
   - Verifies PBKDF2-SHA256 salting, granular RBAC matrices (Super Admin, Operator, Auditor, Viewer), sliding-window rate limiting, and polygon vertex injection sanitization.
4. **Automated Production Readiness Gate (`argus verify production`)**:
   - Audits 8 core architectural pillars: Configuration, Vision Acceleration, Risk Equations, Forensic Evidence Chain, RBAC Security, Digital Twin Simulator, V2X Gateway, and Copilot Decision Support.

## Consequences
### Positive
- Guarantees zero silent failures on edge cameras or corrupted video feeds.
- Provides provable validation for municipal certifications and safety audits.
- Delivers reproducible CI/CD test gates.
