# ArgusTraffic AI — Enterprise System Architecture & Specification

## 1. High-Level Vision & Purpose
**ArgusTraffic AI** is an industrial-grade, edge-native Intelligent Transportation Systems (ITS) platform that converts video sensor streams into real-time spatial telemetry, automated incident detection, multi-signal risk assessments, and forensic evidence packages.

---

## 2. Layered Domain Architecture

```mermaid
flowchart TD
    subgraph EdgePlane ["1. Edge Vision & Sensor Plane"]
        A1[RTSP Camera / USB / MP4 Stream] --> A2[Frame Ingestion & Letterbox]
        A2 --> A3[Detection Engine Protocol - YOLO / RT-DETR]
        A3 --> A4[Spatial Velocity Tracking Engine]
        A4 --> A5[Lane & Polygonal Geofence Mapping]
    end

    subgraph IntelligencePlane ["2. Spatial & Traffic Intelligence Plane"]
        B1[Spatial Risk Engine - Continuous TTC & Delta-V]
        B2[Autonomous Incident Decision Rules]
        B3[ANPR & Speed Estimation Engine]
        B4[Anomaly & Stop-and-Go Density Engine]
    end

    subgraph ForensicPlane ["3. Forensic & Evidence Plane"]
        C1[Cryptographic SHA-256 Evidence Manifest]
        C2[Incident Audit Store - SQLite / Edge Journal]
        C3[Automated Forensic PDF/JSON Exporter]
        C4[Role-Based Access Control - RBAC]
    end

    subgraph InterfacesPlane ["4. Decoupled Interfaces Plane"]
        D1[Video Plane: MJPEG / WebRTC Stream]
        D2[Control Plane: REST APIs & Swagger UI]
        D3[Telemetry Plane: Real-Time WebSockets]
        D4[UI Command Center: Institutional Dashboard]
    end

    EdgePlane --> IntelligencePlane
    IntelligencePlane --> ForensicPlane
    ForensicPlane --> InterfacesPlane
```

---

## 3. Core Protocols & Design Principles

The platform strictly enforces the **Dependency Inversion Principle (DIP)**:

- `DetectionEngine` ([`src/core/interfaces.py`](file:///c:/Users/rampa/Downloads/New%20folder%20(19)/src/core/interfaces.py)): Decouples object detection from specific deep-learning frameworks (PyTorch, ONNX Runtime, TensorRT).
- `TrackingEngine` ([`src/core/interfaces.py`](file:///c:/Users/rampa/Downloads/New%20folder%20(19)/src/core/interfaces.py)): Isolates multi-object association and Kalman filtering from vision inputs.
- `RiskEngineProtocol` ([`src/core/interfaces.py`](file:///c:/Users/rampa/Downloads/New%20folder%20(19)/src/core/interfaces.py)): Evaluates mathematical Time-to-Collision (TTC) and proximity vectors independently of downstream notification adapters.
- `PlatformConfig` ([`src/core/config_schema.py`](file:///c:/Users/rampa/Downloads/New%20folder%20(19)/src/core/config_schema.py)): Strongly-typed Pydantic settings ensuring zero hardcoded magic numbers.

---

## 4. Architectural Decision Records (ADRs)
- [ADR 0001: Domain-Driven Architecture, Dependency Inversion, and Protocol Interfaces](docs/adr/0001-domain-driven-architecture-and-protocols.md)
- [ADR 0002: Cryptographic Forensic Evidence Manifest and ANPR Privacy Lifecycle](docs/adr/0002-cryptographic-evidence-and-privacy-lifecycle.md)
