# ADR 0002: Cryptographic Forensic Evidence Manifest and ANPR Privacy Lifecycle

## Status
**Accepted** (2026-09-26)

## Context
Intelligent Transportation Systems generate sensitive evidence that may be used in municipal audits, insurance claims, and legal court proceedings. Additionally, capturing vehicle license plate numbers introduces strict data protection and privacy regulatory requirements (such as GDPR, CCPA, and regional municipal privacy acts).

## Decision
1. **Tamper-Evident Evidence Manifests**: We implement `EvidencePackage` in [`src/core/evidence_manifest.py`](file:///c:/Users/rampa/Downloads/New%20folder%20(19)/src/core/evidence_manifest.py) which builds a deterministic SHA-256 cryptographic digest across telemetry logs, frame snapshots, and kinematic traces, along with an operator audit seal.
2. **Data Minimization & ANPR Redaction**: License plates rendered in telemetry feeds, audit logs, and non-privileged interfaces are masked by default (e.g. `WP-C**-**21`).
3. **Configurable Retention & Auto-Purging**: Enforce strict Time-to-Live (TTL) expiration (`purge_expired_records`) driven by `ANPRSettings.retention_days` to prevent unmanaged, indefinite storage of identifying vehicle data.

## Consequences
### Positive
- Court-admissible proof of non-tampering for all dispatched traffic incidents.
- Automatic privacy compliance by design.
- Protected against data accumulation and liability risks.

### Negative / Trade-offs
- Slight cryptographic hashing computation overhead per confirmed incident (< 0.5 ms).
