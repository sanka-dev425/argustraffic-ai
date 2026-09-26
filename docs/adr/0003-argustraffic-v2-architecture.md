# ADR 0003: ArgusTraffic V2 Architecture: World Model, Digital Twin, V2X Boundary, and Traffic Copilot

## Status
**Accepted** (2026-09-26)

## Context
ArgusTraffic AI has evolved from localized single-camera incident detection to a city-scale, edge-first Intelligent Transportation Systems (ITS) platform. Modern municipal operations require holistic corridor-level awareness, predictive "what-if" scenario evaluation, connected vehicle (V2X) interoperability, and human-in-the-loop decision intelligence without sacrificing modularity or open-source accessibility.

## Decision
We introduce four foundational pillars for ArgusTraffic V2:

1. **City & Corridor World Model (`src/core/world_model.py`)**:
   - Represents physical roadway topology: `Lane -> Approach -> Intersection -> Corridor -> City`.
   - Explicit state tracking for dynamic entities (vehicles, pedestrians, emergency units) with confidence metrics.

2. **Digital Twin & What-If Simulation Engine (`src/core/digital_twin.py`)**:
   - Implements macroscopic flow and queue propagation models (Greenshields / Webster).
   - Allows operators to simulate lane closures, demand spikes, and adverse weather before executing interventions.

3. **V2X Gateway Abstraction (`src/core/v2x_gateway.py`)**:
   - Standardized Connected Vehicle message schemas (`BSM`, `SPaT`, `MAP`, `RSA`, `EVA`) adhering to SAE J2735 and ETSI ITS guidelines.
   - Provides cooperative perception without binding core logic to proprietary radio hardware.

4. **Traffic Copilot & Decision Support (`src/core/copilot.py`)**:
   - Natural-language diagnostic reasoning with causal explanation.
   - Strict safety policy: `READ -> ANALYZE -> RECOMMEND -> SIMULATE -> APPROVE -> EXECUTE`. AI recommendations remain strictly advisory until authorized by a human operator.

## Consequences
### Positive
- Enables multi-intersection and corridor-level traffic management.
- Zero risk of unauthorized autonomous physical actuation on municipal traffic signals.
- Standard-compliant V2X ingestion alongside camera vision.

### Negative / Trade-offs
- Slight state memory footprint increase for tracking corridor-level world entities.
