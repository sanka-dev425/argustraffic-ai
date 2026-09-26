# 🔒 Security Policy

ArgusTraffic AI adheres to Zero-Trust and privacy-first engineering practices.

---

## 🛡️ Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.2.x   | :white_check_mark: |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## 🚨 Reporting a Vulnerability

If you discover a security vulnerability within ArgusTraffic AI (e.g. JWT privilege escalation, unauthenticated RTSP stream leaks, or tamper flaws in evidence generation), please **do not open a public GitHub issue**.

Please report security vulnerabilities responsibly via email to **sapthasanka@gmail.com** or through GitHub Security Advisories.

---

## 🔐 Core Security Commitments
- **Zero Hardcoded Secrets**: Default JWT secret keys are flagged and enforced with runtime alerts.
- **ANPR & License Plate Privacy**: License plates are subject to automatic configurable TTL retention policies and redaction filters in audit logs.
- **Forensic Chain-of-Custody**: All incident snapshots and video snippets are bound with immutable SHA-256 cryptographic hashes.
