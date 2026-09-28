# Security Policy

ArgusTraffic AI adheres to Zero-Trust and privacy-first engineering practices.

---

## Supported Versions

| Version | Status | Security Updates |
| :--- | :--- | :--- |
| **2.0.x (Current)** | **Production Release** | Supported (Active) |
| 1.2.x | Deprecated | Critical Patches Only |
| < 1.0 | End of Life | Unsupported |

---

## Reporting a Vulnerability

If you discover a security vulnerability within ArgusTraffic AI (e.g., JWT privilege escalation, unauthenticated RTSP stream leaks, or tamper flaws in evidence generation), please **do not open a public GitHub issue**.

Please report security vulnerabilities responsibly via email to **sapthasanka@gmail.com** or through GitHub Security Advisories.

---

## Core Security Commitments
- **Zero Hardcoded Secrets**: Default JWT secret keys are flagged and enforced with runtime alerts.
- **ANPR & License Plate Privacy**: License plates are subject to automatic configurable TTL retention policies and redaction filters in audit logs.
- **Forensic Chain-of-Custody**: All incident snapshots and video snippets are bound with immutable SHA-256 cryptographic hashes (ISO/IEC 27037).
- **Multi-Tenant RBAC**: Strict role boundaries enforced on all control plane APIs.
